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
        description="Default Gemini model",
    )
    research_model: str = Field(
        default="gemini-3.7-flash",
        alias="RESEARCH_MODEL",
        description="Gemini model for research with search grounding",
    )
    evaluator_model: str = Field(
        default="gemini-3.7-flash",
        alias="EVALUATOR_MODEL",
        description="Gemini model for research evaluation and structuring",
    )
    script_model: str = Field(
        default="gemini-3.7-flash",
        alias="SCRIPT_MODEL",
        description="Gemini model for narration script generation",
    )
    animator_model: str = Field(
        default="gemini-3.7-flash",
        alias="ANIMATOR_MODEL",
        description="Gemini model for visual animation styling and code generation",
    )
    video_width: int = Field(
        default=1280,
        alias="VIDEO_WIDTH",
        description="Rendered video width in pixels",
    )
    video_height: int = Field(
        default=720,
        alias="VIDEO_HEIGHT",
        description="Rendered video height in pixels",
    )
    default_scene_duration_seconds: int = Field(
        default=10,
        alias="DEFAULT_SCENE_DURATION_SECONDS",
        description="Default playback duration per scene in seconds",
    )
    max_research_iterations: int = Field(
        default=3,
        alias="MAX_RESEARCH_ITERATIONS",
        description="Maximum iterative research-evaluator refinement rounds",
    )
    default_video_duration_minutes: int = Field(
        default=10,
        alias="DEFAULT_VIDEO_DURATION_MINUTES",
        description="Default target video duration in minutes when unspecified",
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

    # Storage and Output Paths
    storage_dir: Path = Field(
        default=Path("storage"),
        alias="STORAGE_DIR",
        description="Base storage directory for project files and database",
    )
    sqlite_db_path: Path = Field(
        default=Path("storage/curiosity.db"),
        alias="SQLITE_DB_PATH",
        description="SQLite database file path for session and state tracking",
    )

    @property
    def renders_dir(self) -> Path:
        """Directory for rendered frames, animations, and final video outputs."""
        return self.storage_dir / "renders"

    @property
    def animations_dir(self) -> Path:
        """Directory for saved scene HTML/SVG animation code files."""
        return self.storage_dir / "animations"

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        self.animations_dir.mkdir(parents=True, exist_ok=True)
        if self.sqlite_db_path.parent:
            self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached global settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
