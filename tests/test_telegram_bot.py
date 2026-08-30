"""Unit tests for TelegramBotService and iterative pipeline orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import EvaluationResult, WorkflowState
from services.telegram_bot import TelegramBotService, extract_target_duration


def test_extract_target_duration():
    """Test extracting video duration from topics."""
    assert (
        extract_target_duration("Explain quantum computing (5 min video)")
        == "5 minutes"
    )
    assert extract_target_duration("History of Rome in 15 minutes") == "15 minutes"
    assert extract_target_duration("Black holes 2m short") == "2 minutes"
    assert (
        extract_target_duration("How photosynthesis works", default_minutes=10)
        == "~10 minutes"
    )


@pytest.mark.asyncio
async def test_telegram_bot_authorization(mock_settings, memory_db):
    """Test TelegramBotService authorization check with user ID and username."""
    mock_settings.telegram_allowed_users = [999, "dimitreoliveira"]
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    assert bot_service._is_user_authorized(999) is True
    assert bot_service._is_user_authorized(None, username="dimitreoliveira") is True
    assert bot_service._is_user_authorized(None, username="@dimitreoliveira") is True
    assert bot_service._is_user_authorized(123) is False
    assert bot_service._is_user_authorized(123, username="otheruser") is False


@pytest.mark.asyncio
async def test_telegram_bot_build_application(mock_settings, memory_db):
    """Test TelegramBotService building PTB Application."""
    mock_settings.telegram_bot_token = "123456789:TEST_BOT_TOKEN_FOR_BUILDING"
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    app = await bot_service.build_application()
    assert app is not None
    assert bot_service.app is not None


@pytest.mark.asyncio
async def test_telegram_bot_run_research_pipeline_single_round(
    mock_settings, memory_db, sample_research_report
):
    """Test research pipeline completing in a single round when evaluator finds it sufficient."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    # Mock researcher agent
    bot_service.researcher.conduct_research = AsyncMock(
        return_value="Raw research notes on Quantum Computing."
    )

    # Mock evaluator agent returning is_sufficient=True
    eval_result = EvaluationResult(
        is_sufficient=True,
        feedback_for_researcher=None,
        report=sample_research_report,
    )
    bot_service.evaluator.evaluate_research = AsyncMock(return_value=eval_result)

    # Mock send_message on PTB app bot
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    # Create project session
    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing (5 min)"
    )

    # Run research pipeline
    await bot_service._run_research_pipeline(session.project_id)

    # Verify project state updated to COMPLETED
    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.COMPLETED
    assert updated.research_report is not None
    assert updated.research_report.topic == sample_research_report.topic

    # Researcher and evaluator called once
    assert bot_service.researcher.conduct_research.call_count == 1
    assert bot_service.evaluator.evaluate_research.call_count == 1
    assert mock_app.bot.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_telegram_bot_run_research_pipeline_multi_round(
    mock_settings, memory_db, sample_research_report
):
    """Test research pipeline performing multiple rounds guided by evaluator feedback."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    # Mock researcher agent returning progressive notes
    bot_service.researcher.conduct_research = AsyncMock(
        side_effect=[
            "Round 1 notes: Qubits overview.",
            "Round 2 notes: Detailed entanglement and Bell test experiments.",
        ]
    )

    # Mock evaluator: Round 1 insufficient, Round 2 sufficient
    eval_round_1 = EvaluationResult(
        is_sufficient=False,
        feedback_for_researcher="Need more details on Bell tests.",
        report=sample_research_report,
    )
    eval_round_2 = EvaluationResult(
        is_sufficient=True,
        feedback_for_researcher=None,
        report=sample_research_report,
    )
    bot_service.evaluator.evaluate_research = AsyncMock(
        side_effect=[eval_round_1, eval_round_2]
    )

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Physics"
    )

    await bot_service._run_research_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.COMPLETED

    assert bot_service.researcher.conduct_research.call_count == 2
    assert bot_service.evaluator.evaluate_research.call_count == 2
