"""Core module exports."""

from core.database import Base, DatabaseManager, ProjectRecord, get_db_manager
from core.models import (
    AnimationType,
    AspectRatio,
    PitchSummary,
    ProjectSession,
    ResearchFinding,
    ResearchReport,
    ResearchSource,
    Scene,
    SceneVisualBlueprint,
    VerificationResult,
    VideoScript,
    WorkflowState,
)
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine

__all__ = [
    "AnimationType",
    "AspectRatio",
    "Base",
    "DatabaseManager",
    "InvalidStateTransitionError",
    "PipelineStateMachine",
    "PitchSummary",
    "ProjectRecord",
    "ProjectSession",
    "ResearchFinding",
    "ResearchReport",
    "ResearchSource",
    "Scene",
    "SceneVisualBlueprint",
    "VerificationResult",
    "VideoScript",
    "WorkflowState",
    "get_db_manager",
]
