"""Unit tests for Pydantic models and schemas."""

from core.models import (
    ProjectSession,
    ResearchReport,
    ResearchSection,
    WorkflowState,
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
        "STYLING",
        "AWAITING_STYLE_APPROVAL",
        "ANIMATING",
        "COMPLETED",
        "FAILED",
    }
    actual_states = {s.value for s in WorkflowState}
    assert expected_states == actual_states
