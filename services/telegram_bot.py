"""Telegram Bot service orchestrating the multi-agent video creation pipeline."""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents.researcher import ResearcherAgent
from agents.scriptwriter import ScriptWriterAgent
from agents.summarizer import SummarizerAgent
from agents.verifier import VerifierAgent
from config.settings import Settings, get_settings
from core.database import DatabaseManager, get_db_manager
from core.models import AspectRatio, PitchSummary, ResearchReport, WorkflowState
from core.state_machine import PipelineStateMachine
from media.audio_tts import AudioEngine
from media.svg_animator import SvgAnimator
from media.video_assembler import VideoAssembler
from services.youtube_publisher import YouTubePublisher

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Async Telegram Bot orchestrating multi-agent research, approval loops, and video rendering."""

    def __init__(
        self,
        settings: Settings | None = None,
        db: DatabaseManager | None = None,
    ):
        self.settings = settings or get_settings()
        self.db = db or get_db_manager()
        self.state_machine = PipelineStateMachine(db=self.db)

        # Autonomous Agents
        self.researcher = ResearcherAgent(settings=self.settings)
        self.verifier = VerifierAgent(settings=self.settings)
        self.summarizer = SummarizerAgent(settings=self.settings)
        self.scriptwriter = ScriptWriterAgent(settings=self.settings)

        # Media & Publishing Engines
        self.audio_engine = AudioEngine(settings=self.settings)
        self.svg_animator = SvgAnimator(settings=self.settings)
        self.video_assembler = VideoAssembler(settings=self.settings)
        self.youtube_publisher = YouTubePublisher(settings=self.settings)

        # In-memory tracking of pending revision requests: chat_id -> project_id
        self._pending_revisions: dict[int, str] = {}
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

    async def build_application(self) -> Application:
        """Build and configure the python-telegram-bot Application."""
        if not self.settings.telegram_bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is not configured in environment or .env"
            )

        app = Application.builder().token(self.settings.telegram_bot_token).build()

        # Command Handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(CommandHandler("status", self._handle_status))
        app.add_handler(CommandHandler("cancel", self._handle_cancel))

        # Interactive Callback Buttons Handler
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Plain Text Message Handler (Topic submission or revision feedback)
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        self.app = app
        return app

    # ==========================================================================
    # Command Handlers
    # ==========================================================================

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
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
            "I am your AI video production studio. Send me any topic, question, or curiosity, "
            "and I will:\n"
            "1. 🔍 *Research & verify* facts with Gemini 3.7 Flash & Google Search\n"
            "2. 💡 *Pitch a video concept* with a magnetic hook for your review\n"
            "3. 🎬 *Render high-definition SVG animations & narration*\n"
            "4. 🚀 *Publish the final video to YouTube* and send it here!\n\n"
            "👉 *Send a topic to get started!* (e.g. `How do black holes evaporate?` or `The history of cryptography`)"
        )
        await update.effective_chat.send_message(
            welcome_text, parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        if not update.effective_chat:
            return
        help_text = (
            "📖 *Curiosity On Demand - Help & Commands*\n\n"
            "• Simply type any topic to start a new video creation.\n"
            "• `/status` - Check the status of your active video project.\n"
            "• `/cancel` - Cancel your ongoing project.\n"
            "• `/help` - Show this guide.\n\n"
            "When the pitch summary arrives, you can use the inline buttons to approve, request revisions, or generate a scene preview!"
        )
        await update.effective_chat.send_message(
            help_text, parse_mode=ParseMode.MARKDOWN
        )

    async def _handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        if not update.effective_chat:
            return
        active_project = await self.db.get_active_project_for_chat(
            update.effective_chat.id
        )
        if not active_project:
            await update.effective_chat.send_message(
                "ℹ️ No active video project found. Send a topic to start one!"
            )
            return

        msg = (
            f"🎬 *Active Project Status*\n\n"
            f"• *Topic:* {active_project.topic}\n"
            f"• *State:* `{active_project.state.value}`\n"
            f"• *Project ID:* `{active_project.project_id[:8]}...`\n"
            f"• *Updated:* {active_project.updated_at}"
        )
        await update.effective_chat.send_message(msg, parse_mode=ParseMode.MARKDOWN)

    async def _handle_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /cancel command."""
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
        self._pending_revisions.pop(update.effective_chat.id, None)
        await update.effective_chat.send_message("❌ Project cancelled.")

    # ==========================================================================
    # Message & Interaction Handlers
    # ==========================================================================

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle user text messages (new topic or revision feedback)."""
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

        # Check if user was responding to a pitch revision prompt
        if chat_id in self._pending_revisions:
            project_id = self._pending_revisions.pop(chat_id)
            asyncio.create_task(self._process_pitch_revision(chat_id, project_id, text))
            return

        # Start a brand new project session
        session = await self.db.create_project(
            user_id=user_id, chat_id=chat_id, topic=text
        )
        await update.message.reply_text(
            f"🚀 *Started new project on:* '{text}'\n\n"
            f"🔍 *Phase 1:* Conducting grounded research and fact-checking with Gemini 3.7 Flash...",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Dispatch research pipeline in background task
        asyncio.create_task(self._run_research_pipeline(session.project_id))

    async def _run_research_pipeline(self, project_id: str) -> None:
        """Execute the iterative Researcher <-> Verifier loop."""
        try:
            session = await self.db.get_project(project_id)
            if not session:
                return

            await self.state_machine.transition(project_id, WorkflowState.RESEARCHING)

            report: ResearchReport | None = None
            follow_ups = None

            for iteration in range(1, self.settings.max_research_iterations + 1):
                # 1. Research step
                report = await self.researcher.conduct_research(
                    topic=session.topic,
                    follow_up_queries=follow_ups,
                    previous_report=report,
                    iteration=iteration,
                )
                await self.db.save_research_report(project_id, report)

                # 2. Verification step
                await self.state_machine.transition(project_id, WorkflowState.VERIFYING)
                ver_result = await self.verifier.verify_research(
                    report=report, iteration=iteration
                )

                if ver_result.is_complete:
                    logger.info(
                        "Research verified complete for project %s on iteration %d",
                        project_id,
                        iteration,
                    )
                    break
                else:
                    logger.info(
                        "Verifier requested follow-ups: %s",
                        ver_result.follow_up_queries,
                    )
                    follow_ups = ver_result.follow_up_queries
                    await self.state_machine.transition(
                        project_id, WorkflowState.RESEARCHING
                    )

            if not report:
                raise RuntimeError("Failed to generate research report.")

            # 3. Summarization step
            pitch = await self.summarizer.create_pitch(report=report)
            await self.db.save_pitch_summary(project_id, pitch)
            await self.state_machine.transition(
                project_id, WorkflowState.AWAITING_APPROVAL
            )

            # Send pitch to user with Inline Buttons
            await self._send_pitch_review_message(session.chat_id, project_id, pitch)

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

    async def _send_pitch_review_message(
        self, chat_id: int, project_id: str, pitch: PitchSummary
    ) -> None:
        """Send formatted pitch concept with interactive Inline Buttons."""
        if not self.app:
            return

        titles_formatted = "\n".join(
            f"  {i + 1}. {t}" for i, t in enumerate(pitch.title_options)
        )
        takeaways_formatted = "\n".join(f"  • {t}" for t in pitch.key_takeaways)

        pitch_text = (
            f"💡 *Video Concept Pitch Ready for Review!*\n\n"
            f"📌 *Topic:* {pitch.topic}\n\n"
            f"🎯 *Proposed Titles:*\n{titles_formatted}\n\n"
            f"🪝 *Opening Hook (First 5-10s):*\n_{pitch.hook}_\n\n"
            f"👥 *Target Audience:* {pitch.target_audience}\n\n"
            f"🔑 *Key Takeaways:*\n{takeaways_formatted}\n\n"
            f"📖 *Storyline & Narrative Arc:*\n{pitch.core_narrative}\n\n"
            f"⏱️ *Estimated Duration:* ~{int(pitch.estimated_duration_seconds)}s ({pitch.estimated_scenes_count} scenes)\n\n"
            f"Please approve or request revisions below:"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Approve & Render",
                    callback_data=f"approve:{project_id}",
                ),
                InlineKeyboardButton(
                    "✏️ Request Changes",
                    callback_data=f"revise:{project_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "👁️ Generate Scene Preview",
                    callback_data=f"sample:{project_id}",
                ),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.app.bot.send_message(
            chat_id=chat_id,
            text=pitch_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _process_pitch_revision(
        self, chat_id: int, project_id: str, feedback: str
    ) -> None:
        """Regenerate pitch incorporating user feedback."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.research_report or not session.pitch_summary:
                return

            if self.app:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔄 *Revising pitch with your feedback:* '{feedback}'...",
                    parse_mode=ParseMode.MARKDOWN,
                )

            revised_pitch = await self.summarizer.create_pitch(
                report=session.research_report,
                user_feedback=feedback,
                previous_pitch=session.pitch_summary,
            )
            await self.db.save_pitch_summary(project_id, revised_pitch)
            await self._send_pitch_review_message(chat_id, project_id, revised_pitch)

        except Exception as err:
            logger.exception("Error revising pitch for project %s", project_id)
            if self.app:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Failed to revise pitch: `{err}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

    # ==========================================================================
    # Callback Handlers (Approve / Revise / Sample)
    # ==========================================================================

    async def _handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline button clicks."""
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        action, _, project_id = query.data.partition(":")
        session = await self.db.get_project(project_id)
        if not session:
            await query.edit_message_text("⚠️ Project session expired or not found.")
            return

        chat_id = session.chat_id

        if action == "approve":
            await query.edit_message_text(
                "✅ *Pitch approved!* Starting full script generation & media rendering...",
                parse_mode=ParseMode.MARKDOWN,
            )
            asyncio.create_task(self._run_render_pipeline(project_id))

        elif action == "revise":
            self._pending_revisions[chat_id] = project_id
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ *Please reply with your feedback or instructions for what you would like changed in the pitch:*",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "sample":
            await context.bot.send_message(
                chat_id=chat_id,
                text="🎨 Generating a fast sample preview of Scene 1...",
            )
            asyncio.create_task(self._run_sample_generation(project_id))

    async def _run_sample_generation(self, project_id: str) -> None:
        """Generate and send quick scene 1 video preview to user."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.pitch_summary:
                return

            project_media_dir = self.settings.media_output_dir / project_id
            project_media_dir.mkdir(parents=True, exist_ok=True)

            # Generate script if not already generated
            script = session.script
            if not script:
                script = await self.scriptwriter.generate_script(
                    pitch=session.pitch_summary,
                    report=session.research_report,
                )
                await self.db.save_video_script(project_id, script)

            scene_1 = script.scenes[0]

            # Synthesize audio & render frames for scene 1
            audio_dir = project_media_dir / "audio"
            await self.audio_engine.synthesize_scene(scene_1, audio_dir)
            await self.svg_animator.render_scene_frames(
                scene=scene_1, output_dir=project_media_dir, fps=24
            )

            # Render preview clip
            sample_clip_path = project_media_dir / "sample_scene_1.mp4"
            await self.video_assembler.render_sample_preview(
                scene=scene_1, output_sample_path=sample_clip_path, fps=24
            )
            await self.db.save_media_outputs(
                project_id, sample_clip_path=str(sample_clip_path)
            )

            # Send video to Telegram
            if self.app and sample_clip_path.exists():
                await self.app.bot.send_video(
                    chat_id=session.chat_id,
                    video=sample_clip_path,
                    caption=f"👁️ *Scene 1 Preview Sample*\n_{scene_1.narration[:100]}..._",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as err:
            logger.exception("Error generating sample for %s", project_id)
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ Failed to generate sample preview: `{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )

    async def _run_render_pipeline(self, project_id: str) -> None:
        """Complete scriptwriting, audio synthesis, SVG frame rendering, assembly, and publishing."""
        try:
            session = await self.db.get_project(project_id)
            if not session or not session.pitch_summary:
                return

            project_media_dir = self.settings.media_output_dir / project_id
            project_media_dir.mkdir(parents=True, exist_ok=True)

            # 1. Script Generation
            await self.state_machine.transition(
                project_id, WorkflowState.GENERATING_SCRIPT
            )
            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="✍️ *Writing scene-by-scene script and SVG visual blueprints...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            script = await self.scriptwriter.generate_script(
                pitch=session.pitch_summary,
                report=session.research_report,
            )
            await self.db.save_video_script(project_id, script)

            # 2. Audio & Visual Asset Generation
            await self.state_machine.transition(
                project_id, WorkflowState.GENERATING_ASSETS
            )
            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="🎙️ *Synthesizing voice narration and rendering SVG keyframe sequences...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            # Synthesize all scene voiceovers
            script = await self.audio_engine.batch_synthesize_script(
                script=script, project_dir=project_media_dir
            )
            await self.db.save_video_script(project_id, script)

            # Render frames and clips for each scene
            scene_clips = []
            for scene in script.scenes:
                await self.svg_animator.render_scene_frames(
                    scene=scene,
                    output_dir=project_media_dir,
                    fps=self.settings.default_fps,
                )
                clip_path = project_media_dir / f"scene_{scene.scene_id}_clip.mp4"
                await self.video_assembler.render_scene_clip(
                    scene=scene,
                    output_clip_path=clip_path,
                    fps=self.settings.default_fps,
                )
                scene_clips.append(clip_path)

            # 3. Video Assembly
            await self.state_machine.transition(project_id, WorkflowState.ASSEMBLING)
            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="🎬 *Stitching audio and scenes into final 1080p MP4 master...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            final_video_path = project_media_dir / "final_video.mp4"
            await self.video_assembler.assemble_full_video(
                scene_clip_paths=scene_clips,
                output_video_path=final_video_path,
            )
            await self.db.save_media_outputs(
                project_id, final_video_path=str(final_video_path)
            )

            # Also render highlighted vertical short(s) if identified
            short_paths = []
            if script.highlighted_short_scene_ids:
                short_scene_id = script.highlighted_short_scene_ids[0]
                matching_scene = next(
                    (s for s in script.scenes if s.scene_id == short_scene_id),
                    script.scenes[0],
                )
                short_clip_path = project_media_dir / "short_9_16.mp4"
                await self.svg_animator.render_scene_frames(
                    scene=matching_scene,
                    output_dir=project_media_dir / "short_frames",
                    aspect_ratio=AspectRatio.VERTICAL_9_16,
                )
                await self.video_assembler.render_scene_clip(
                    scene=matching_scene, output_clip_path=short_clip_path
                )
                short_paths.append(str(short_clip_path))
                await self.db.save_media_outputs(project_id, short_paths=short_paths)

            # 4. YouTube Publishing
            await self.state_machine.transition(project_id, WorkflowState.UPLOADING)
            if self.app:
                await self.app.bot.send_message(
                    chat_id=session.chat_id,
                    text="🚀 *Publishing video to YouTube...*",
                    parse_mode=ParseMode.MARKDOWN,
                )

            youtube_url = await self.youtube_publisher.upload_video(
                video_path=final_video_path,
                title=script.title,
                description=script.description,
                tags=script.tags,
            )
            await self.db.save_media_outputs(project_id, youtube_url=youtube_url)

            # 5. Completed
            await self.state_machine.transition(project_id, WorkflowState.COMPLETED)

            # Send video and YouTube link to Telegram
            if self.app:
                caption = (
                    f"🎉 *Video Complete & Published!* 🎉\n\n"
                    f"📺 *Title:* {script.title}\n"
                    f"🔗 *YouTube Watch Link:* {youtube_url}\n"
                    f"⏱️ *Duration:* {int(script.total_duration_seconds)}s\n\n"
                    f"Thank you for using Curiosity On Demand!"
                )
                if final_video_path.exists() and final_video_path.stat().st_size > 0:
                    await self.app.bot.send_video(
                        chat_id=session.chat_id,
                        video=final_video_path,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=caption,
                        parse_mode=ParseMode.MARKDOWN,
                    )

        except Exception as err:
            logger.exception("Error during render pipeline for project %s", project_id)
            await self.state_machine.transition(
                project_id, WorkflowState.FAILED, error_message=str(err)
            )
            if self.app:
                session = await self.db.get_project(project_id)
                if session:
                    await self.app.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"⚠️ *Rendering failed:*\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
