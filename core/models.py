"""Core data models and schemas for Curiosity On Demand pipeline."""

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def compute_project_folder(topic: str, created_at: datetime | str | None = None) -> str:
    """Generate visual storage folder name based on topic slug and creation timestamp."""
    topic_slug = (
        re.sub(r"[^\w]+", "_", (topic or "").strip().lower()).strip("_") or "project"
    )
    if isinstance(created_at, datetime):
        ts = created_at.strftime("%Y%m%d_%H%M%S")
    elif isinstance(created_at, str):
        try:
            ts = datetime.fromisoformat(created_at).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    else:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{topic_slug}_{ts}"


class WorkflowState(str, Enum):
    """Execution states for the video research, scripting, and animation state machine."""

    IDLE = "IDLE"
    RESEARCHING = "RESEARCHING"
    AWAITING_RESEARCH_APPROVAL = "AWAITING_RESEARCH_APPROVAL"
    SCRIPTING = "SCRIPTING"
    AWAITING_SCRIPT_APPROVAL = "AWAITING_SCRIPT_APPROVAL"
    NARRATING = "NARRATING"
    AWAITING_NARRATION_APPROVAL = "AWAITING_NARRATION_APPROVAL"
    STYLING = "STYLING"
    AWAITING_STYLE_APPROVAL = "AWAITING_STYLE_APPROVAL"
    ANIMATING = "ANIMATING"
    AWAITING_PUBLISH_APPROVAL = "AWAITING_PUBLISH_APPROVAL"
    PUBLISHING = "PUBLISHING"
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
    description: str = Field(
        default="",
        description="Detailed visual description of the visual elements, motion, metaphors, transitions, diagrams, and graphics to appear on screen for this scene",
    )
    duration_seconds: int = Field(
        default=10,
        description="Estimated duration of this scene in seconds based on narration word count and target video length",
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


class AnimationStyle(BaseModel):
    """Visual theme and design aesthetic chosen for video animations."""

    style_name: str = Field(
        description="Descriptive name of the visual style (e.g. 'Warm Editorial Vector Illustration', 'Vibrant Flat Motion Graphics', 'Minimalist Luminous Storybook', 'Dynamic Kinetic Collage', 'Atmospheric 2D Cinematic')"
    )
    visual_description: str = Field(
        description="Detailed description of visual aesthetics, composition, lighting, backgrounds, and art direction"
    )
    color_palette: list[str] = Field(
        default_factory=list,
        description="List of primary and accent hex color codes used across all scenes",
    )
    font_family: str = Field(
        default="Inter, sans-serif",
        description="Typography and font stack for on-screen titles and diagram callouts (e.g. 'Inter, sans-serif', 'Cinzel, Georgia, serif', 'Outfit, sans-serif')",
    )
    animation_guidelines: str = Field(
        description="Principles and motion design guidelines for SVG and Canvas animations in this style"
    )
    background_tone: str = Field(
        default="warm",
        description="Overall background mood and brightness direction for the visual style (e.g., 'warm parchment', 'cool dark atmospheric', 'soft pastel', 'vibrant saturated', 'clean white studio', 'deep oceanic', 'sunset gradient'). Guides whether scene animations use dark, light, warm, or colored backgrounds.",
    )


class SceneAnimation(BaseModel):
    """Self-contained SVG + HTML canvas code and configuration for a single scene."""

    scene_number: int = Field(
        description="Sequential index of this scene matching the script"
    )
    title: str = Field(description="Title of this scene")
    html_content: str = Field(
        description="Full, standalone executable HTML code containing CSS, SVG, and HTML5 Canvas JS animations"
    )
    duration_seconds: float = Field(
        default=10.0,
        description="Playback duration in seconds for this scene",
    )
    notes: str | None = Field(
        default=None,
        description="Visual design explanation and metaphor notes for this scene",
    )


class AnimationStoryboard(BaseModel):
    """Collection of animations for all scenes in a video project."""

    topic: str = Field(description="The video topic")
    style: AnimationStyle = Field(description="The approved visual animation style")
    scenes: list[SceneAnimation] = Field(
        default_factory=list,
        description="Ordered list of scene animations",
    )
    sample_frame_path: str | None = Field(
        default=None,
        description="Filesystem path to the rendered Scene 1 sample frame image",
    )
    final_video_path: str | None = Field(
        default=None,
        description="Filesystem path to the assembled final MP4 video",
    )
    captions_path: str | None = Field(
        default=None,
        description="Filesystem path to the generated synchronized SRT captions file",
    )


class SceneNarrationPlan(BaseModel):
    """Directorial performance plan and audio tags for an individual scene."""

    scene_number: int = Field(
        description="Sequential index of this scene matching the script"
    )
    title: str = Field(description="Title or theme of this scene")
    original_narration: str = Field(
        description="The original voiceover narration text from the script"
    )
    enhanced_narration: str = Field(
        description="Voiceover narration annotated with inline emotional and delivery audio tags (e.g., [excitedly], [amazed], [curious], [thoughtful], [gasp], [serious], [very fast], [sighs]). Minimize [whispers], reserving only when strictly fitting."
    )
    tone: str = Field(
        description="Emotional vibe and vocal attitude for this scene (e.g., 'Intrigued and thoughtful revelation', 'Upbeat energetic revelation')"
    )
    pace: str = Field(
        description="Pacing and cadence direction for this scene (e.g., 'Brisk delivery with punchy consonants', 'Deliberate cadence with dramatic pauses')"
    )
    scene_directors_notes: str | None = Field(
        default=None,
        description="Specific directorial advice, accent nuances, or breathing instructions for this scene",
    )


class NarrationPlan(BaseModel):
    """Comprehensive directorial plan and voice casting system for video narration."""

    voice_name: str = Field(
        default="Zephyr",
        description="Prebuilt voice selected from supported Gemini TTS voices (e.g., Zephyr, Puck, Charon, Kore, Fenrir, Aoede, Enceladus, Sadaltager, Achird)",
    )
    audio_profile_name: str = Field(
        description="Grounded character persona name (e.g., 'Dr. Julian Vance', 'Elena Rostova')"
    )
    audio_profile_role: str = Field(
        description="Archetype and professional identity of the narrator (e.g., 'Enthusiastic Documentary Host', 'Knowledgeable Science Explorer')"
    )
    scene_environment: str = Field(
        description="Physical studio environment and atmosphere setting the stage and acoustic vibe"
    )
    directors_notes: str = Field(
        description="Core directorial performance notes detailing style, vocal smile, projection, accent, and articulation"
    )
    sample_context: str = Field(
        description="Contextual scene setup establishing how the voice talent naturally enters the scene"
    )
    scenes: list[SceneNarrationPlan] = Field(
        default_factory=list,
        description="Scene-by-scene enhanced narrations with inline audio tags and directorial guidance",
    )


class SceneAudio(BaseModel):
    """Synthesized speech audio clip metadata for a single scene."""

    scene_number: int = Field(description="Sequential index of the scene")
    audio_path: str = Field(
        description="Filesystem path to the generated WAV audio file"
    )
    duration_seconds: float = Field(
        default=0.0, description="Exact playback duration of the audio clip in seconds"
    )
    mime_type: str = Field(
        default="audio/wav", description="MIME type of the generated audio file"
    )
    file_size_bytes: int = Field(
        default=0, description="Size of the audio file in bytes"
    )


class NarrationStoryboard(BaseModel):
    """Collection of synthesized audio clips for all scenes in a video project."""

    topic: str = Field(description="The video topic")
    plan: NarrationPlan = Field(
        description="The approved narration plan and voice styling"
    )
    scenes_audio: list[SceneAudio] = Field(
        default_factory=list,
        description="Ordered list of generated scene audio clips",
    )
    sample_audio_path: str | None = Field(
        default=None,
        description="Filesystem path to the Scene 1 sample audio preview",
    )
    full_audio_path: str | None = Field(
        default=None,
        description="Filesystem path to the assembled full voiceover audio file",
    )
    total_duration_seconds: float = Field(
        default=0.0,
        description="Total duration of all scene voiceover clips combined in seconds",
    )


class ProjectSession(BaseModel):
    """Pipeline project session tracking state, research, script, narration, and animation results."""

    project_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique project identifier",
    )
    project_folder: str = Field(
        default="",
        description="Directory folder name for visual project asset storage",
    )
    user_id: int = Field(description="Telegram user ID")
    chat_id: int = Field(description="Telegram chat ID")
    topic: str = Field(description="User submitted topic or inquiry")
    state: WorkflowState = Field(
        default=WorkflowState.IDLE, description="Current workflow state"
    )

    @model_validator(mode="after")
    def _ensure_project_folder(self) -> Self:
        if not self.project_folder and self.topic:
            self.project_folder = compute_project_folder(self.topic, self.created_at)
        return self

    research_report: ResearchReport | None = Field(
        default=None, description="Researched report and subtopics"
    )
    script: Script | None = Field(
        default=None, description="Generated scene-by-scene narration script"
    )
    narration_plan: NarrationPlan | None = Field(
        default=None, description="Directorial narration plan and voice styling"
    )
    narration_storyboard: NarrationStoryboard | None = Field(
        default=None, description="Generated speech audio clips for all scenes"
    )
    style: AnimationStyle | None = Field(
        default=None, description="Selected animation visual style"
    )
    storyboard: AnimationStoryboard | None = Field(
        default=None, description="Generated animations for all scenes"
    )
    sample_frame_path: str | None = Field(
        default=None, description="Path to rendered sample frame image"
    )
    sample_audio_path: str | None = Field(
        default=None, description="Path to rendered Scene 1 sample audio file"
    )
    final_audio_path: str | None = Field(
        default=None, description="Path to assembled master voiceover audio file"
    )
    final_video_path: str | None = Field(
        default=None, description="Path to assembled final MP4 video"
    )
    captions_path: str | None = Field(
        default=None,
        description="Path to generated synchronized SRT subtitles file",
    )
    youtube_url: str | None = Field(
        default=None, description="Published YouTube video URL"
    )
    error_message: str | None = Field(
        default=None, description="Error message if workflow failed"
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ComponentUsage(BaseModel):
    """Resource and cost usage statistics for a specific pipeline component."""

    component: str = Field(description="Name of the pipeline component or agent")
    model_name: str = Field(
        default="", description="Primary model or tool utilized by this component"
    )
    prompt_tokens: int = Field(
        default=0, description="Total input/prompt tokens consumed"
    )
    output_tokens: int = Field(
        default=0, description="Total output/candidate tokens consumed"
    )
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    grounding_queries: int = Field(
        default=0, description="Number of Google Search Grounding queries executed"
    )
    audio_duration_seconds: float = Field(
        default=0.0, description="Total synthesized speech audio duration in seconds"
    )
    estimated_cost_usd: float = Field(
        default=0.0, description="Estimated total cost in USD for this component"
    )
    call_count: int = Field(
        default=0, description="Number of API/LLM calls made by this component"
    )


class ProjectUsageSummary(BaseModel):
    """Aggregated resource and cost usage summary for an entire video project session."""

    project_id: str = Field(description="Unique project identifier")
    total_cost_usd: float = Field(
        default=0.0, description="Total estimated cost in USD across all components"
    )
    total_prompt_tokens: int = Field(
        default=0, description="Total input prompt tokens across all components"
    )
    total_output_tokens: int = Field(
        default=0, description="Total output tokens across all components"
    )
    total_tokens: int = Field(
        default=0, description="Total tokens consumed across all components"
    )
    total_grounding_queries: int = Field(
        default=0, description="Total Google Search Grounding queries executed"
    )
    total_audio_duration_seconds: float = Field(
        default=0.0, description="Total synthesized audio duration in seconds"
    )
    total_calls: int = Field(
        default=0, description="Total API invocations across all components"
    )
    components: list[ComponentUsage] = Field(
        default_factory=list,
        description="Per-component breakdown of resource usage and cost",
    )


class YouTubePublishResult(BaseModel):
    """Result of publishing a video to YouTube."""

    video_id: str = Field(description="Unique YouTube video identifier")
    video_url: str = Field(
        description="Direct URL to the published YouTube video or Short"
    )
    title: str = Field(description="Published video title")
    privacy_status: str = Field(
        default="public", description="Video privacy status (public, unlisted, private)"
    )
    is_short: bool = Field(
        default=False,
        description="Whether the video was published as a vertical YouTube Short",
    )
    captions_uploaded: bool = Field(
        default=False,
        description="Whether synchronized SRT captions were uploaded to YouTube",
    )
