"""Core data models and schemas for Curiosity On Demand pipeline."""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """Execution states for the video research and scripting state machine."""

    IDLE = "IDLE"
    RESEARCHING = "RESEARCHING"
    AWAITING_RESEARCH_APPROVAL = "AWAITING_RESEARCH_APPROVAL"
    SCRIPTING = "SCRIPTING"
    AWAITING_SCRIPT_APPROVAL = "AWAITING_SCRIPT_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResearchSection(BaseModel):
    """Researched subtopic and its detailed content."""

    topic: str = Field(description="The subtopic or theme investigated")
    content: str = Field(
        description="The researched facts, insights, context, and details for this subtopic"
    )


class ResearchReport(BaseModel):
    """Aggregated research gathered for a video topic."""

    topic: str = Field(description="The primary inquiry or subject researched")
    summary: str = Field(
        description="Comprehensive high-level summary of the topic and key takeaways"
    )
    sections: list[ResearchSection] = Field(
        default_factory=list,
        description="Researched subtopics and their detailed contents",
    )


class EvaluationResult(BaseModel):
    """Outcome of the evaluator agent assessing research completeness and quality."""

    is_sufficient: bool = Field(
        description="True if the research is thorough, factually rich, and sufficient to produce a high-quality educational video of the target duration; False if critical gaps or more context is needed."
    )
    feedback_for_researcher: str | None = Field(
        default=None,
        description="Actionable guidance, missing questions, or specific angles the researcher should investigate in the next round if not sufficient.",
    )
    report: ResearchReport = Field(
        description="The cleaned, filtered, and structured research report with duplicates and irrelevant info removed."
    )


class ScriptScene(BaseModel):
    """A segment or scene in the video narration script."""

    scene_number: int = Field(description="Sequential index of this scene/segment")
    title: str = Field(description="Title or theme of this scene")
    summary: str = Field(
        description="Concise summary of the concept and content in this scene"
    )
    narration: str = Field(description="Spoken voiceover narration text for this scene")


class Script(BaseModel):
    """Complete scene-by-scene narration script for a video."""

    topic: str = Field(description="The primary subject of the script")
    summary: str = Field(
        description="Overall summary of the narration arc and video structure"
    )
    scenes: list[ScriptScene] = Field(
        default_factory=list,
        description="Ordered list of script scenes/segments",
    )


class ProjectSession(BaseModel):
    """Pipeline project session tracking state, research, and script results."""

    project_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique project identifier",
    )
    user_id: int = Field(description="Telegram user ID")
    chat_id: int = Field(description="Telegram chat ID")
    topic: str = Field(description="User submitted topic or inquiry")
    state: WorkflowState = Field(
        default=WorkflowState.IDLE, description="Current workflow state"
    )
    research_report: ResearchReport | None = Field(
        default=None, description="Researched report and subtopics"
    )
    script: Script | None = Field(
        default=None, description="Generated scene-by-scene narration script"
    )
    error_message: str | None = Field(
        default=None, description="Error message if workflow failed"
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
