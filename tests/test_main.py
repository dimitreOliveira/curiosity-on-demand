"""Unit tests for main application startup validation and diagnostics."""

from unittest.mock import patch

import pytest

from config.settings import Settings
from main import log_startup_diagnostics, validate_startup_environment


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
    """Test log_startup_diagnostics executes without exception."""
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
