"""Unit tests for Gemini-powered agents using mocked API responses."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import BaseAgent
from agents.researcher import ResearcherAgent
from agents.scriptwriter import ScriptWriterAgent
from agents.summarizer import SummarizerAgent
from agents.verifier import VerifierAgent
from core.models import (
    PitchSummary,
    ResearchReport,
    VerificationResult,
    VideoScript,
)


@pytest.mark.asyncio
async def test_base_agent_generate_text(mock_settings):
    """Test BaseAgent text generation with mocked GenAI client."""
    agent = BaseAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.text = "Hello from Gemini 3.7 Flash!"
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.generate_text("Test prompt")
    assert result == "Hello from Gemini 3.7 Flash!"


@pytest.mark.asyncio
async def test_base_agent_generate_structured_direct(
    mock_settings, sample_pitch_summary
):
    """Test BaseAgent structured generation when response.text has JSON markdown fences."""
    agent = BaseAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = f"```json\n{sample_pitch_summary.model_dump_json()}\n```"
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.generate_structured(
        prompt="Synthesize pitch",
        response_schema=PitchSummary,
    )
    assert isinstance(result, PitchSummary)
    assert result.topic == sample_pitch_summary.topic
    assert len(result.title_options) == 3


@pytest.mark.asyncio
async def test_researcher_agent(mock_settings, sample_research_report):
    """Test ResearcherAgent conducting grounded search and structuring output."""
    agent = ResearcherAgent(settings=mock_settings)

    # Step 1 response (grounded search)
    mock_search_resp = MagicMock()
    mock_search_resp.text = "Raw grounded text about Quantum Computing."
    mock_candidate = MagicMock()
    mock_grounding = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.web.title = "Quantum Physics Reference"
    mock_chunk.web.uri = "https://example.com/quantum"
    mock_grounding.grounding_chunks = [mock_chunk]
    mock_candidate.grounding_metadata = mock_grounding
    mock_search_resp.candidates = [mock_candidate]

    # Step 2 response (structured report)
    mock_struct_resp = MagicMock()
    mock_struct_resp.parsed = None
    mock_struct_resp.text = sample_research_report.model_dump_json()

    agent.client.aio.models.generate_content = AsyncMock(
        side_effect=[mock_search_resp, mock_struct_resp]
    )

    report = await agent.conduct_research(
        topic="How Quantum Computers Work", iteration=1
    )
    assert isinstance(report, ResearchReport)
    assert report.topic == "How Quantum Computers Work"
    assert len(report.findings) >= 2


@pytest.mark.asyncio
async def test_verifier_agent(mock_settings, sample_research_report):
    """Test VerifierAgent returning verification decision."""
    agent = VerifierAgent(settings=mock_settings)

    expected_result = VerificationResult(
        is_complete=True,
        critique="The research is detailed with solid experimental data.",
        follow_up_queries=[],
        missing_aspects=[],
        score=0.95,
    )

    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = expected_result.model_dump_json()
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    ver_result = await agent.verify_research(report=sample_research_report, iteration=1)
    assert isinstance(ver_result, VerificationResult)
    assert ver_result.is_complete is True
    assert ver_result.score == 0.95


@pytest.mark.asyncio
async def test_verifier_agent_max_iterations(mock_settings, sample_research_report):
    """Test that VerifierAgent forces is_complete=True when max iterations is hit."""
    agent = VerifierAgent(settings=mock_settings)

    # Incomplete result
    incomplete_result = VerificationResult(
        is_complete=False,
        critique="Still missing edge cases.",
        follow_up_queries=["More details on X?"],
        missing_aspects=["X"],
        score=0.6,
    )

    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = incomplete_result.model_dump_json()
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    # iteration 2 equals max_research_iterations in mock_settings
    ver_result = await agent.verify_research(report=sample_research_report, iteration=2)
    assert ver_result.is_complete is True
    assert "reached maximum research iterations" in ver_result.critique


@pytest.mark.asyncio
async def test_summarizer_agent(
    mock_settings, sample_research_report, sample_pitch_summary
):
    """Test SummarizerAgent generating pitch and revising with user feedback."""
    agent = SummarizerAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = sample_pitch_summary.model_dump_json()
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    pitch = await agent.create_pitch(
        report=sample_research_report,
        user_feedback="Make the hook more dramatic about cryptography.",
        previous_pitch=sample_pitch_summary,
    )
    assert isinstance(pitch, PitchSummary)
    assert pitch.revision_notes == "Make the hook more dramatic about cryptography."


@pytest.mark.asyncio
async def test_scriptwriter_agent(
    mock_settings, sample_pitch_summary, sample_research_report, sample_video_script
):
    """Test ScriptWriterAgent producing multi-scene VideoScript with SVG code."""
    agent = ScriptWriterAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = sample_video_script.model_dump_json()
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    script = await agent.generate_script(
        pitch=sample_pitch_summary,
        report=sample_research_report,
    )
    assert isinstance(script, VideoScript)
    assert len(script.scenes) == 2
    assert script.scenes[0].scene_id == 1
    assert script.scenes[1].scene_id == 2
    assert script.total_duration_seconds > 0
    assert len(script.highlighted_short_scene_ids) > 0
