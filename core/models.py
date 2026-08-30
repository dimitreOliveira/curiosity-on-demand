"""Core data models and schemas for Curiosity On Demand pipeline."""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """Execution states for the video research state machine."""

    IDLE = "IDLE"
    RESEARCHING = "RESEARCHING"
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


class ProjectSession(BaseModel):
    """Pipeline project session tracking state and research results."""

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
    error_message: str | None = Field(
        default=None, description="Error message if research failed"
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
