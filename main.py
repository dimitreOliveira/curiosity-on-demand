"""Main application entrypoint for Curiosity On Demand pipeline and Telegram bot."""

import asyncio
import logging
import signal
import sys

from config.settings import get_settings
from core.database import get_db_manager
from services.telegram_bot import TelegramBotService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("curiosity-on-demand")


async def main() -> None:
    """Initialize system, database, and launch Telegram bot polling."""
    settings = get_settings()
    logger.info("Initializing Curiosity On Demand Video Pipeline...")
    logger.info(
        "Using Gemini Model: %s (Research: %s)",
        settings.gemini_model,
        settings.research_model,
    )

    # 1. Initialize SQLite database
    db_manager = get_db_manager()
    await db_manager.init_db()
    logger.info("Database initialized at %s", settings.sqlite_db_path)

    # 2. Check for Telegram Bot Token
    if not settings.telegram_bot_token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set in environment or .env file. "
            "Please configure your token to start the Telegram bot."
        )
        sys.exit(1)

    # 3. Build Telegram Bot Service
    bot_service = TelegramBotService(settings=settings, db=db_manager)
    application = await bot_service.build_application()

    # 4. Handle graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received termination signal. Shutting down gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Fallback for platforms where add_signal_handler is not implemented
            pass

    logger.info("Starting Telegram Bot long-polling...")
    await application.initialize()
    await application.start()
    if application.updater:
        await application.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot is active and listening for topics! Press Ctrl+C to stop.")
    await stop_event.wait()

    logger.info("Stopping Telegram Bot...")
    if application.updater:
        await application.updater.stop()
    await application.stop()
    await application.shutdown()
    logger.info("Curiosity On Demand stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process terminated.")
