"""Core module exports."""

from core.audio_utils import normalize_inline_audio_tags
from core.caption_utils import (
    format_srt_timestamp,
    generate_srt_content,
    save_srt_subtitles,
    split_text_into_caption_cues,
    strip_audio_tags,
)
from core.database import Base, DatabaseManager, ProjectRecord, get_db_manager
from core.models import (
    EvaluationResult,
    NarrationPlan,
    NarrationStoryboard,
    ProjectSession,
    ResearchReport,
    ResearchSection,
    SceneAudio,
    SceneNarrationPlan,
    Script,
    ScriptScene,
    WorkflowState,
    compute_project_folder,
)
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine

__all__ = [
    "Base",
    "DatabaseManager",
    "EvaluationResult",
    "InvalidStateTransitionError",
    "NarrationPlan",
    "NarrationStoryboard",
    "PipelineStateMachine",
    "ProjectRecord",
    "ProjectSession",
    "ResearchReport",
    "ResearchSection",
    "SceneAudio",
    "SceneNarrationPlan",
    "Script",
    "ScriptScene",
    "WorkflowState",
    "compute_project_folder",
    "format_srt_timestamp",
    "generate_srt_content",
    "get_db_manager",
    "normalize_inline_audio_tags",
    "save_srt_subtitles",
    "split_text_into_caption_cues",
    "strip_audio_tags",
]
