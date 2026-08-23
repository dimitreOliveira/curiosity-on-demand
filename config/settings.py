"""Application configuration and environment settings."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Curiosity On Demand pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini AI Configuration
    gemini_api_key: str = Field(
        default="",
        alias="GEMINI_API_KEY",
        description="Google Gemini API key",
    )
    gemini_model: str = Field(
        default="gemini-3.7-flash",
        alias="GEMINI_MODEL",
        description="Default Gemini model for summarization and scriptwriting",
    )
    research_model: str = Field(
        default="gemini-3.7-flash",
        alias="RESEARCH_MODEL",
        description="Gemini model for research and verification with search grounding",
    )
    tts_model: str = Field(
        default="gemini-2.0-flash",
        alias="TTS_MODEL",
        description="Gemini model for text-to-speech narration synthesis",
    )
    tts_voice: str = Field(
        default="random",
        alias="TTS_VOICE",
        description="Gemini voice name for speech synthesis (e.g. random, Puck, Charon, Kore, Fenrir, Zephyr)",
    )

    # Telegram Bot Configuration
    telegram_bot_token: str = Field(
        default="",
        alias="TELEGRAM_BOT_TOKEN",
        description="Telegram bot authentication token",
    )
    telegram_allowed_users: str | list[str | int] = Field(
        default_factory=list,
        alias="TELEGRAM_ALLOWED_USERS",
        description="Optional list of Telegram user IDs or usernames permitted to trigger pipeline",
    )

    @field_validator("telegram_allowed_users", mode="after")
    @classmethod
    def _parse_allowed_users(cls, v: Any) -> list[str | int]:
        if not v:
            return []
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [
                            int(x) if str(x).isdigit() else str(x).strip().lstrip("@")
                            for x in parsed
                        ]
                except json.JSONDecodeError:
                    pass
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return [int(x) if x.isdigit() else x.lstrip("@") for x in parts]
        if isinstance(v, (list, tuple, set)):
            res: list[str | int] = []
            for item in v:
                if isinstance(item, int):
                    res.append(item)
                elif isinstance(item, str) and item.isdigit():
                    res.append(int(item))
                elif isinstance(item, str) and item.strip():
                    res.append(item.strip().lstrip("@"))
            return res
        return []

    # YouTube Configuration (OAuth2 Client)
    youtube_client_secrets_file: Path = Field(
        default=Path("client_secrets.json"),
        alias="YOUTUBE_CLIENT_SECRETS_FILE",
        description="Path to OAuth2 client_secrets.json for YouTube Data API",
    )
    youtube_token_file: Path = Field(
        default=Path("storage/youtube_token.json"),
        alias="YOUTUBE_TOKEN_FILE",
        description="Path to store refreshed YouTube OAuth2 user token",
    )

    # Storage and Output Paths
    storage_dir: Path = Field(
        default=Path("storage"),
        alias="STORAGE_DIR",
        description="Base storage directory for project files and caches",
    )
    media_output_dir: Path = Field(
        default=Path("storage/media"),
        alias="MEDIA_OUTPUT_DIR",
        description="Directory where generated audio, SVG frames, and MP4 videos are saved",
    )
    sqlite_db_path: Path = Field(
        default=Path("storage/curiosity.db"),
        alias="SQLITE_DB_PATH",
        description="SQLite database file path for session and state tracking",
    )

    # Pipeline Constraints & Video Parameters
    max_research_iterations: int = Field(
        default=3,
        alias="MAX_RESEARCH_ITERATIONS",
        description="Maximum iterations between researcher and verifier agents",
    )
    default_video_width: int = Field(
        default=1920,
        alias="DEFAULT_VIDEO_WIDTH",
        description="Default landscape video width (1080p)",
    )
    default_video_height: int = Field(
        default=1080,
        alias="DEFAULT_VIDEO_HEIGHT",
        description="Default landscape video height (1080p)",
    )
    short_video_width: int = Field(
        default=1080,
        alias="SHORT_VIDEO_WIDTH",
        description="Vertical short video width (9:16)",
    )
    short_video_height: int = Field(
        default=1920,
        alias="SHORT_VIDEO_HEIGHT",
        description="Vertical short video height (9:16)",
    )
    default_fps: int = Field(
        default=30,
        alias="DEFAULT_FPS",
        description="Target frames per second for video rendering",
    )

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.media_output_dir.mkdir(parents=True, exist_ok=True)
        if self.sqlite_db_path.parent:
            self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached global settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
