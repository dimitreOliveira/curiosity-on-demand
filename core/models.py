"""Core data models and schemas for Curiosity On Demand pipeline."""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """Execution states for the video generation state machine."""

    IDLE = "IDLE"
    RESEARCHING = "RESEARCHING"
    VERIFYING = "VERIFYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    GENERATING_SCRIPT = "GENERATING_SCRIPT"
    GENERATING_SAMPLE = "GENERATING_SAMPLE"
    GENERATING_ASSETS = "GENERATING_ASSETS"
    ASSEMBLING = "ASSEMBLING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnimationType(str, Enum):
    """Visual animation styles for SVG rendering."""

    FADE_SCALE = "fade_scale"
    DATA_COUNTER = "data_counter"
    DIAGRAM_REVEAL = "diagram_reveal"
    KINETIC_TYPOGRAPHY = "kinetic_typography"
    SPLIT_SCREEN = "split_screen"
    INFOGRAPHIC_CARD = "infographic_card"
    CUSTOM_VECTOR = "custom_vector"


class AspectRatio(str, Enum):
    """Video framing orientation."""

    LANDSCAPE_16_9 = "16:9"
    VERTICAL_9_16 = "9:16"
    SQUARE_1_1 = "1:1"


class ResearchSource(BaseModel):
    """Individual web search source reference."""

    title: str = Field(description="Title of source webpage or article")
    url: str = Field(description="Web URL of the citation")
    snippet: str | None = Field(
        default=None, description="Relevant excerpt or context from source"
    )


class ResearchFinding(BaseModel):
    """Structured factual finding extracted by research agent."""

    topic: str = Field(description="Subtopic or theme of this finding")
    claim: str = Field(description="Factual statement or statistic")
    detail: str = Field(description="In-depth explanation, context, and data")
    source_url: str | None = Field(
        default=None, description="URL where claim originated"
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this factual claim",
    )


class ResearchReport(BaseModel):
    """Aggregated findings and citations compiled by researcher agent."""

    topic: str = Field(description="The primary inquiry topic")
    findings: list[ResearchFinding] = Field(
        default_factory=list, description="Verified facts and statistics"
    )
    sources: list[ResearchSource] = Field(
        default_factory=list, description="Citations used during research"
    )
    summary: str = Field(description="Synthesized summary of all research notes")
    raw_notes: str | None = Field(
        default=None, description="Unstructured LLM reasoning and scratchpad"
    )
    iteration: int = Field(
        default=1, description="Current research-verification loop count"
    )


class VerificationResult(BaseModel):
    """Assessment of research report completeness by verifier agent."""

    is_complete: bool = Field(
        description="True if facts are sufficient, accurate, and ready for pitch"
    )
    critique: str = Field(
        description="Critique explaining gaps, missing depth, or quality score"
    )
    follow_up_queries: list[str] = Field(
        default_factory=list,
        description="Targeted follow-up search queries if is_complete is False",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Specific themes, stats, or angles that still need research",
    )
    score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Completeness and quality score (0.0 to 1.0)",
    )


class PitchSummary(BaseModel):
    """Video concept pitch presented to user via Telegram for human review."""

    topic: str = Field(description="The subject of the video")
    title_options: list[str] = Field(
        description="2-4 compelling and engaging title proposals"
    )
    hook: str = Field(description="First 5-10 seconds hook to capture viewer attention")
    target_audience: str = Field(description="Target demographic or interest group")
    key_takeaways: list[str] = Field(
        description="Core insights and takeaways the viewer will gain"
    )
    core_narrative: str = Field(
        description="High-level story arc and visual progression"
    )
    estimated_scenes_count: int = Field(
        default=4, ge=2, le=12, description="Estimated number of scenes"
    )
    estimated_duration_seconds: float = Field(
        default=60.0, ge=15.0, description="Estimated video runtime in seconds"
    )
    revision_notes: str | None = Field(
        default=None, description="Notes from previous user revisions, if any"
    )


class SceneVisualBlueprint(BaseModel):
    """Design specifications for programmatic SVG frame generation."""

    animation_type: AnimationType = Field(
        default=AnimationType.FADE_SCALE,
        description="Animation style for visual dynamism",
    )
    background_gradient: list[str] = Field(
        default_factory=lambda: ["#0f172a", "#1e293b"],
        description="2-stop hex color codes for background gradient",
    )
    accent_color: str = Field(
        default="#38bdf8",
        description="Primary accent color for highlights, shapes, and borders",
    )
    primary_text: str = Field(description="Main headline or stat to render on screen")
    secondary_text: str | None = Field(
        default=None, description="Subtitle, supporting clause, or metric label"
    )
    icon_or_graphic_type: str | None = Field(
        default="chart",
        description="Graphic element descriptor (e.g. chart, brain, globe, network)",
    )


class Scene(BaseModel):
    """Individual scene specification within the full video script."""

    scene_id: int = Field(ge=1, description="1-indexed sequence number of the scene")
    narration: str = Field(
        description="Verbatim voiceover narration text for TTS engine"
    )
    visual_description: str = Field(
        description="Detailed visual prompt describing layout, iconography, and colors"
    )
    svg_source: str = Field(
        description="Valid standalone SVG XML markup (1920x1080 viewBox) or template specification"
    )
    duration_seconds: float = Field(
        ge=2.0,
        le=60.0,
        description="Estimated or allocated duration for this scene in seconds",
    )
    visual_blueprint: SceneVisualBlueprint | None = Field(
        default=None, description="Structured visual styling metadata"
    )
    is_suitable_for_short: bool = Field(
        default=False,
        description="Whether this scene is a standout moment for vertical shorts",
    )

    # Generated file paths populated during rendering phases
    audio_path: str | None = Field(
        default=None, description="Local path to synthesized scene audio MP3/WAV"
    )
    frames_dir: str | None = Field(
        default=None, description="Local directory containing rasterized PNG frames"
    )
    clip_path: str | None = Field(
        default=None, description="Local path to rendered single-scene MP4 clip"
    )


class VideoScript(BaseModel):
    """Full scene-by-scene script generated by scriptwriter agent."""

    title: str = Field(description="Selected official video title")
    description: str = Field(
        description="SEO-optimized description including summary and timestamps"
    )
    tags: list[str] = Field(
        default_factory=list, description="YouTube search tags and keywords"
    )
    scenes: list[Scene] = Field(
        min_length=1, description="Ordered list of scenes comprising the video"
    )
    total_duration_seconds: float = Field(
        default=60.0, description="Sum of scene durations in seconds"
    )
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.LANDSCAPE_16_9, description="Target aspect ratio"
    )
    highlighted_short_scene_ids: list[int] = Field(
        default_factory=list,
        description="List of scene IDs selected for vertical shorts creation",
    )


class ProjectSession(BaseModel):
    """End-to-end pipeline project tracking state and artifacts."""

    project_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique project identifier",
    )
    user_id: int = Field(description="Telegram user ID")
    chat_id: int = Field(description="Telegram chat ID")
    topic: str = Field(description="User prompt or inquiry topic")
    state: WorkflowState = Field(
        default=WorkflowState.IDLE, description="Current workflow state"
    )
    research_report: ResearchReport | None = Field(
        default=None, description="Aggregated research data"
    )
    pitch_summary: PitchSummary | None = Field(
        default=None, description="Human review pitch"
    )
    script: VideoScript | None = Field(
        default=None, description="Generated multi-scene script"
    )
    final_video_path: str | None = Field(
        default=None, description="Path to finished landscape MP4"
    )
    sample_clip_path: str | None = Field(
        default=None, description="Path to preliminary scene-1 preview clip"
    )
    short_video_paths: list[str] = Field(
        default_factory=list, description="Paths to generated 9:16 short clips"
    )
    youtube_url: str | None = Field(
        default=None, description="Published YouTube video URL"
    )
    error_message: str | None = Field(
        default=None, description="Details if an unhandled failure occurred"
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
