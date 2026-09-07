"""Unit tests for main application startup validation and diagnostics."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings
from main import log_startup_diagnostics, main, validate_startup_environment


def test_validate_startup_environment_valid(tmp_path):
    """Test validation succeeds when critical credentials are present."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    # Should not raise
    validate_startup_environment(settings)


def test_validate_startup_environment_missing_gemini(tmp_path):
    """Test validation fails when GEMINI_API_KEY is missing."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        validate_startup_environment(settings)


def test_validate_startup_environment_missing_telegram(tmp_path):
    """Test validation fails when TELEGRAM_BOT_TOKEN is missing."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is not set"):
        validate_startup_environment(settings)


def test_log_startup_diagnostics(tmp_path):
    """Test log_startup_diagnostics executes and logs system info."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        TELEGRAM_ALLOWED_USERS=[123456],
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with patch("main.logger") as mock_logger:
        log_startup_diagnostics(settings)
        assert mock_logger.info.call_count >= 2


def test_log_startup_diagnostics_ffmpeg_missing(tmp_path):
    """Test log_startup_diagnostics warns when FFmpeg binary cannot be detected."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with (
        patch("shutil.which", return_value=None),
        patch("imageio_ffmpeg.get_ffmpeg_exe", side_effect=RuntimeError("Not found")),
        patch("main.logger") as mock_logger,
    ):
        log_startup_diagnostics(settings)
        assert any(
            "FFmpeg binary not detected" in str(call)
            for call in mock_logger.warning.call_args_list
        )


def test_log_startup_diagnostics_youtube_configured(tmp_path):
    """Test log_startup_diagnostics logs configured status when YouTube publishing is active."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with (
        patch(
            "services.youtube_publisher.YouTubePublisher.is_configured",
            return_value=True,
        ),
        patch("main.logger") as mock_logger,
    ):
        log_startup_diagnostics(settings)
        assert any(
            "YouTube Publishing: CONFIGURED" in str(call)
            for call in mock_logger.info.call_args_list
        )


@pytest.mark.asyncio
async def test_main_validation_failure(tmp_path):
    """Test main exits with status code 1 when required credentials are missing."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="",
        TELEGRAM_BOT_TOKEN="",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    with (
        patch("main.get_settings", return_value=settings),
        pytest.raises(SystemExit) as exc_info,
    ):
        await main()
    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_main_lifecycle_clean_shutdown(tmp_path):
    """Test main initializes all components and shuts down cleanly upon stop event."""
    settings = Settings(
        _env_file=None,
        GEMINI_API_KEY="valid_gemini_key",
        TELEGRAM_BOT_TOKEN="valid_telegram_token",
        STORAGE_DIR=tmp_path / "storage",
        SQLITE_DB_PATH=tmp_path / "test.db",
    )
    mock_db = AsyncMock()
    mock_app = AsyncMock()
    mock_updater = AsyncMock()
    mock_app.updater = mock_updater
    mock_bot_service = MagicMock()
    mock_bot_service.build_application = AsyncMock(return_value=mock_app)
    mock_bot_service.setup_bot_commands = AsyncMock()

    with (
        patch("main.get_settings", return_value=settings),
        patch("main.get_db_manager", return_value=mock_db),
        patch("main.TelegramBotService", return_value=mock_bot_service),
        patch("asyncio.Event.wait", new_callable=AsyncMock) as mock_wait,
    ):
        mock_wait.return_value = True
        await main()

    mock_db.init_db.assert_awaited_once()
    mock_bot_service.build_application.assert_awaited_once()
    mock_app.initialize.assert_awaited_once()
    mock_bot_service.setup_bot_commands.assert_awaited_once()
    mock_app.start.assert_awaited_once()
    mock_updater.start_polling.assert_awaited_once()
    mock_updater.stop.assert_awaited_once()
    mock_app.stop.assert_awaited_once()
    mock_app.shutdown.assert_awaited_once()
