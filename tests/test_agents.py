"""Unit tests for Gemini-powered agents using mocked API responses."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import BaseAgent
from agents.evaluator import EvaluatorAgent
from agents.researcher import ResearcherAgent
from agents.script_writer import (
    ScriptWriterAgent,
    calculate_scene_budget,
    parse_duration_to_seconds,
)
from core.models import EvaluationResult, ResearchReport, Script


@pytest.mark.asyncio
async def test_base_agent_generate_text(mock_settings):
    """Test BaseAgent text generation with mocked GenAI client."""
    agent = BaseAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.text = "Grounded research notes from Google Search."
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.generate_text("Research prompt")
    assert result == "Grounded research notes from Google Search."


@pytest.mark.asyncio
async def test_base_agent_generate_structured_direct(
    mock_settings, sample_research_report
):
    """Test BaseAgent structured generation returning parsed Pydantic object."""
    agent = BaseAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = sample_research_report
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.generate_structured(
        prompt="Research topic",
        response_schema=ResearchReport,
    )
    assert isinstance(result, ResearchReport)
    assert result.topic == sample_research_report.topic
    assert len(result.sections) == 3


@pytest.mark.asyncio
async def test_researcher_agent_initial(mock_settings):
    """Test ResearcherAgent conducting initial unconstrained search."""
    agent = ResearcherAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.text = (
        "Quantum computing harnesses qubits, superposition, and entanglement."
    )
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    raw_notes = await agent.conduct_research(
        topic="How Quantum Computers Work",
        target_duration="5 minutes",
    )
    assert isinstance(raw_notes, str)
    assert "superposition" in raw_notes.lower()
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_researcher_agent_guided(mock_settings):
    """Test ResearcherAgent conducting guided search with feedback."""
    agent = ResearcherAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.text = "Detailed explanation of quantum entanglement and Bell states."
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    raw_notes = await agent.conduct_research(
        topic="Quantum Computing",
        feedback="Explain Bell states and entanglement experiments.",
        previous_research="Basic qubits notes.",
        target_duration="10 minutes",
    )
    assert "entanglement" in raw_notes.lower()
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_evaluator_agent_insufficient(mock_settings, sample_research_report):
    """Test EvaluatorAgent returning insufficient result with feedback."""
    agent = EvaluatorAgent(settings=mock_settings)

    eval_result_mock = EvaluationResult(
        is_sufficient=False,
        feedback_for_researcher="Need more real-world applications and hardware architectures.",
        report=sample_research_report,
    )

    mock_resp = MagicMock()
    mock_resp.parsed = eval_result_mock
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.evaluate_research(
        topic="How Quantum Computers Work",
        accumulated_research="Raw quantum notes...",
        target_duration="10 minutes",
        iteration=1,
        max_iterations=3,
    )
    assert isinstance(result, EvaluationResult)
    assert result.is_sufficient is False
    assert result.feedback_for_researcher is not None
    assert "hardware architectures" in result.feedback_for_researcher
    assert result.report.topic == "How Quantum Computers Work"


@pytest.mark.asyncio
async def test_evaluator_agent_final_round_forces_sufficiency(
    mock_settings, sample_research_report
):
    """Test EvaluatorAgent forcing is_sufficient=True on final iteration."""
    agent = EvaluatorAgent(settings=mock_settings)

    eval_result_mock = EvaluationResult(
        is_sufficient=False,  # Even if LLM returned False
        feedback_for_researcher="Something missing",
        report=sample_research_report,
    )

    mock_resp = MagicMock()
    mock_resp.parsed = eval_result_mock
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.evaluate_research(
        topic="How Quantum Computers Work",
        accumulated_research="Raw quantum notes...",
        target_duration="10 minutes",
        iteration=3,
        max_iterations=3,
    )
    assert result.is_sufficient is True
    assert result.feedback_for_researcher is None


@pytest.mark.asyncio
async def test_script_writer_agent_initial(
    mock_settings, sample_research_report, sample_script
):
    """Test ScriptWriterAgent generating structured script from research report."""
    agent = ScriptWriterAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = sample_script
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    script = await agent.generate_script(
        topic="How Quantum Computers Work",
        research_report=sample_research_report,
        target_duration="5 minutes",
    )

    assert isinstance(script, Script)
    assert script.topic == "How Quantum Computers Work"
    assert len(script.scenes) == 3
    assert script.scenes[0].title == "The Light Switch Dilemma"
    assert "light switch" in script.scenes[0].narration.lower()
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_script_writer_agent_with_feedback(
    mock_settings, sample_research_report, sample_script
):
    """Test ScriptWriterAgent revising script incorporating previous script and user feedback."""
    agent = ScriptWriterAgent(settings=mock_settings)

    revised_script = sample_script.model_copy(deep=True)
    revised_script.scenes[0].title = "The Quantum Coin Toss"
    revised_script.scenes[0].narration = "Imagine flipping a coin that spins forever."

    mock_resp = MagicMock()
    mock_resp.parsed = revised_script
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    script = await agent.generate_script(
        topic="How Quantum Computers Work",
        research_report=sample_research_report,
        target_duration="5 minutes",
        feedback="Change the opening metaphor from a light switch to a spinning coin.",
        previous_script=sample_script,
    )

    assert isinstance(script, Script)
    assert script.scenes[0].title == "The Quantum Coin Toss"
    assert "coin" in script.scenes[0].narration.lower()
    agent.client.aio.models.generate_content.assert_called_once()


def test_parse_duration_to_seconds():
    """Test duration string parsing across various human and bot inputs."""
    assert parse_duration_to_seconds("2 min") == 120
    assert parse_duration_to_seconds("2 minutes") == 120
    assert parse_duration_to_seconds("5 minutes") == 300
    assert parse_duration_to_seconds("~10 minutes") == 600
    assert parse_duration_to_seconds("15m") == 900
    assert parse_duration_to_seconds("30 seconds") == 30
    assert parse_duration_to_seconds("45s") == 45
    assert parse_duration_to_seconds("90 sec") == 90
    assert parse_duration_to_seconds("3-minute") == 180
    assert parse_duration_to_seconds("3-min") == 180
    assert parse_duration_to_seconds("45-second") == 45
    assert parse_duration_to_seconds("60-sec") == 60
    assert parse_duration_to_seconds("1:30") == 90
    assert parse_duration_to_seconds("1m 30s") == 90
    assert parse_duration_to_seconds("1 min 30 sec") == 90
    assert parse_duration_to_seconds("0:45") == 45
    assert parse_duration_to_seconds("2:00") == 120
    assert parse_duration_to_seconds("unknown", default_seconds=300) == 300
    assert parse_duration_to_seconds("", default_seconds=600) == 600


def test_calculate_scene_budget():
    """Test dynamic scene budgeting scaling across different video durations."""
    # 1 min (60s) -> minimum 4 scenes
    min_s, max_s, avg_dur = calculate_scene_budget(60)
    assert min_s == 4
    assert max_s <= 5
    assert avg_dur <= 20

    # 2 min (120s) -> 5 to 7 scenes (~20s each)
    min_s, max_s, avg_dur = calculate_scene_budget(120)
    assert min_s == 5
    assert max_s == 7
    assert avg_dur == 20

    # 5 min (300s) -> 14 to 16 scenes (~20s each)
    min_s, max_s, avg_dur = calculate_scene_budget(300)
    assert min_s == 14
    assert max_s == 16
    assert avg_dur == 20

    # 10 min (600s) -> 29 to 30 scenes (~20s each)
    min_s, max_s, avg_dur = calculate_scene_budget(600)
    assert min_s == 29
    assert max_s == 30
    assert avg_dur == 20

    # 30 min (1800s) -> clamped to max_scenes=30
    min_s, max_s, avg_dur = calculate_scene_budget(1800)
    assert min_s == 29
    assert max_s == 30
    assert avg_dur >= 50
