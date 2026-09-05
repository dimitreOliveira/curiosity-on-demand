"""Unit tests for CostTracker, usage persistence, and cost report generation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import BaseAgent
from core.cost_tracker import (
    CostTracker,
    PipelineComponent,
    current_component,
    current_project_id,
    get_cost_tracker,
    track_component,
)
from core.models import ComponentUsage, ProjectUsageSummary


def test_cost_tracker_calculation():
    """Test cost calculation with various models, grounding queries, and audio durations."""
    tracker = CostTracker()

    # 1. Standard text model (Gemini 3.7 Flash: $0.75/1M prompt, $3.75/1M output)
    # 1,000 prompt tokens = $0.00075, 2,000 output tokens = $0.0075 -> $0.00825
    cost = tracker.calculate_cost(
        model_name="gemini-3.7-flash",
        prompt_tokens=1000,
        output_tokens=2000,
    )
    assert cost == pytest.approx(0.00825, rel=1e-4)

    # 2. Search Grounding query cost ($35 / 1k queries = $0.035 each)
    cost_with_search = tracker.calculate_cost(
        model_name="gemini-3.7-flash",
        prompt_tokens=1000,
        output_tokens=2000,
        grounding_queries=2,
    )
    assert cost_with_search == pytest.approx(0.00825 + 0.070, rel=1e-4)

    # 3. Gemini TTS audio model (pure token-based: $1.00/1M prompt, $20.00/1M output audio tokens)
    cost_tts = tracker.calculate_cost(
        model_name="gemini-3.1-flash-tts-preview",
        prompt_tokens=500,
        output_tokens=1500,
        audio_duration_seconds=10.0,
    )
    # 500 * 1.00/1M = 0.0005 + 1500 * 20.0/1M = 0.030 -> $0.0305
    expected_tts = 0.0005 + 0.030
    assert cost_tts == pytest.approx(expected_tts, rel=1e-4)


def test_track_component_context_manager():
    """Test setting and resetting tracking context variables."""
    assert current_project_id.get() is None
    assert current_component.get() is None

    with track_component("proj-123", PipelineComponent.RESEARCH):
        assert current_project_id.get() == "proj-123"
        assert current_component.get() == PipelineComponent.RESEARCH.value

        # Nested context override
        with track_component("proj-123", PipelineComponent.EVALUATION):
            assert current_component.get() == PipelineComponent.EVALUATION.value

        assert current_component.get() == PipelineComponent.RESEARCH.value

    assert current_project_id.get() is None
    assert current_component.get() is None


@pytest.mark.asyncio
async def test_in_memory_usage_recording_and_summary():
    """Test recording usage in-memory and generating project summary."""
    tracker = CostTracker()
    proj_id = "test-project-456"

    # Record Research
    await tracker.record_usage(
        project_id=proj_id,
        component=PipelineComponent.RESEARCH,
        model_name="gemini-3.7-flash",
        prompt_tokens=1500,
        output_tokens=800,
        grounding_queries=2,
    )

    # Record Script Writing
    await tracker.record_usage(
        project_id=proj_id,
        component=PipelineComponent.SCRIPT_WRITING,
        model_name="gemini-3.7-flash",
        prompt_tokens=2000,
        output_tokens=1200,
    )

    # Record Voice Synthesis
    await tracker.record_usage(
        project_id=proj_id,
        component=PipelineComponent.VOICE_SYNTHESIS,
        model_name="gemini-3.1-flash-tts-preview",
        prompt_tokens=600,
        output_tokens=2500,
        audio_duration_seconds=30.0,
    )

    summary = await tracker.get_project_summary(proj_id)
    assert summary.project_id == proj_id
    assert summary.total_prompt_tokens == 4100
    assert summary.total_output_tokens == 4500
    assert summary.total_tokens == 8600
    assert summary.total_grounding_queries == 2
    assert summary.total_audio_duration_seconds == 30.0
    assert summary.total_calls == 3
    assert len(summary.components) == 3
    assert summary.total_cost_usd > 0


@pytest.mark.asyncio
async def test_database_usage_lifecycle(memory_db):
    """Test database recording and summary querying via DatabaseManager."""
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="Test DB Usage"
    )
    p_id = project.project_id

    # Record multiple usage logs
    await memory_db.record_usage(
        project_id=p_id,
        component="Research & Grounding",
        model_name="gemini-3.7-flash",
        prompt_tokens=1000,
        output_tokens=500,
        grounding_queries=1,
        cost_usd=0.03545,
    )
    await memory_db.record_usage(
        project_id=p_id,
        component="Research & Grounding",
        model_name="gemini-3.7-flash",
        prompt_tokens=800,
        output_tokens=400,
        grounding_queries=1,
        cost_usd=0.03534,
    )
    await memory_db.record_usage(
        project_id=p_id,
        component="Scene Canvas Coding",
        model_name="gemini-3.7-flash",
        prompt_tokens=3000,
        output_tokens=5000,
        cost_usd=0.0023,
    )

    logs = await memory_db.get_project_usage(p_id)
    assert len(logs) == 3

    summary = await memory_db.get_project_usage_summary(p_id)
    assert summary.project_id == p_id
    assert summary.total_calls == 3
    assert summary.total_grounding_queries == 2
    assert summary.total_tokens == (1000 + 500 + 800 + 400 + 3000 + 5000)
    assert len(summary.components) == 2

    # Check component aggregation
    research_comp = next(
        c for c in summary.components if c.component == "Research & Grounding"
    )
    assert research_comp.call_count == 2
    assert research_comp.grounding_queries == 2
    assert research_comp.prompt_tokens == 1800


def test_telegram_report_formatting():
    """Test Markdown formatting for badges and detailed breakdown reports."""
    tracker = CostTracker()
    summary = ProjectUsageSummary(
        project_id="p-100",
        total_cost_usd=0.0784,
        total_prompt_tokens=15000,
        total_output_tokens=12000,
        total_tokens=27000,
        total_grounding_queries=2,
        total_audio_duration_seconds=42.5,
        total_calls=5,
        components=[
            ComponentUsage(
                component=PipelineComponent.RESEARCH.value,
                model_name="gemini-3.7-flash",
                prompt_tokens=2000,
                output_tokens=1000,
                total_tokens=3000,
                grounding_queries=2,
                estimated_cost_usd=0.0706,
                call_count=1,
            ),
            ComponentUsage(
                component=PipelineComponent.VOICE_SYNTHESIS.value,
                model_name="gemini-3.1-flash-tts-preview",
                prompt_tokens=1000,
                output_tokens=4000,
                total_tokens=5000,
                audio_duration_seconds=42.5,
                estimated_cost_usd=0.0701,
                call_count=4,
            ),
        ],
    )

    badge = tracker.format_short_badge(summary)
    assert "0.0784" in badge
    assert "27,000" in badge

    report = tracker.format_telegram_report(summary)
    assert "Resource & Cost Breakdown" in report
    assert "Research & Grounding" in report
    assert "Voice Synthesis (TTS)" in report
    assert "$0.0784" in report
    assert "42.5s audio" in report
    assert "2 searches" in report
    assert "Local compute" in report


@pytest.mark.asyncio
async def test_base_agent_records_usage(monkeypatch):
    """Test that BaseAgent._record_response_usage captures usage metadata from response."""
    agent = BaseAgent()

    mock_response = MagicMock()
    mock_response.usage_metadata = MagicMock(
        prompt_token_count=1200,
        candidates_token_count=600,
    )
    mock_candidate = MagicMock()
    mock_candidate.grounding_metadata = MagicMock(
        web_search_queries=["quantum entanglement", "bell theorem"]
    )
    mock_response.candidates = [mock_candidate]

    cost_tracker = get_cost_tracker()
    cost_tracker.record_usage = AsyncMock()

    with track_component("proj-xyz", PipelineComponent.RESEARCH):
        await agent._record_response_usage(
            response=mock_response,
            model_name="gemini-3.7-flash",
        )

    cost_tracker.record_usage.assert_awaited_once_with(
        project_id="proj-xyz",
        component=PipelineComponent.RESEARCH.value,
        model_name="gemini-3.7-flash",
        prompt_tokens=1200,
        output_tokens=600,
        grounding_queries=2,
        audio_duration_seconds=0.0,
    )
