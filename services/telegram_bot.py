"""Telegram Bot service orchestrating the research and narration script pipeline."""

import asyncio
import logging
import re
from pathlib import Path

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents.animation_planner import AnimationPlannerAgent
from agents.evaluator import EvaluatorAgent
from agents.narrator import NarratorAgent
from agents.researcher import ResearcherAgent
from agents.scene_animator import SceneAnimatorAgent
from agents.script_writer import ScriptWriterAgent, parse_duration_to_seconds
from config.settings import Settings, get_settings
from core.audio_utils import format_duration, get_wav_duration
from core.caption_utils import save_srt_subtitles
from core.cost_tracker import (
    PipelineComponent,
    get_cost_tracker,
    track_component,
)
from core.database import DatabaseManager, get_db_manager
from core.models import (
    AnimationStoryboard,
    AnimationStyle,
    NarrationPlan,
    NarrationStoryboard,
    ProjectSession,
    ResearchReport,
    SceneAnimation,
    SceneAudio,
    Script,
    WorkflowState,
)
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine
from services.renderer import AnimationRenderer
from services.youtube_publisher import YouTubePublisher

logger = logging.getLogger(__name__)


def extract_target_duration(text: str, default_minutes: int = 10) -> str:
    """Extract requested video duration from topic string, or default to configured duration."""
    # Match MM:SS or M:SS e.g. "1:30", "01:30", "2:45 min", "1:30 minute video", "0:45"
    mmss_match = re.search(r"(?:^|[^\w:])(\d{1,2}):(\d{2})(?!\d)", text)
    if mmss_match:
        m, s = int(mmss_match.group(1)), int(mmss_match.group(2))
        total_sec = m * 60 + s
        if total_sec > 0:
            if total_sec < 60:
                return f"{total_sec} seconds"
            if s == 0:
                return f"{m} minutes"
            return f"{m}m {s:02d}s"

    # Match composite min + sec e.g. "1m 30s", "1 min 30 sec", "1m30s"
    min_sec_match = re.search(
        r"(?<!:)\b(\d+)\s*(?:minutes?|mins?|m)\s*(\d+)\s*(?:seconds?|secs?|s)\b",
        text,
        re.IGNORECASE,
    )
    if min_sec_match:
        m, s = int(min_sec_match.group(1)), int(min_sec_match.group(2))
        total_sec = m * 60 + s
        if total_sec < 60:
            return f"{total_sec} seconds"
        if s == 0:
            return f"{m} minutes"
        return f"{m}m {s:02d}s"

    # Match minutes e.g. "5 min", "3-minute", "15 minutes", "2m", "3-min"
    # Note (?<!:) prevents matching the seconds part of 1:30
    min_match = re.search(
        r"(?<!:)\b(\d+(?:\.\d+)?)[-\s]*(?:minutes?|mins?|m)\b", text, re.IGNORECASE
    )
    if min_match:
        val = min_match.group(1)
        val_str = str(int(float(val))) if float(val).is_integer() else str(float(val))
        return f"{val_str} minutes"

    # Match seconds e.g. "30s", "45 seconds", "90 sec", "45-second"
    sec_match = re.search(
        r"(?<!:)\b(\d+(?:\.\d+)?)[-\s]*(?:seconds?|secs?|s)\b", text, re.IGNORECASE
    )
    if sec_match:
        val = sec_match.group(1)
        val_str = str(int(float(val))) if float(val).is_integer() else str(float(val))
        return f"{val_str} seconds"

    return f"~{default_minutes} minutes"


def split_message_chunks(text: str, max_chars: int = 4000) -> list[str]:
    """Split long message text into clean chunks bounded by max_chars.

    Prefers splitting cleanly at paragraph breaks (\\n\\n), then line breaks (\\n),
    preventing mid-entity markdown truncation whenever possible.
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        candidate = f"{current_chunk}\n\n{para}" if current_chunk else para
        if len(candidate) <= max_chars:
            current_chunk = candidate
            continue

        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

        if len(para) <= max_chars:
            current_chunk = para
            continue

        lines = para.split("\n")
        for line in lines:
            line_candidate = f"{current_chunk}\n{line}" if current_chunk else line
            if len(line_candidate) <= max_chars:
                current_chunk = line_candidate
                continue

            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            if len(line) <= max_chars:
                current_chunk = line
                continue

            # Hard fallback: slice line in increments of max_chars
            for k in range(0, len(line), max_chars):
                sub = line[k : k + max_chars]
                if k + max_chars < len(line):
                    chunks.append(sub)
                else:
                    current_chunk = sub

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text]


class TelegramBotService:
    """Async Telegram Bot orchestrating research, scripting, animation, and video production."""

    def __init__(
        self,
        settings: Settings | None = None,
        db: DatabaseManager | None = None,
    ):
        self.settings = settings or get_settings()
        self.db = db or get_db_manager()
        self.state_machine = PipelineStateMachine(db=self.db)
        self.researcher = ResearcherAgent(settings=self.settings)
        self.evaluator = EvaluatorAgent(settings=self.settings)
        self.script_writer = ScriptWriterAgent(settings=self.settings)
        self.narrator = NarratorAgent(settings=self.settings)
        self.planner = AnimationPlannerAgent(settings=self.settings)
        self.animator = SceneAnimatorAgent(settings=self.settings)
        self.renderer = AnimationRenderer(settings=self.settings)
        self.youtube_publisher = YouTubePublisher(settings=self.settings)
        self.app: Application | None = None

    def _is_user_authorized(
        self, user_id: int | str | None, username: str | None = None
    ) -> bool:
        """Check if user is permitted to interact with the bot."""
        allowed = self.settings.telegram_allowed_users
        if not allowed:
            return True
        allowed_str = [str(x).lower().lstrip("@") for x in allowed]
        if user_id is not None and str(user_id) in allowed_str:
            return True
        return bool(username and username.lower().lstrip("@") in allowed_str)

    def _get_project_video_duration(self, session: ProjectSession) -> float:
        """Calculate the project's target or actual video duration in seconds.

        Priority order:
        1. Narration storyboard total audio duration (if synthesized)
        2. Script scenes total duration (if script generated)
        3. Parsed target duration from topic text
        4. Default video duration from settings
        """
        if (
            session.narration_storyboard
            and session.narration_storyboard.total_duration_seconds > 0
        ):
            return float(session.narration_storyboard.total_duration_seconds)

        if session.script and session.script.scenes:
            script_duration = sum(s.duration_seconds for s in session.script.scenes)
            if script_duration > 0:
                return float(script_duration)

        if session.topic:
            target_str = extract_target_duration(
                session.topic, self.settings.default_video_duration_minutes
            )
            parsed_sec = parse_duration_to_seconds(target_str)
            if parsed_sec > 0:
                return float(parsed_sec)

        return float(self.settings.default_video_duration_minutes * 60)

    async def build_application(self) -> Application:
        """Build and configure the python-telegram-bot Application."""
        if not self.settings.telegram_bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is not configured in environment or .env"
            )

        app = (
            Application.builder()
            .token(self.settings.telegram_bot_token)
            .connect_timeout(30.0)
            .read_timeout(float(self.settings.telegram_request_timeout_seconds))
            .write_timeout(float(self.settings.telegram_request_timeout_seconds))
            .pool_timeout(30.0)
            .media_write_timeout(float(self.settings.telegram_upload_timeout_seconds))
            .post_init(self._post_init)
            .build()
        )

        # Command Handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(CommandHandler("status", self._handle_status))
        app.add_handler(CommandHandler("cancel", self._handle_cancel))

        # Inline Button Callback Handler
        app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        # Plain Text Message Handler (Topic submission & review feedback)
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        self.app = app
        return app

    async def _post_init(self, application: Application) -> None:
        """Post-init hook invoked by PTB to configure commands."""
        await self.setup_bot_commands()

    async def setup_bot_commands(self) -> None:
        """Register bot commands menu with Telegram for native auto-complete."""
        if not self.app or not self.app.bot:
            return
        commands = [
            BotCommand("start", "Welcome message & pipeline overview"),
            BotCommand("help", "Detailed guide & usage instructions"),
            BotCommand("status", "Check active project status"),
            BotCommand("cancel", "Cancel current active project"),
        ]
        try:
            await self.app.bot.set_my_commands(commands)
            logger.info("Telegram bot commands registered successfully.")
        except (TelegramError, RuntimeError, OSError) as exc:
            logger.warning("Failed to register bot commands with Telegram: %s", exc)

    # ==========================================================================
    # Command Handlers
    # ==========================================================================

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command, sending a welcoming overview of the pipeline to authorized users."""
        if not update.effective_user or not update.effective_chat:
            return
        if not self._is_user_authorized(
            update.effective_user.id, update.effective_user.username
        ):
            await update.effective_chat.send_message(
                "⛔ You are not authorized to use this bot."
            )
            return

        welcome_text = (
            "✨ *Welcome to Curiosity On Demand!* ✨\n\n"
            "Curiosity On Demand turns any curiosity into an educational animated video with synchronized AI voiceover:\n\n"
            "1. 🔍 *Grounded Research:* In-depth web research using Gemini with Google Search.\n"
            "2. 📋 *Concept Review:* Review findings and approve or request adjustments.\n"
            "3. ✍️ *Scene Scripting:* Scene-by-scene narration script synthesis.\n"
            "4. 🎙️ *Voice Direction:* Voice talent planning & Gemini TTS audio preview.\n"
            "5. 🎨 *Visual Styling:* Animation art direction & rendered scene frame preview.\n"
            "6. 🎬 *Full Rendering:* Canvas/SVG animations rendered to master MP4 video.\n"
            "7. 🚀 *YouTube Publishing:* One-click publish to your YouTube channel as video or Shorts.\n\n"
            "👉 *Send a topic to get started!*\n"
            "_(e.g. `How do black holes evaporate? (2 min short)` or `Quantum computing explained (5 min)`)_\n\n"
            "💡 _Tip: Videos ≤ 2 minutes are automatically generated in vertical 9:16 format for YouTube Shorts!_"
        )
        await update.effective_chat.send_message(
            welcome_text, parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command, providing comprehensive usage instructions and workflow guidance."""
        if not update.effective_chat:
            return
        help_text = (
            "📖 *Curiosity On Demand - Help & Guide*\n\n"
            "*How It Works:*\n"
            "• *Start a Project:* Send any curiosity or educational topic. You can specify a duration like `2m short` or `5 min`.\n"
            "• *Format:* Videos ≤ 2 minutes are automatically rendered in vertical 9:16 format (Shorts style); longer videos use 16:9 widescreen.\n"
            "• *Human-in-the-Loop Review:* At each stage, click *Approve* to advance or reply with text to refine:\n"
            "  1. *Research summary* — review facts, concepts, and storytelling angles.\n"
            "  2. *Narration script* — review scene breakdown and spoken script.\n"
            "  3. *Voice sample* — listen to TTS audio preview and adjust tone/voice.\n"
            "  4. *Visual style frame* — review rendered frame snapshot and color palette.\n"
            "  5. *Final video* — receive MP4 preview & publish to YouTube with one tap.\n\n"
            "*Commands:*\n"
            "• `/start` - Show welcome message and pipeline overview.\n"
            "• `/status` - Check active project progress, stage, and resource costs.\n"
            "• `/cancel` - Cancel the current active project.\n"
            "• `/help` - Show this guide."
        )
        await update.effective_chat.send_message(
            help_text, parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command, reporting current project state, topic, and identifier."""
        if not update.effective_chat:
            return
        active_project = await self.db.get_active_project_for_chat(
            update.effective_chat.id
        )
        if not active_project:
            await update.effective_chat.send_message(
                "ℹ️ No active project found. Send a topic to start one!"
            )
            return

        msg = (
            f"🔍 *Active Project Status*\n\n"
            f"• *Topic:* {active_project.topic}\n"
            f"• *State:* `{active_project.state.value}`\n"
            f"• *Project ID:* `{active_project.project_id[:8]}...`\n"
            f"• *Updated:* {active_project.updated_at}"
        )
        await update.effective_chat.send_message(msg, parse_mode=ParseMode.MARKDOWN)

    async def _handle_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /cancel command, marking the active project as cancelled."""
        if not update.effective_chat:
            return
        active_project = await self.db.get_active_project_for_chat(
            update.effective_chat.id
        )
        if not active_project:
            await update.effective_chat.send_message("No active project to cancel.")
            return

        await self.state_machine.transition(
            active_project.project_id,
            WorkflowState.FAILED,
            error_message="Cancelled by user.",
        )
        await update.effective_chat.send_message("❌ Project cancelled.")

    # ==========================================================================
    # Message Handlers
    # ==========================================================================

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle user text messages: topic submissions or review feedback."""
        if (
            not update.effective_user
            or not update.effective_chat
            or not update.message
            or not update.message.text
        ):
            return
        if not self._is_user_authorized(
            update.effective_user.id, update.effective_user.username
        ):
            await update.effective_chat.send_message("⛔ You are not authorized.")
            return

        text = update.message.text.strip()
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # Check if there is an active project waiting for review or running
        active_project = await self.db.get_active_project_for_chat(chat_id)

        if active_project:
            if active_project.state == WorkflowState.AWAITING_RESEARCH_APPROVAL:
                # User provided feedback on the research summary
                await update.message.reply_text(
                    f"📝 *Research feedback received:*\n_{text}_\n\n"
                    f"🔄 Re-running research & evaluation loop with your feedback...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(
                    self._run_research_pipeline(
                        active_project.project_id, user_feedback=text
                    )
                )
                return

            if active_project.state == WorkflowState.AWAITING_SCRIPT_APPROVAL:
                # User provided feedback on the narration script
                await update.message.reply_text(
                    f"📝 *Script feedback received:*\n_{text}_\n\n"
                    f"✍️ Revising scene-by-scene script with your feedback...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(
                    self._run_script_pipeline(
                        active_project.project_id, user_feedback=text
                    )
                )
                return

            if active_project.state == WorkflowState.AWAITING_NARRATION_APPROVAL:
                # User provided feedback on the narration voice style
                await update.message.reply_text(
                    f"📝 *Narration feedback received:*\n_{text}_\n\n"
                    f"🎙️ Revising voice talent, style, and audio tags...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(
                    self._run_narration_pipeline(
                        active_project.project_id, user_feedback=text
                    )
                )
                return

            if active_project.state == WorkflowState.AWAITING_STYLE_APPROVAL:
                # User provided feedback on the animation visual style
                await update.message.reply_text(
                    f"📝 *Style feedback received:*\n_{text}_\n\n"
                    f"🎨 Refining animation style and re-generating Scene 1 sample...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(
                    self._run_style_pipeline(
                        active_project.project_id, user_feedback=text
                    )
                )
                return

            if active_project.state == WorkflowState.AWAITING_PUBLISH_APPROVAL:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🚀 Publish to YouTube",
                            callback_data=f"publish_youtube:{active_project.project_id}",
                        ),
                        InlineKeyboardButton(
                            "⏭️ Skip (Complete)",
                            callback_data=f"skip_publish:{active_project.project_id}",
                        ),
                    ]
                ]
                await update.message.reply_text(
                    "🎬 *Your video is ready!* Please click *Publish to YouTube* or *Skip* to finish the project.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            if active_project.state in (
                WorkflowState.RESEARCHING,
                WorkflowState.SCRIPTING,
                WorkflowState.NARRATING,
                WorkflowState.STYLING,
                WorkflowState.ANIMATING,
                WorkflowState.PUBLISHING,
            ):
                await update.message.reply_text(
                    "⏳ A task is currently running for your project. Please wait for it to finish or use `/cancel` to abort.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

        # Start a brand new project session
        session = await self.db.create_project(
            user_id=user_id, chat_id=chat_id, topic=text
        )
        await update.message.reply_text(
            f"🚀 *Started research on:* '{text}'\n\n"
            f"🔍 Conducting grounded web research with iterative evaluation...",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Dispatch research pipeline in background task
        asyncio.create_task(self._run_research_pipeline(session.project_id))

    # ==========================================================================
    # Callback Query Handlers (Inline Buttons)
    # ==========================================================================

    async def _handle_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline button clicks for approving research, scripts, and visual styles."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        data = query.data
        if data.startswith("approve_research:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if not project or project.state != WorkflowState.AWAITING_RESEARCH_APPROVAL:
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This research review is no longer active."
                    )
                return

            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "✅ *Research summary approved!*\n\n✍️ Generating scene-by-scene narration script...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            asyncio.create_task(self._run_script_pipeline(project_id))

        elif data.startswith("approve_script:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if not project or project.state != WorkflowState.AWAITING_SCRIPT_APPROVAL:
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This script review is no longer active."
                    )
                return

            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "✅ *Script approved!*\n\n🎙️ Formulating voice talent direction and synthesizing Scene 1 voice sample...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            asyncio.create_task(self._run_narration_pipeline(project_id))

        elif data.startswith("approve_narration:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if (
                not project
                or project.state != WorkflowState.AWAITING_NARRATION_APPROVAL
            ):
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This narration review is no longer active."
                    )
                return

            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "✅ *Voice & narration approved!*\n\n🎨 Designing animation style and generating Scene 1 sample frame...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            asyncio.create_task(self._run_style_pipeline(project_id))

        elif data.startswith("approve_style:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if not project or project.state != WorkflowState.AWAITING_STYLE_APPROVAL:
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This style review is no longer active."
                    )
                return

            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "✅ *Animation style approved!*\n\n🎬 Generating full scene animations and assembling video...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            asyncio.create_task(self._run_full_animation_pipeline(project_id))

        elif data.startswith("publish_youtube:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if not project or project.state != WorkflowState.AWAITING_PUBLISH_APPROVAL:
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This publish review is no longer active."
                    )
                return

            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "🚀 *Initiating YouTube upload...*\n\nUploading video to YouTube...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            asyncio.create_task(self._run_youtube_publish_pipeline(project_id))

        elif data.startswith("skip_publish:"):
            project_id = data.split(":", 1)[1]
            project = await self.db.get_project(project_id)
            if not project or project.state != WorkflowState.AWAITING_PUBLISH_APPROVAL:
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "ℹ️ This publish review is no longer active."
                    )
                return

            await self.state_machine.transition(project_id, WorkflowState.COMPLETED)
            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "✅ *Video generation completed!*\n\nYour video is safely stored on the server.",
                    parse_mode=ParseMode.MARKDOWN,
                )

    # ==========================================================================
    # Pipeline Orchestration
    # ==========================================================================

    async def _run_research_pipeline(
        self, project_id: str, user_feedback: str | None = None
    ) -> None:
        """Execute iterative Researcher & Evaluator multi-turn loop."""
        try:
            session = await self.db.get_project(project_id)
            if not session:
                return

            await self.state_machine.transition(project_id, WorkflowState.RESEARCHING)

            target_duration = extract_target_duration(
                session.topic, self.settings.default_video_duration_minutes
            )
            max_iterations = max(1, self.settings.max_research_iterations)

            accumulated_notes = ""
            feedback: str | None = user_feedback
            final_report: ResearchReport | None = None

            for iteration in range(1, max_iterations + 1):
                logger.info(
                    "Executing research pipeline iteration %d/%d for project %s (Duration: %s)",
                    iteration,
                    max_iterations,
                    project_id,
                    target_duration,
                )

                # Step 1: Researcher agent gathers search-grounded text findings
                with track_component(project_id, PipelineComponent.RESEARCH):
                    round_notes = await self.researcher.conduct_research(
                        topic=session.topic,
                        feedback=feedback,
                        previous_research=accumulated_notes
                        if accumulated_notes
                        else (
                            session.research_report.summary
                            if session.research_report
                            else None
                        ),
                        target_duration=target_duration,
                    )

                if accumulated_notes:
                    accumulated_notes = (
                        f"{accumulated_notes}\n\n"
                        f"=== RESEARCH ROUND {iteration} ===\n"
                        f"{round_notes}"
                    )
                else:
                    accumulated_notes = round_notes

                # Step 2: Evaluator agent filters noise, structures report, and checks sufficiency
                with track_component(project_id, PipelineComponent.EVALUATION):
                    eval_result = await self.evaluator.evaluate_research(
                        topic=session.topic,
                        accumulated_research=accumulated_notes,
                        target_duration=target_duration,
                        iteration=iteration,
                        max_iterations=max_iterations,
                    )

                final_report = eval_result.report

                if eval_result.is_sufficient or iteration >= max_iterations:
                    logger.info(
                        "Research finalized at iteration %d (Sufficient: %s)",
                        iteration,
                        eval_result.is_sufficient,
                    )
                    break

                # Prepare feedback for next researcher round
                feedback = eval_result.feedback_for_researcher
                logger.info(
                    "Research iteration %d insufficient. Refining with feedback: %s",
                    iteration,
                    feedback,
                )

                if self.app:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"🔄 *Round {iteration} complete.* Expanding depth on missing subtopics...",
                        parse_mode=ParseMode.MARKDOWN,
                    )

            if not final_report:
                raise RuntimeError(
                    "Research pipeline completed without producing a valid report."
                )

            await self.db.save_research_report(project_id, final_report)
            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
            )

            # Send research results and approval buttons to user
            await self._send_research_results(session.chat_id, final_report, project_id)

        except Exception as err:
            logger.exception(
                "Error during research pipeline for project %s", project_id
            )
            await self.state_machine.transition(
                project_id, WorkflowState.FAILED, error_message=str(err)
            )
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ *An error occurred during research:*\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )

    async def _send_message_chunks(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Send message to chat, chunking cleanly if exceeding Telegram's character limit.

        Splits at paragraph or newline boundaries to preserve formatting entities,
        and falls back to plain text if Markdown entity parsing fails.
        """
        if not self.app:
            return

        chunks = split_message_chunks(text, max_chars=4000)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            markup = reply_markup if is_last else None
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_markup=markup,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except BadRequest as bad_req:
                err_msg = str(bad_req).lower()
                if "can't parse entities" in err_msg or "entity" in err_msg:
                    logger.warning(
                        "Telegram Markdown entity parsing failed for message chunk (%s). Falling back to plain text.",
                        bad_req,
                    )
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        reply_markup=markup,
                        parse_mode=None,
                    )
                else:
                    raise

    async def _send_research_results(
        self, chat_id: int, report: ResearchReport, project_id: str
    ) -> None:
        """Send formatted research summary and approval prompt to chat."""
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve Research",
                    callback_data=f"approve_research:{project_id}",
                )
            ]
        ]
        text = (
            f"📋 *Research Summary: {report.topic}*\n\n"
            f"💡 *Key Insights & Summary:*\n{report.summary}\n\n"
            "💬 *Next Steps:*\n"
            "• Click *Approve Research* below to generate the narration script.\n"
            "• Or *reply with your feedback* to refine and expand the research."
        )
        await self._send_message_chunks(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _run_script_pipeline(
        self, project_id: str, user_feedback: str | None = None
    ) -> None:
        """Execute ScriptWriter agent to generate or revise scene-by-scene narration script."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.research_report:
                logger.error(
                    "Cannot run script pipeline: project or research report missing for %s",
                    project_id,
                )
                return

            await self.state_machine.transition(project_id, WorkflowState.SCRIPTING)

            target_duration = extract_target_duration(
                session.topic, self.settings.default_video_duration_minutes
            )

            with track_component(project_id, PipelineComponent.SCRIPT_WRITING):
                script = await self.script_writer.generate_script(
                    topic=session.topic,
                    research_report=session.research_report,
                    target_duration=target_duration,
                    feedback=user_feedback,
                    previous_script=session.script,
                )

            await self.db.save_script(project_id, script)
            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
            )

            # Send script results and approval buttons to user
            await self._send_script_results(session.chat_id, script, project_id)

        except Exception as err:
            logger.exception(
                "Error during script generation for project %s", project_id
            )
            await self.state_machine.transition(
                project_id, WorkflowState.FAILED, error_message=str(err)
            )
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ *An error occurred during script generation:*\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )

    async def _send_script_results(
        self, chat_id: int, script: Script, project_id: str
    ) -> None:
        """Send formatted script overview, scene summaries, and approval prompt to chat."""
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve Script",
                    callback_data=f"approve_script:{project_id}",
                )
            ]
        ]

        parts = [
            (
                f"🎬 *Video Script Summary: {script.topic}*\n\n"
                f"📝 *Overview:*\n{script.summary}"
            )
        ]

        if script.scenes:
            scene_summaries = [
                f"🎬 *Scene {scene.scene_number}: {scene.title}*\n"
                f"📌 *Summary:* {scene.summary}"
                for scene in script.scenes
            ]
            parts.append("📋 *Scene Breakdown:*\n\n" + "\n\n".join(scene_summaries))

        parts.append(
            "💬 *Next Steps:*\n"
            "• Click *Approve Script* below to finalize the narration script.\n"
            "• Or *reply with your feedback* to revise scenes or narration."
        )

        full_text = "\n\n".join(parts)
        await self._send_message_chunks(
            chat_id=chat_id,
            text=full_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _run_narration_pipeline(
        self, project_id: str, user_feedback: str | None = None
    ) -> None:
        """Execute NarrationPlanner and NarrationGenerator agents to formulate voice direction and synthesize Scene 1 audio sample."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.script:
                logger.error(
                    "Cannot run narration pipeline: project or script missing for %s",
                    project_id,
                )
                return

            await self.state_machine.transition(project_id, WorkflowState.NARRATING)

            project_folder = session.project_folder or project_id
            audio_dir = self.settings.audio_dir / project_folder
            audio_dir.mkdir(parents=True, exist_ok=True)

            with track_component(project_id, PipelineComponent.NARRATION_PLANNING):
                plan, sample_audio = await self.narrator.determine_plan_and_sample(
                    topic=session.topic,
                    script=session.script,
                    feedback=user_feedback,
                    previous_plan=session.narration_plan,
                    output_dir=audio_dir,
                )

            await self.db.save_narration_plan(
                project_id=project_id,
                plan=plan,
                sample_audio_path=sample_audio.audio_path,
            )
            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_NARRATION_APPROVAL
            )

            # Send voice sample and review buttons to user
            await self._send_narration_results(
                chat_id=session.chat_id,
                plan=plan,
                sample_audio=sample_audio,
                project_id=project_id,
            )

        except Exception as err:
            logger.exception(
                "Error during voice narration generation for project %s", project_id
            )
            await self.state_machine.transition(
                project_id, WorkflowState.FAILED, error_message=str(err)
            )
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ *An error occurred during voice narration synthesis:*\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )

    async def _send_narration_results(
        self,
        chat_id: int,
        plan: NarrationPlan,
        sample_audio: SceneAudio,
        project_id: str,
    ) -> None:
        """Send Scene 1 voice sample and narration direction review prompt to chat."""
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve Voice & Narration",
                    callback_data=f"approve_narration:{project_id}",
                )
            ]
        ]

        text_lines = [
            f"🎙️ *Voice Narration Plan: {plan.audio_profile_name}*",
            f"🎭 *Archetype:* {plan.audio_profile_role}",
            f"🗣️ *Voice:* `{plan.voice_name}`",
            f"⏱️ *Scene 1 Sample Duration:* {sample_audio.duration_seconds:.1f}s",
            "",
            f"🎬 *Scene Setting & Vibe:*\n_{plan.scene_environment}_",
            "",
            f"📋 *Director's Notes:*\n{plan.directors_notes}",
        ]

        if plan.scenes and plan.scenes[0].enhanced_narration:
            text_lines.extend(
                [
                    "",
                    "🎧 *Scene 1 Enhanced Transcript:*",
                    f"_{plan.scenes[0].enhanced_narration}_",
                ]
            )

        text_lines.extend(
            [
                "",
                "💬 *Next Steps:*",
                "• Listen to the voice note above and click *Approve Voice & Narration* to proceed.",
                "• Or *reply with your feedback* to change the voice, pacing, accent, or delivery.",
            ]
        )

        full_text = "\n".join(text_lines)

        audio_path = Path(sample_audio.audio_path)
        if self.app and audio_path.exists():
            audio_bytes = audio_path.read_bytes()
            media_timeout = float(self.settings.telegram_upload_timeout_seconds)
            try:
                await self.app.bot.send_voice(
                    chat_id=chat_id,
                    voice=audio_bytes,
                    caption=f"🎙️ *Scene 1 Voice Preview* ({sample_audio.duration_seconds:.1f}s)",
                    parse_mode=ParseMode.MARKDOWN,
                    read_timeout=media_timeout,
                    write_timeout=media_timeout,
                )
            except (TelegramError, OSError):
                try:
                    await self.app.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio_bytes,
                        title="Scene 1 Voice Preview",
                        performer=plan.audio_profile_name,
                        caption=f"🎙️ *Scene 1 Voice Preview* ({sample_audio.duration_seconds:.1f}s)",
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=media_timeout,
                        write_timeout=media_timeout,
                    )
                except (TelegramError, OSError) as send_err:
                    logger.warning("Could not send audio preview message: %s", send_err)

        await self._send_message_chunks(
            chat_id=chat_id,
            text=full_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _run_style_pipeline(
        self, project_id: str, user_feedback: str | None = None
    ) -> None:
        """Execute AnimationPlanner and SceneAnimator agents to formulate visual style, generate Scene 1 HTML sample, and render frame snapshot."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.script:
                logger.error(
                    "Cannot run style pipeline: project or script missing for %s",
                    project_id,
                )
                return

            await self.state_machine.transition(project_id, WorkflowState.STYLING)

            total_duration = self._get_project_video_duration(session)
            is_vertical = self.settings.is_vertical_video(total_duration)
            video_width, video_height = self.settings.get_video_dimensions(
                total_duration
            )

            with track_component(project_id, PipelineComponent.STYLE_PLANNING):
                style = await self.planner.plan_style(
                    topic=session.topic,
                    script=session.script,
                    feedback=user_feedback,
                    previous_style=session.style,
                    is_vertical=is_vertical,
                )

            scene_1 = session.script.scenes[0] if session.script.scenes else None
            if not scene_1:
                raise RuntimeError("Cannot animate: script contains no scenes.")

            s1_duration = scene_1.duration_seconds
            if session.sample_audio_path and Path(session.sample_audio_path).exists():
                audio_dur = get_wav_duration(session.sample_audio_path)
                if audio_dur > 0:
                    s1_duration = audio_dur

            with track_component(project_id, PipelineComponent.SCENE_ANIMATION):
                scene_1_anim = await self.animator.animate_scene(
                    topic=session.topic,
                    scene=scene_1,
                    style=style,
                    duration_seconds=s1_duration,
                    width=video_width,
                    height=video_height,
                    is_vertical=is_vertical,
                    total_video_duration=total_duration,
                )

            # Persist Scene 1 HTML code
            project_folder = session.project_folder or project_id
            anim_dir = self.settings.animations_dir / project_folder
            anim_dir.mkdir(parents=True, exist_ok=True)
            scene_1_html_path = anim_dir / "scene_1.html"
            scene_1_html_path.write_text(scene_1_anim.html_content, encoding="utf-8")

            # Render Scene 1 sample frame image snapshot (PNG)
            render_dir = self.settings.renders_dir / project_folder
            render_dir.mkdir(parents=True, exist_ok=True)
            sample_frame_path = render_dir / "scene_1_sample.png"

            await self.renderer.render_sample_frame(
                html_content=scene_1_anim.html_content,
                output_image_path=sample_frame_path,
                width=video_width,
                height=video_height,
            )

            await self.db.save_style(
                project_id=project_id,
                style=style,
                sample_frame_path=str(sample_frame_path),
            )
            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_STYLE_APPROVAL
            )

            # Send visual style sample image and review buttons to user
            await self._send_style_results(
                chat_id=session.chat_id,
                style=style,
                sample_frame_path=sample_frame_path,
                project_id=project_id,
                is_vertical=is_vertical,
                width=video_width,
                height=video_height,
            )

        except Exception as err:
            logger.exception(
                "Error during animation style generation for project %s", project_id
            )
            await self.state_machine.transition(
                project_id, WorkflowState.FAILED, error_message=str(err)
            )
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ *An error occurred during visual style generation:*\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )

    async def _send_style_results(
        self,
        chat_id: int,
        style: AnimationStyle,
        sample_frame_path: Path,
        project_id: str,
        is_vertical: bool = False,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        """Send formatted style overview and rendered Scene 1 sample image to chat."""
        if not self.app:
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve Style",
                    callback_data=f"approve_style:{project_id}",
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        format_str = (
            f"📱 *Format:* Vertical 9:16 ({width}x{height} • YouTube Shorts style)\n"
            if is_vertical
            else f"🖥️ *Format:* Horizontal 16:9 ({width}x{height} • Widescreen)\n"
        )

        caption = (
            f"🎨 *Visual Style Design: {style.style_name}*\n\n"
            f"{format_str}\n"
            f"📋 *Art Direction:*\n{style.visual_description}\n\n"
            "💬 *Next Steps:*\n"
            "• Click *Approve Style* below to generate full scene animations & assemble the video.\n"
            "• Or *reply with your feedback* to adjust colors, aesthetic, or visual metaphors."
        )

        if sample_frame_path.exists() and sample_frame_path.stat().st_size > 0:
            try:
                photo_bytes = sample_frame_path.read_bytes()
                media_timeout = float(self.settings.telegram_upload_timeout_seconds)
                # Telegram photo captions have a 1024 character limit
                if len(caption) <= 1024:
                    await self.app.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_bytes,
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=media_timeout,
                        write_timeout=media_timeout,
                    )
                    return
                else:
                    # Send photo first, followed by text breakdown and buttons
                    await self.app.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_bytes,
                        caption=f"🎨 *Scene 1 Sample Frame: {style.style_name}*",
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=media_timeout,
                        write_timeout=media_timeout,
                    )
            except Exception as photo_err:  # noqa: BLE001
                logger.warning(
                    "Failed to send sample photo: %s. Falling back to text.", photo_err
                )

        await self._send_message_chunks(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
        )

    async def _run_full_animation_pipeline(self, project_id: str) -> None:
        """Generate animations for all scenes, render video clips, and assemble the master MP4 video."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.script or not session.style:
                logger.error(
                    "Cannot run full animation pipeline: project, script, or style missing for %s",
                    project_id,
                )
                return

            await self.state_machine.transition(project_id, WorkflowState.ANIMATING)

            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="🎬 *Generating animations for all scenes and rendering video clips...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            project_folder = session.project_folder or project_id
            anim_dir = self.settings.animations_dir / project_folder
            anim_dir.mkdir(parents=True, exist_ok=True)
            render_dir = self.settings.renders_dir / project_folder
            render_dir.mkdir(parents=True, exist_ok=True)

            # Check if Scene 1 was already generated during the styling approval stage
            sample_scene_1: SceneAnimation | None = None
            scene_1_html_path = anim_dir / "scene_1.html"
            if scene_1_html_path.exists() and session.script.scenes:
                scene_1 = session.script.scenes[0]
                s1_duration = (
                    scene_1.duration_seconds
                    or self.settings.default_scene_duration_seconds
                )
                if (
                    session.sample_audio_path
                    and Path(session.sample_audio_path).exists()
                ):
                    audio_dur = get_wav_duration(session.sample_audio_path)
                    if audio_dur > 0:
                        s1_duration = audio_dur

                sample_scene_1 = SceneAnimation(
                    scene_number=1,
                    title=scene_1.title,
                    html_content=scene_1_html_path.read_text(encoding="utf-8"),
                    duration_seconds=s1_duration,
                )

            script: Script = session.script
            style: AnimationStyle = session.style
            topic: str = session.topic
            narration_plan: NarrationPlan | None = session.narration_plan
            sample_audio_path: str | None = session.sample_audio_path

            # Determine dynamic video format and dimensions based on duration
            project_duration = self._get_project_video_duration(session)
            is_vertical = self.settings.is_vertical_video(project_duration)
            video_width, video_height = self.settings.get_video_dimensions(
                project_duration
            )

            # Concurrently synthesize all scene voiceovers and generate scene canvas codes
            async def _synthesize_voiceover() -> NarrationStoryboard | None:
                if not narration_plan:
                    return None
                audio_dir = self.settings.audio_dir / project_folder
                audio_dir.mkdir(parents=True, exist_ok=True)
                sample_s1_audio: SceneAudio | None = None
                if sample_audio_path and Path(sample_audio_path).exists():
                    sample_s1_audio = SceneAudio(
                        scene_number=1,
                        audio_path=sample_audio_path,
                        duration_seconds=get_wav_duration(sample_audio_path),
                        mime_type="audio/wav",
                        file_size_bytes=Path(sample_audio_path).stat().st_size,
                    )
                with track_component(project_id, PipelineComponent.VOICE_SYNTHESIS):
                    return await self.narrator.generate_full_narration(
                        topic=topic,
                        plan=narration_plan,
                        output_dir=audio_dir,
                        sample_scene_1=sample_s1_audio,
                        concurrency=self.settings.tts_concurrency,
                    )

            async def _generate_animations() -> AnimationStoryboard:
                with track_component(project_id, PipelineComponent.SCENE_ANIMATION):
                    return await self.animator.animate_storyboard(
                        topic=topic,
                        script=script,
                        style=style,
                        sample_scene_1=sample_scene_1,
                        concurrency=self.settings.animation_concurrency,
                        width=video_width,
                        height=video_height,
                        is_vertical=is_vertical,
                        total_video_duration=project_duration,
                    )

            # Execute voiceover synthesis and canvas code generation in parallel
            narration_storyboard, storyboard = await asyncio.gather(
                _synthesize_voiceover(),
                _generate_animations(),
            )

            if narration_storyboard:
                await self.db.save_narration_storyboard(
                    project_id=project_id,
                    storyboard=narration_storyboard,
                    final_audio_path=narration_storyboard.full_audio_path,
                )

            # Save HTML animation codes
            for scene_anim in storyboard.scenes:
                html_path = anim_dir / f"scene_{scene_anim.scene_number}.html"
                html_path.write_text(scene_anim.html_content, encoding="utf-8")

            # Check whether all scenes have valid synthesized audio for single-pass rendering + muxing
            scene_audio_paths = (
                [
                    s.audio_path
                    for s in narration_storyboard.scenes_audio
                    if s.audio_path
                ]
                if narration_storyboard
                else None
            )
            can_single_pass_mux = bool(
                narration_storyboard
                and scene_audio_paths
                and len(scene_audio_paths) == len(storyboard.scenes)
                and all(Path(p).exists() for p in scene_audio_paths)
            )

            # Render scene video clips concurrently in parallel (with single-pass audio muxing when available)
            scene_video_paths = await self.renderer.render_scenes_parallel(
                scenes=storyboard.scenes,
                output_dir=render_dir,
                concurrency=self.settings.render_concurrency,
                width=video_width,
                height=video_height,
                narration_storyboard=narration_storyboard
                if can_single_pass_mux
                else None,
            )

            # Assemble final master MP4 video with narration audio muxed in
            final_video_path = render_dir / f"final_video_{project_folder}.mp4"
            final_audio_p = (
                Path(narration_storyboard.full_audio_path)
                if narration_storyboard and narration_storyboard.full_audio_path
                else None
            )
            await self.renderer.assemble_video(
                scene_video_paths=scene_video_paths,
                output_video_path=final_video_path,
                audio_path=final_audio_p,
                scene_audio_paths=scene_audio_paths,
                narration_storyboard=narration_storyboard,
                scenes_pre_muxed=can_single_pass_mux,
            )

            # Generate synchronized SRT subtitle file for the video
            captions_path = render_dir / f"captions_{project_folder}.srt"
            try:
                save_srt_subtitles(
                    output_path=captions_path,
                    script=script,
                    narration_storyboard=narration_storyboard,
                    animation_storyboard=storyboard,
                )
                storyboard.captions_path = str(captions_path)
            except (OSError, ValueError, RuntimeError) as srt_err:
                logger.warning(
                    "Failed to generate synchronized SRT captions for project %s: %s",
                    project_id,
                    srt_err,
                )

            storyboard.final_video_path = str(final_video_path)
            storyboard.sample_frame_path = session.sample_frame_path

            await self.db.save_storyboard(
                project_id=project_id,
                storyboard=storyboard,
                final_video_path=str(final_video_path),
                captions_path=storyboard.captions_path,
            )

            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
            )

            # Send final video or preview sample to user via Telegram
            if self.app and final_video_path.exists():
                try:
                    cost_summary = await get_cost_tracker().get_project_summary(
                        project_id
                    )
                    cost_badge = get_cost_tracker().format_short_badge(cost_summary)
                    cost_report = get_cost_tracker().format_telegram_report(
                        cost_summary
                    )

                    max_allowed_bytes = int(
                        self.settings.telegram_max_video_size_mb * 1024 * 1024
                    )
                    max_preview_duration = (
                        self.settings.telegram_preview_max_duration_seconds
                    )

                    file_size = final_video_path.stat().st_size

                    # Probe video duration
                    total_duration = 0.0
                    try:
                        total_duration = await self.renderer.get_media_duration(
                            final_video_path
                        )
                    except (RuntimeError, OSError, ValueError) as dur_err:
                        logger.warning(
                            "Could not probe video duration from %s: %s",
                            final_video_path,
                            dur_err,
                        )
                        if storyboard.scenes:
                            total_duration = sum(
                                s.duration_seconds for s in storyboard.scenes
                            )

                    is_large_video = (
                        total_duration > max_preview_duration
                        or file_size > max_allowed_bytes
                    )

                    video_to_send = final_video_path
                    is_preview = False

                    if is_large_video:
                        logger.info(
                            "Video for project %s is large (duration=%.1fs, size=%.2fMB). Generating preview...",
                            project_id,
                            total_duration,
                            file_size / (1024 * 1024),
                        )
                        preview_path = (
                            render_dir / f"preview_video_{project_folder}.mp4"
                        )
                        try:
                            video_to_send = await self.renderer.create_video_preview(
                                video_path=final_video_path,
                                output_path=preview_path,
                                max_duration_seconds=max_preview_duration,
                                max_file_size_bytes=max_allowed_bytes,
                            )
                            is_preview = True
                        except (RuntimeError, OSError, ValueError) as preview_err:
                            logger.error(
                                "Failed to generate video preview for project %s: %s; falling back to full video",
                                project_id,
                                preview_err,
                            )
                            video_to_send = final_video_path
                            is_preview = False

                    total_duration_str = (
                        format_duration(total_duration)
                        if total_duration > 0
                        else "Unknown"
                    )

                    caption_lines = [
                        "🎉 *Your Educational Video is Ready!* ✨",
                        "",
                        f"🎬 *Topic:* {session.topic}",
                        f"🎨 *Style:* {session.style.style_name}",
                    ]
                    if session.narration_plan:
                        caption_lines.append(
                            f"🎙️ *Voice Talent:* {session.narration_plan.audio_profile_name} (`{session.narration_plan.voice_name}`)"
                        )

                    if is_preview:
                        preview_duration_str = format_duration(
                            min(total_duration, max_preview_duration)
                        )
                        caption_lines.append(
                            f"⏱️ *Duration:* {preview_duration_str} (Preview) • Total: {total_duration_str}"
                        )
                    elif total_duration > 0:
                        caption_lines.append(f"⏱️ *Duration:* {total_duration_str}")

                    caption_lines.append(
                        f"📊 *Scenes:* {len(storyboard.scenes)} scenes assembled."
                    )
                    format_badge = (
                        f"📱 *Format:* Vertical 9:16 ({video_width}x{video_height} • Shorts)"
                        if is_vertical
                        else f"🖥️ *Format:* Horizontal 16:9 ({video_width}x{video_height})"
                    )
                    caption_lines.append(format_badge)
                    if storyboard.captions_path:
                        caption_lines.append("💬 *Captions:* Synchronized `.srt` ready")
                    caption_lines.append(cost_badge)

                    if is_preview:
                        caption_lines.append("")
                        caption_lines.append(
                            f"ℹ️ *Preview Notice:* Due to Telegram's 50MB upload limit, this is a {format_duration(max_preview_duration)} preview sample. The full complete video ({total_duration_str}) has been generated and saved on the server."
                        )

                    caption = "\n".join(caption_lines)

                    video_bytes = video_to_send.read_bytes()
                    upload_timeout = float(
                        self.settings.telegram_upload_timeout_seconds
                    )
                    max_send_attempts = 2
                    last_send_err: Exception | None = None

                    for attempt in range(1, max_send_attempts + 1):
                        try:
                            await self.app.bot.send_video(
                                chat_id=session.chat_id,
                                video=video_bytes,
                                caption=caption,
                                width=video_width,
                                height=video_height,
                                parse_mode=ParseMode.MARKDOWN,
                                supports_streaming=True,
                                read_timeout=upload_timeout,
                                write_timeout=upload_timeout,
                            )
                            last_send_err = None
                            break
                        except (TimedOut, NetworkError) as net_err:
                            last_send_err = net_err
                            logger.warning(
                                "Attempt %d/%d to send video to Telegram failed for project %s: %s",
                                attempt,
                                max_send_attempts,
                                project_id,
                                net_err,
                            )
                            if attempt < max_send_attempts:
                                await asyncio.sleep(2.0)
                        except Exception as non_net_err:  # noqa: BLE001
                            last_send_err = non_net_err
                            break

                    if last_send_err is not None:
                        raise last_send_err

                    # Send detailed generation cost & token breakdown message
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=cost_report,
                        parse_mode=ParseMode.MARKDOWN,
                    )

                    # Prompt user for YouTube publishing approval
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "🚀 Publish to YouTube",
                                callback_data=f"publish_youtube:{project_id}",
                            ),
                            InlineKeyboardButton(
                                "⏭️ Skip (Complete)",
                                callback_data=f"skip_publish:{project_id}",
                            ),
                        ]
                    ]
                    format_desc = (
                        "YouTube Short (Vertical 9:16)"
                        if is_vertical
                        else "YouTube Video (16:9)"
                    )
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=(
                            "🎬 *Ready for Publishing!*\n\n"
                            f"Would you like to publish this video as a *{format_desc}* to YouTube?"
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as send_err:
                    logger.exception(
                        "Failed to send video to Telegram for project %s",
                        project_id,
                    )
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=(
                            f"⚠️ *Video generation completed, but delivery via Telegram failed:*\n`{send_err}`\n\n"
                            f"Your full video file is safely saved on the server."
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )

        except Exception as err:
            logger.exception(
                "Error during full animation pipeline for project %s", project_id
            )
            session = await self.db.get_project(project_id)
            if session and session.state not in (
                WorkflowState.COMPLETED,
                WorkflowState.AWAITING_PUBLISH_APPROVAL,
                WorkflowState.PUBLISHING,
            ):
                await self.state_machine.transition(
                    project_id, WorkflowState.FAILED, error_message=str(err)
                )
            if self.app and session:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text=f"⚠️ *An error occurred during video rendering and assembly:*\n`{err}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

    async def _run_youtube_publish_pipeline(self, project_id: str) -> None:
        """Upload and publish the final master video to YouTube upon user approval."""
        try:
            session = await self.db.get_project(project_id)
            if not session:
                logger.error("Project %s not found for YouTube publishing", project_id)
                return

            if (
                not session.final_video_path
                or not Path(session.final_video_path).exists()
            ):
                logger.error(
                    "Final video file not found for project %s at %s",
                    project_id,
                    session.final_video_path,
                )
                if self.app:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text="⚠️ *Cannot publish to YouTube:* Master video file was not found on the server.",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                return

            # Check if YouTube credentials are configured
            if not self.youtube_publisher.is_configured():
                logger.warning(
                    "YouTube publishing requested but not configured for project %s",
                    project_id,
                )
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🔄 Retry Publish",
                            callback_data=f"publish_youtube:{project_id}",
                        ),
                        InlineKeyboardButton(
                            "⏭️ Skip (Complete)",
                            callback_data=f"skip_publish:{project_id}",
                        ),
                    ]
                ]
                if self.app:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=(
                            "⚠️ *YouTube publishing is not configured.*\n\n"
                            "To enable publishing, set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, "
                            "and `YOUTUBE_REFRESH_TOKEN` (or generate `storage/youtube_token.json`).\n\n"
                            "Once configured, click *Retry Publish*, or click *Skip* to complete without publishing."
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                return

            await self.state_machine.transition(project_id, WorkflowState.PUBLISHING)

            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="⏳ *Uploading master video to YouTube...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            project_duration = self._get_project_video_duration(session)
            is_vertical = self.settings.is_vertical_video(project_duration)

            result = await self.youtube_publisher.publish_video(
                video_path=session.final_video_path,
                topic=session.topic,
                script=session.script,
                storyboard=session.storyboard,
                is_vertical=is_vertical,
                captions_path=session.captions_path,
            )

            await self.db.save_youtube_url(project_id, result.video_url)
            await self.state_machine.transition(project_id, WorkflowState.COMPLETED)

            if self.app:
                format_label = (
                    "📱 *Format:* YouTube Short (Vertical 9:16)"
                    if result.is_short
                    else "🖥️ *Format:* YouTube Video (Horizontal 16:9)"
                )
                msg_text = (
                    "🎉 *Your video is now live on YouTube!* 🚀\n\n"
                    f"🎬 *Title:* {result.title}\n"
                    f"{format_label}\n"
                    f"👁️ *Privacy:* `{result.privacy_status}`\n\n"
                    f"🔗 [Watch on YouTube]({result.video_url})\n"
                    f"`{result.video_url}`"
                )
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text=msg_text,
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as err:
            logger.exception(
                "Error during YouTube publishing for project %s", project_id
            )
            session = await self.db.get_project(project_id)
            if session and session.state == WorkflowState.PUBLISHING:
                try:
                    await self.state_machine.transition(
                        project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
                    )
                except (
                    InvalidStateTransitionError,
                    ValueError,
                    RuntimeError,
                ) as rev_err:
                    logger.debug(
                        "Could not revert state to AWAITING_PUBLISH_APPROVAL: %s",
                        rev_err,
                    )

            if self.app and session:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🔄 Retry Publish",
                            callback_data=f"publish_youtube:{project_id}",
                        ),
                        InlineKeyboardButton(
                            "⏭️ Skip (Complete)",
                            callback_data=f"skip_publish:{project_id}",
                        ),
                    ]
                ]
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text=(
                        f"⚠️ *Failed to publish video to YouTube:*\n`{err}`\n\n"
                        f"Your video remains safely saved on the server. You can retry or skip."
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN,
                )
