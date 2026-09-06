"""Unit tests for Pydantic models and schemas."""

from datetime import UTC, datetime

from core.models import (
    ProjectSession,
    ResearchReport,
    ResearchSection,
    WorkflowState,
    compute_project_folder,
)


def test_research_section_validation():
    """Test validation for ResearchSection."""
    section = ResearchSection(
        topic="Physics",
        content="Light travels at ~300,000 km/s in vacuum.",
    )
    assert section.topic == "Physics"
    assert "300,000" in section.content


def test_research_report_serialization(sample_research_report):
    """Test JSON round-trip serialization of ResearchReport."""
    json_data = sample_research_report.model_dump_json()
    reconstructed = ResearchReport.model_validate_json(json_data)

    assert reconstructed.topic == sample_research_report.topic
    assert reconstructed.summary == sample_research_report.summary
    assert len(reconstructed.sections) == len(sample_research_report.sections)
    assert (
        reconstructed.sections[0].content == sample_research_report.sections[0].content
    )


def test_project_session_defaults():
    """Test ProjectSession initialization defaults."""
    session = ProjectSession(
        user_id=12345,
        chat_id=67890,
        topic="Black Holes",
    )
    assert session.state == WorkflowState.IDLE
    assert session.project_id is not None
    assert session.research_report is None
    assert session.error_message is None


def test_evaluation_result_validation(sample_research_report):
    """Test EvaluationResult serialization and field validation."""
    from core.models import EvaluationResult

    eval_result = EvaluationResult(
        is_sufficient=False,
        feedback_for_researcher="Needs more detail on quantum entanglement paradoxes.",
        report=sample_research_report,
    )
    assert eval_result.is_sufficient is False
    assert (
        eval_result.feedback_for_researcher
        == "Needs more detail on quantum entanglement paradoxes."
    )
    assert eval_result.report.topic == sample_research_report.topic

    json_str = eval_result.model_dump_json()
    reconstructed = EvaluationResult.model_validate_json(json_str)
    assert reconstructed.is_sufficient is False
    assert reconstructed.report.summary == sample_research_report.summary


def test_script_and_scenes_serialization(sample_script):
    """Test ScriptScene and Script validation and JSON serialization."""
    from core.models import Script, ScriptScene

    scene = ScriptScene(
        scene_number=1,
        title="Intro",
        summary="Hook",
        description="Visual introduction with spinning particles",
        narration="Hello world",
    )
    assert scene.scene_number == 1
    assert scene.title == "Intro"
    assert scene.description == "Visual introduction with spinning particles"
    assert scene.duration_seconds == 10

    json_str = sample_script.model_dump_json()
    reconstructed = Script.model_validate_json(json_str)

    assert reconstructed.topic == sample_script.topic
    assert reconstructed.summary == sample_script.summary
    assert len(reconstructed.scenes) == len(sample_script.scenes)
    assert reconstructed.scenes[0].description == sample_script.scenes[0].description
    assert (
        reconstructed.scenes[0].duration_seconds
        == sample_script.scenes[0].duration_seconds
    )
    assert reconstructed.scenes[0].narration == sample_script.scenes[0].narration


def test_animation_style_and_storyboard_serialization(
    sample_animation_style, sample_scene_animation, sample_storyboard
):
    """Test AnimationStyle, SceneAnimation, and AnimationStoryboard serialization."""
    from core.models import (
        AnimationStoryboard,
        AnimationStyle,
        SceneAnimation,
    )

    # Style serialization
    style_json = sample_animation_style.model_dump_json()
    reconstructed_style = AnimationStyle.model_validate_json(style_json)
    assert reconstructed_style.style_name == sample_animation_style.style_name
    assert reconstructed_style.color_palette == sample_animation_style.color_palette

    # Scene animation serialization
    scene_json = sample_scene_animation.model_dump_json()
    reconstructed_scene = SceneAnimation.model_validate_json(scene_json)
    assert reconstructed_scene.scene_number == 1
    assert "canvas" in reconstructed_scene.html_content

    # Storyboard serialization
    storyboard_json = sample_storyboard.model_dump_json()
    reconstructed_sb = AnimationStoryboard.model_validate_json(storyboard_json)
    assert reconstructed_sb.topic == sample_storyboard.topic
    assert len(reconstructed_sb.scenes) == 3
    assert reconstructed_sb.style.style_name == sample_animation_style.style_name


def test_workflow_states():
    """Test that all required workflow states are present."""
    expected_states = {
        "IDLE",
        "RESEARCHING",
        "AWAITING_RESEARCH_APPROVAL",
        "SCRIPTING",
        "AWAITING_SCRIPT_APPROVAL",
        "NARRATING",
        "AWAITING_NARRATION_APPROVAL",
        "STYLING",
        "AWAITING_STYLE_APPROVAL",
        "ANIMATING",
        "COMPLETED",
        "FAILED",
    }
    actual_states = {s.value for s in WorkflowState}
    assert expected_states == actual_states


def test_narration_models_serialization(
    sample_narration_plan, sample_scene_audio, sample_narration_storyboard
):
    """Test NarrationPlan, SceneAudio, and NarrationStoryboard serialization."""
    from core.models import NarrationPlan, NarrationStoryboard, SceneAudio

    # Plan serialization
    plan_json = sample_narration_plan.model_dump_json()
    reconstructed_plan = NarrationPlan.model_validate_json(plan_json)
    assert reconstructed_plan.voice_name == "Zephyr"
    assert len(reconstructed_plan.scenes) == 3
    assert reconstructed_plan.scenes[0].title == "The Light Switch Dilemma"

    # Audio serialization
    audio_json = sample_scene_audio.model_dump_json()
    reconstructed_audio = SceneAudio.model_validate_json(audio_json)
    assert reconstructed_audio.scene_number == 1
    assert reconstructed_audio.duration_seconds == 1.0

    # Storyboard serialization
    sb_json = sample_narration_storyboard.model_dump_json()
    reconstructed_sb = NarrationStoryboard.model_validate_json(sb_json)
    assert reconstructed_sb.topic == sample_narration_storyboard.topic
    assert len(reconstructed_sb.scenes_audio) == 3


def test_compute_project_folder():
    """Test compute_project_folder logic for slugification, formatting, and fallbacks."""
    fixed_dt = datetime(2026, 9, 5, 20, 15, 30, tzinfo=UTC)

    # Standard topic
    folder = compute_project_folder("The Dinossaurs eras", fixed_dt)
    assert folder == "the_dinossaurs_eras_20260905_201530"

    # Special characters and punctuation
    folder_special = compute_project_folder("Why the sky is blue? (Part 1!)", fixed_dt)
    assert folder_special == "why_the_sky_is_blue_part_1_20260905_201530"

    # Non-alphanumeric fallback
    folder_fallback = compute_project_folder("!!!???---", fixed_dt)
    assert folder_fallback == "project_20260905_201530"

    # ISO string timestamp input
    folder_iso = compute_project_folder("Quantum Physics", "2026-09-05T20:15:30+00:00")
    assert folder_iso == "quantum_physics_20260905_201530"

    # Default timestamp uses current time
    folder_now = compute_project_folder("Black Holes")
    assert folder_now.startswith("black_holes_")


def test_project_session_project_folder():
    """Test that ProjectSession automatically sets project_folder and preserves custom value."""
    session = ProjectSession(
        user_id=1,
        chat_id=2,
        topic="The Cthulhu mythos",
    )
    assert session.project_folder.startswith("the_cthulhu_mythos_")

    custom_session = ProjectSession(
        user_id=1,
        chat_id=2,
        topic="The Cthulhu mythos",
        project_folder="custom_folder_name",
    )
    assert custom_session.project_folder == "custom_folder_name"


def test_settings_vertical_video_resolution(mock_settings):
    """Test Settings.is_vertical_video and Settings.get_video_dimensions."""
    # Duration <= 120s should trigger vertical (YouTube Shorts style)
    assert mock_settings.is_vertical_video(30.0) is True
    assert mock_settings.is_vertical_video(60.0) is True
    assert mock_settings.is_vertical_video(120.0) is True
    assert mock_settings.get_video_dimensions(duration_seconds=60.0) == (720, 1280)
    assert mock_settings.get_video_dimensions(duration_seconds=120.0) == (720, 1280)

    # Duration > 120s should use standard horizontal widescreen
    assert mock_settings.is_vertical_video(120.1) is False
    assert mock_settings.is_vertical_video(300.0) is False
    assert mock_settings.get_video_dimensions(duration_seconds=121.0) == (1280, 720)
    assert mock_settings.get_video_dimensions(duration_seconds=300.0) == (1280, 720)

    # Non-positive or None duration should fallback to horizontal defaults
    assert mock_settings.is_vertical_video(0.0) is False
    assert mock_settings.is_vertical_video(-10.0) is False
    assert mock_settings.is_vertical_video(None) is False
    assert mock_settings.get_video_dimensions(duration_seconds=0.0) == (1280, 720)
    assert mock_settings.get_video_dimensions(duration_seconds=None) == (1280, 720)

    # Explicit is_vertical flag overrides duration
    assert mock_settings.get_video_dimensions(is_vertical=True) == (720, 1280)
    assert mock_settings.get_video_dimensions(is_vertical=False) == (1280, 720)
    assert mock_settings.get_video_dimensions(
        duration_seconds=600.0, is_vertical=True
    ) == (720, 1280)
    assert mock_settings.get_video_dimensions(
        duration_seconds=30.0, is_vertical=False
    ) == (1280, 720)
