"""Main application entrypoint for Curiosity On Demand pipeline and Telegram bot."""

import asyncio
import logging
import shutil
import signal
import sys

import imageio_ffmpeg

from config.settings import Settings, get_settings
from core.database import get_db_manager
from services.telegram_bot import TelegramBotService
from services.youtube_publisher import YouTubePublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Silence noisy external library loggers
for noisy_logger in (
    "httpx",
    "httpcore",
    "telegram",
    "apscheduler",
    "google_genai",
):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger("curiosity-on-demand")


def validate_startup_environment(settings: Settings) -> None:
    """Validate critical environment credentials before service startup.

    Raises:
        ValueError: If critical credentials such as GEMINI_API_KEY or
            TELEGRAM_BOT_TOKEN are missing.
    """
    if not settings.gemini_api_key or not settings.gemini_api_key.strip():
        raise ValueError(
            "GEMINI_API_KEY is not set in environment or .env file. "
            "Please configure your Gemini API key from https://aistudio.google.com/."
        )

    if not settings.telegram_bot_token or not settings.telegram_bot_token.strip():
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set in environment or .env file. "
            "Please configure your bot token from https://t.me/BotFather."
        )


def log_startup_diagnostics(settings: Settings) -> None:
    """Log system dependencies, tools, and configuration state at launch."""
    logger.info(
        "Using Gemini Model: %s (Research: %s, TTS: %s)",
        settings.gemini_model,
        settings.research_model,
        settings.tts_model,
    )

    # Detect FFmpeg binary availability
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        try:
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except (RuntimeError, OSError):
            ffmpeg_bin = None

    if ffmpeg_bin:
        logger.info("FFmpeg binary detected: %s", ffmpeg_bin)
    else:
        logger.warning(
            "FFmpeg binary not detected on PATH or via imageio-ffmpeg! "
            "Video assembly and muxing may fail."
        )

    # Detect YouTube publishing configuration
    publisher = YouTubePublisher(settings=settings)
    if publisher.is_configured():
        logger.info(
            "YouTube Publishing: CONFIGURED (privacy: %s, category: %s)",
            settings.youtube_default_privacy_status,
            settings.youtube_default_category_id,
        )
    else:
        logger.info(
            "YouTube Publishing: NOT CONFIGURED (channel uploads disabled; step will be skipped)"
        )

    # Log Access Control
    if settings.telegram_allowed_users:
        logger.info(
            "Access Control: Restricted to %d authorized user(s)",
            len(settings.telegram_allowed_users),
        )
    else:
        logger.info("Access Control: Open to all Telegram users")


async def main() -> None:
    """Initialize system, database, and launch Telegram bot polling."""
    settings = get_settings()
    logger.info("Initializing Curiosity On Demand Video Pipeline...")

    # 1. Validate required environment credentials
    try:
        validate_startup_environment(settings)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # 2. Log startup diagnostics
    log_startup_diagnostics(settings)

    # 3. Initialize SQLite database
    db_manager = get_db_manager()
    await db_manager.init_db()
    logger.info("Database initialized at %s", settings.sqlite_db_path)

    # 4. Build Telegram Bot Service
    bot_service = TelegramBotService(settings=settings, db=db_manager)
    application = await bot_service.build_application()

    # 5. Handle graceful shutdown
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
    await bot_service.setup_bot_commands()
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
