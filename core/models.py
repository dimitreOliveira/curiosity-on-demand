"""Core data models and schemas for Curiosity On Demand pipeline."""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


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
        description="Descriptive name of the visual style (e.g. 'Minimalist Vector Blueprint', 'Dark Neon Cybernetic', 'Vibrant Flat Infographic')"
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
        description="Typography and font stack for on-screen titles, equations, and annotations",
    )
    animation_guidelines: str = Field(
        description="Principles and motion design guidelines for SVG and Canvas animations in this style"
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
        description="Voiceover narration annotated with inline emotional and delivery audio tags (e.g., [excitedly], [whispers], [amazed], [gasp], [serious], [very fast], [sighs])"
    )
    tone: str = Field(
        description="Emotional vibe and vocal attitude for this scene (e.g., 'Intrigued and hushed whisper', 'Upbeat energetic revelation')"
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
    error_message: str | None = Field(
        default=None, description="Error message if workflow failed"
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
