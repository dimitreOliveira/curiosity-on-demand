"""Telegram Bot service orchestrating the research and narration script pipeline."""

import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents.evaluator import EvaluatorAgent
from agents.researcher import ResearcherAgent
from agents.script_writer import ScriptWriterAgent
from config.settings import Settings, get_settings
from core.database import DatabaseManager, get_db_manager
from core.models import ResearchReport, Script, WorkflowState
from core.state_machine import PipelineStateMachine

logger = logging.getLogger(__name__)


def extract_target_duration(text: str, default_minutes: int = 10) -> str:
    """Extract requested video duration from topic string, or default to configured duration."""
    match = re.search(r"\b(\d+)\s*(?:min|minute|minutes|m)\b", text, re.IGNORECASE)
    if match:
        return f"{match.group(1)} minutes"
    return f"~{default_minutes} minutes"


class TelegramBotService:
    """Async Telegram Bot orchestrating research, scripting, and interactive user reviews."""

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

        # Inline Button Callback Handler
        app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        # Plain Text Message Handler (Topic submission & review feedback)
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
            "Send me any topic or curiosity, and our AI agents will:\n"
            "1. 🔍 Conduct in-depth, grounded web research.\n"
            "2. 📋 Present a structured summary for your review and feedback.\n"
            "3. ✍️ Write a scene-by-scene narration script.\n"
            "4. 🎬 Let you review and refine the script.\n\n"
            "👉 *Send a topic to get started!* (e.g. `How do black holes evaporate? (5 min video)`)"
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
            "• Type any topic (with optional target duration like `5 min`) to start research.\n"
            "• When reviewing research or script summaries, click *Approve* or reply with your feedback.\n"
            "• `/status` - Check the status of your active project.\n"
            "• `/cancel` - Cancel your ongoing project.\n"
            "• `/help` - Show this guide."
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

            if active_project.state in (
                WorkflowState.RESEARCHING,
                WorkflowState.SCRIPTING,
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
        """Handle inline button clicks for approving research and scripts."""
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

            await self.state_machine.transition(project_id, WorkflowState.COMPLETED)
            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "🎉 *Script Approved & Finalized!*\n\n"
                    "The narration script is ready. All scenes and voiceovers have been saved.",
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
        """Send message to chat, chunking if exceeding Telegram's 4096 character limit."""
        if not self.app:
            return

        if len(text) <= 4000:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_markup=reply_markup if is_last else None,
                parse_mode=ParseMode.MARKDOWN,
            )

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
                f"🎬 *Scene {scene.scene_number}: {scene.title}*\n{scene.summary}"
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
