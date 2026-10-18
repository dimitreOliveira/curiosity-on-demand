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
        description="Google Gemini API key (or Vertex AI Express Mode API key)",
    )
    gemini_use_vertexai: bool = Field(
        default=False,
        alias="GEMINI_USE_VERTEXAI",
        description="Whether to route Gemini API requests through Vertex AI endpoints",
    )
    google_cloud_project: str = Field(
        default="",
        alias="GOOGLE_CLOUD_PROJECT",
        description="Google Cloud project ID or number for Vertex AI requests",
    )
    google_cloud_location: str = Field(
        default="global",
        alias="GOOGLE_CLOUD_LOCATION",
        description="Google Cloud location/region for Vertex AI requests (e.g., global, us-central1)",
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
    narration_planner_model: str = Field(
        default="gemini-3.7-flash",
        alias="NARRATION_PLANNER_MODEL",
        description="Gemini model for audio direction and narration planning",
    )
    tts_model: str = Field(
        default="gemini-3.8-flash-tts",
        alias="TTS_MODEL",
        description="Gemini model for text-to-speech voice audio generation",
    )
    default_tts_voice: str = Field(
        default="Zephyr",
        alias="DEFAULT_TTS_VOICE",
        description="Default voice name for Gemini speech generation",
    )
    video_width: int = Field(
        default=1920,
        alias="VIDEO_WIDTH",
        description="Rendered horizontal video width in pixels",
    )
    video_height: int = Field(
        default=1080,
        alias="VIDEO_HEIGHT",
        description="Rendered horizontal video height in pixels",
    )
    vertical_video_width: int = Field(
        default=1080,
        alias="VERTICAL_VIDEO_WIDTH",
        description="Rendered vertical video width in pixels (YouTube Shorts style)",
    )
    vertical_video_height: int = Field(
        default=1920,
        alias="VERTICAL_VIDEO_HEIGHT",
        description="Rendered vertical video height in pixels (YouTube Shorts style)",
    )
    vertical_video_threshold_seconds: int = Field(
        default=120,
        alias="VERTICAL_VIDEO_THRESHOLD_SECONDS",
        description="Video duration threshold in seconds (inclusive) under which videos are generated in vertical format",
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
        default=5,
        alias="DEFAULT_VIDEO_DURATION_MINUTES",
        description="Default target video duration in minutes when unspecified",
    )
    render_concurrency: int = Field(
        default=3,
        alias="RENDER_CONCURRENCY",
        description="Maximum concurrent Playwright browser scene rendering sessions",
    )
    tts_concurrency: int = Field(
        default=3,
        alias="TTS_CONCURRENCY",
        description="Maximum concurrent Gemini TTS speech synthesis tasks",
    )
    animation_concurrency: int = Field(
        default=6,
        alias="ANIMATION_CONCURRENCY",
        description="Maximum concurrent Gemini LLM scene canvas code generation tasks",
    )
    ffmpeg_concurrency: int = Field(
        default=4,
        alias="FFMPEG_CONCURRENCY",
        description="Maximum concurrent FFmpeg audio/video retiming and muxing processes",
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
    telegram_max_video_size_mb: float = Field(
        default=49.0,
        alias="TELEGRAM_MAX_VIDEO_SIZE_MB",
        description="Maximum video size in MB allowed for Telegram upload (standard limit is 50MB)",
    )
    telegram_preview_max_duration_seconds: float = Field(
        default=60.0,
        alias="TELEGRAM_PREVIEW_MAX_DURATION_SECONDS",
        description="Maximum duration in seconds for video preview sent via Telegram when full video exceeds limits",
    )
    telegram_upload_timeout_seconds: float = Field(
        default=300.0,
        alias="TELEGRAM_UPLOAD_TIMEOUT_SECONDS",
        description="Timeout in seconds for Telegram media uploads (video, audio, photo)",
    )
    telegram_request_timeout_seconds: float = Field(
        default=60.0,
        alias="TELEGRAM_REQUEST_TIMEOUT_SECONDS",
        description="Default timeout in seconds for standard Telegram API requests",
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

    # YouTube Publishing Configuration
    youtube_client_id: str = Field(
        default="",
        alias="YOUTUBE_CLIENT_ID",
        description="Google OAuth 2.0 Client ID for YouTube Data API",
    )
    youtube_client_secret: str = Field(
        default="",
        alias="YOUTUBE_CLIENT_SECRET",
        description="Google OAuth 2.0 Client Secret for YouTube Data API",
    )
    youtube_refresh_token: str = Field(
        default="",
        alias="YOUTUBE_REFRESH_TOKEN",
        description="Google OAuth 2.0 Refresh Token for headless YouTube publishing",
    )
    youtube_token_file: Path = Field(
        default=Path("storage/youtube_token.json"),
        alias="YOUTUBE_TOKEN_FILE",
        description="Path to stored OAuth credentials/token JSON file",
    )
    youtube_client_secrets_file: Path | None = Field(
        default=None,
        alias="YOUTUBE_CLIENT_SECRETS_FILE",
        description="Optional path to client_secrets.json for interactive OAuth authentication flow",
    )

    @field_validator("youtube_client_secrets_file", mode="before")
    @classmethod
    def _parse_optional_path(cls, v: Any) -> Path | None:
        if not v or (isinstance(v, str) and not v.strip()):
            return None
        return Path(v)

    @field_validator("youtube_token_file", mode="before")
    @classmethod
    def _parse_token_path(cls, v: Any) -> Path:
        if not v or (isinstance(v, str) and not v.strip()):
            return Path("storage/youtube_token.json")
        return Path(v)

    youtube_default_privacy_status: str = Field(
        default="public",
        alias="YOUTUBE_DEFAULT_PRIVACY_STATUS",
        description="Default video privacy status (public, unlisted, private)",
    )
    youtube_default_category_id: str = Field(
        default="27",
        alias="YOUTUBE_DEFAULT_CATEGORY_ID",
        description="YouTube category ID (default: 27 for Education)",
    )
    youtube_default_tags: str | list[str] = Field(
        default_factory=lambda: ["CuriosityOnDemand", "Education", "Animation"],
        alias="YOUTUBE_DEFAULT_TAGS",
        description="Default tags included when publishing to YouTube",
    )

    @field_validator("youtube_default_tags", mode="after")
    @classmethod
    def _parse_youtube_tags(cls, v: Any) -> list[str]:
        if not v:
            return ["CuriosityOnDemand", "Education", "Animation"]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["CuriosityOnDemand", "Education", "Animation"]
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except json.JSONDecodeError:
                    pass
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or ["CuriosityOnDemand", "Education", "Animation"]
        if isinstance(v, (list, tuple, set)):
            return [str(item).strip() for item in v if str(item).strip()]
        return ["CuriosityOnDemand", "Education", "Animation"]

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

    @property
    def audio_dir(self) -> Path:
        """Directory for synthesized voiceover narration audio files."""
        return self.storage_dir / "audio"

    def is_vertical_video(self, duration_seconds: float | None = None) -> bool:
        """Check if video should be rendered in vertical format based on duration.

        Videos with duration of 2 minutes or shorter (<= 120s) use vertical format (YouTube Shorts style).
        """
        if duration_seconds is None or duration_seconds <= 0:
            return False
        return duration_seconds <= self.vertical_video_threshold_seconds

    def get_video_dimensions(
        self,
        duration_seconds: float | None = None,
        is_vertical: bool | None = None,
    ) -> tuple[int, int]:
        """Return (width, height) based on duration or explicit vertical flag."""
        if is_vertical is True or (
            is_vertical is None and self.is_vertical_video(duration_seconds)
        ):
            return self.vertical_video_width, self.vertical_video_height
        return self.video_width, self.video_height

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        self.animations_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        if self.sqlite_db_path.parent:
            self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached global settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
