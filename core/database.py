"""Database layer for persistent session state using SQLAlchemy and SQLite."""

import json
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config.settings import get_settings
from core.models import (
    PitchSummary,
    ProjectSession,
    ResearchReport,
    VideoScript,
    WorkflowState,
)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


class ProjectRecord(Base):
    """SQLAlchemy model for persisting video project lifecycle and artifacts."""

    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowState.IDLE.value
    )

    # JSON-encoded payloads for structured agent outputs
    research_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pitch_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Rendered media paths and publishing links
    final_video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sample_clip_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    short_videos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def to_session(self) -> ProjectSession:
        """Convert database record into a strongly-typed ProjectSession Pydantic model."""
        research_report = (
            ResearchReport.model_validate_json(self.research_json)
            if self.research_json
            else None
        )
        pitch_summary = (
            PitchSummary.model_validate_json(self.pitch_json)
            if self.pitch_json
            else None
        )
        script = (
            VideoScript.model_validate_json(self.script_json)
            if self.script_json
            else None
        )
        short_paths: list[str] = (
            json.loads(self.short_videos_json) if self.short_videos_json else []
        )

        return ProjectSession(
            project_id=self.project_id,
            user_id=self.user_id,
            chat_id=self.chat_id,
            topic=self.topic,
            state=WorkflowState(self.state),
            research_report=research_report,
            pitch_summary=pitch_summary,
            script=script,
            final_video_path=self.final_video_path,
            sample_clip_path=self.sample_clip_path,
            short_video_paths=short_paths,
            youtube_url=self.youtube_url,
            error_message=self.error_message,
            created_at=self.created_at.isoformat()
            if self.created_at
            else datetime.now(UTC).isoformat(),
            updated_at=self.updated_at.isoformat()
            if self.updated_at
            else datetime.now(UTC).isoformat(),
        )


class DatabaseManager:
    """Manages database connection and session operations."""

    def __init__(self, db_url: str | None = None):
        if db_url is None:
            settings = get_settings()
            db_path = settings.sqlite_db_path.resolve()
            db_url = f"sqlite+aiosqlite:///{db_path}"

        self.engine: AsyncEngine = create_async_engine(db_url, echo=False)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def init_db(self) -> None:
        """Create database tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_project(
        self, user_id: int, chat_id: int, topic: str
    ) -> ProjectSession:
        """Create a new project session record."""
        session_obj = ProjectSession(
            user_id=user_id,
            chat_id=chat_id,
            topic=topic,
            state=WorkflowState.IDLE,
        )
        record = ProjectRecord(
            project_id=session_obj.project_id,
            user_id=user_id,
            chat_id=chat_id,
            topic=topic,
            state=session_obj.state.value,
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
        return session_obj

    async def get_project(self, project_id: str) -> ProjectSession | None:
        """Fetch project session by project ID."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            return record.to_session() if record else None

    async def get_active_project_for_chat(self, chat_id: int) -> ProjectSession | None:
        """Fetch the most recent active (non-completed/non-failed) project for a chat."""
        async with self.session_factory() as session:
            stmt = (
                select(ProjectRecord)
                .where(
                    ProjectRecord.chat_id == chat_id,
                    ProjectRecord.state.notin_(
                        [
                            WorkflowState.COMPLETED.value,
                            WorkflowState.FAILED.value,
                        ]
                    ),
                )
                .order_by(ProjectRecord.updated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            return record.to_session() if record else None

    async def update_project_state(
        self,
        project_id: str,
        state: WorkflowState,
        error_message: str | None = None,
    ) -> ProjectSession | None:
        """Update workflow status and optional error message."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.state = state.value
            if error_message is not None:
                record.error_message = error_message
            record.updated_at = datetime.now(UTC)
            await session.commit()
            return record.to_session()

    async def save_research_report(
        self, project_id: str, report: ResearchReport
    ) -> ProjectSession | None:
        """Persist structured research findings."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.research_json = report.model_dump_json()
            record.updated_at = datetime.now(UTC)
            await session.commit()
            return record.to_session()

    async def save_pitch_summary(
        self, project_id: str, pitch: PitchSummary
    ) -> ProjectSession | None:
        """Persist pitch summary ready for user review."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.pitch_json = pitch.model_dump_json()
            record.updated_at = datetime.now(UTC)
            await session.commit()
            return record.to_session()

    async def save_video_script(
        self, project_id: str, script: VideoScript
    ) -> ProjectSession | None:
        """Persist scene-by-scene script."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.script_json = script.model_dump_json()
            record.updated_at = datetime.now(UTC)
            await session.commit()
            return record.to_session()

    async def save_media_outputs(
        self,
        project_id: str,
        final_video_path: str | None = None,
        sample_clip_path: str | None = None,
        short_paths: list[str] | None = None,
        youtube_url: str | None = None,
    ) -> ProjectSession | None:
        """Save media artifact paths and published YouTube URL."""
        async with self.session_factory() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.project_id == project_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None
            if final_video_path:
                record.final_video_path = final_video_path
            if sample_clip_path:
                record.sample_clip_path = sample_clip_path
            if short_paths is not None:
                record.short_videos_json = json.dumps(short_paths)
            if youtube_url:
                record.youtube_url = youtube_url
            record.updated_at = datetime.now(UTC)
            await session.commit()
            return record.to_session()


_db_manager: DatabaseManager | None = None


def get_db_manager() -> DatabaseManager:
    """Retrieve singleton DatabaseManager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
