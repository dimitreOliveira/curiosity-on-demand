"""Unit tests for Pydantic models and schemas."""

from core.models import (
    AnimationType,
    ProjectSession,
    ResearchFinding,
    ResearchReport,
    VerificationResult,
    WorkflowState,
)


def test_research_finding_validation():
    """Test validation and confidence bounds for ResearchFinding."""
    finding = ResearchFinding(
        topic="Physics",
        claim="Light travels at ~300,000 km/s in vacuum.",
        detail="The speed of light is denoted as c.",
        confidence_score=0.99,
    )
    assert finding.confidence_score == 0.99
    assert finding.topic == "Physics"


def test_research_report_serialization(sample_research_report):
    """Test JSON round-trip serialization of ResearchReport."""
    json_data = sample_research_report.model_dump_json()
    reconstructed = ResearchReport.model_validate_json(json_data)

    assert reconstructed.topic == sample_research_report.topic
    assert len(reconstructed.findings) == len(sample_research_report.findings)
    assert reconstructed.sources[0].url == "https://example.com/quantum-basics"


def test_verification_result():
    """Test VerificationResult model logic."""
    ver = VerificationResult(
        is_complete=False,
        critique="Needs more historical background.",
        follow_up_queries=["Who proposed the quantum concept first?"],
        missing_aspects=["Max Planck 1900 discovery"],
        score=0.75,
    )
    assert not ver.is_complete
    assert len(ver.follow_up_queries) == 1
    assert ver.score == 0.75


def test_pitch_summary(sample_pitch_summary):
    """Test PitchSummary model attributes."""
    assert len(sample_pitch_summary.title_options) == 3
    assert sample_pitch_summary.estimated_scenes_count == 3
    assert "atoms in the universe" in sample_pitch_summary.hook


def test_scene_and_video_script(sample_video_script):
    """Test VideoScript structure, scenes, and shorts detection."""
    assert sample_video_script.title == "Why Quantum Computing Changes Everything"
    assert len(sample_video_script.scenes) == 2
    assert sample_video_script.highlighted_short_scene_ids == [1]

    scene_1 = sample_video_script.scenes[0]
    assert scene_1.scene_id == 1
    assert scene_1.is_suitable_for_short is True
    assert scene_1.visual_blueprint is not None
    assert scene_1.visual_blueprint.animation_type == AnimationType.FADE_SCALE


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
    assert session.script is None
    assert session.short_video_paths == []
