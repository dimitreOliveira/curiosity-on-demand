"""Unit tests for TelegramBotService and interactive research & scripting orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Message

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
    """Test research pipeline transitioning to AWAITING_RESEARCH_APPROVAL on sufficient evaluation."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    bot_service.researcher.conduct_research = AsyncMock(
        return_value="Raw research notes on Quantum Computing."
    )

    eval_result = EvaluationResult(
        is_sufficient=True,
        feedback_for_researcher=None,
        report=sample_research_report,
    )
    bot_service.evaluator.evaluate_research = AsyncMock(return_value=eval_result)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing (5 min)"
    )

    await bot_service._run_research_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_RESEARCH_APPROVAL
    assert updated.research_report is not None
    assert updated.research_report.topic == sample_research_report.topic

    assert bot_service.researcher.conduct_research.call_count == 1
    assert bot_service.evaluator.evaluate_research.call_count == 1
    assert mock_app.bot.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_telegram_bot_run_research_pipeline_multi_round(
    mock_settings, memory_db, sample_research_report
):
    """Test research pipeline performing multiple rounds guided by evaluator feedback."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    bot_service.researcher.conduct_research = AsyncMock(
        side_effect=[
            "Round 1 notes: Qubits overview.",
            "Round 2 notes: Detailed entanglement and Bell test experiments.",
        ]
    )

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
    assert updated.state == WorkflowState.AWAITING_RESEARCH_APPROVAL

    assert bot_service.researcher.conduct_research.call_count == 2
    assert bot_service.evaluator.evaluate_research.call_count == 2


@pytest.mark.asyncio
async def test_telegram_bot_approve_research_callback(
    mock_settings, memory_db, sample_research_report, sample_script
):
    """Test clicking Approve Research callback button transitions to SCRIPTING and triggers script pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.script_writer.generate_script = AsyncMock(return_value=sample_script)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )

    # Mock Update and CallbackQuery
    update = MagicMock()
    query = MagicMock()
    query.data = f"approve_research:{session.project_id}"
    query.answer = AsyncMock()
    query.message = MagicMock(spec=Message)
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    await bot_service._handle_callback_query(update, MagicMock())

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()

    # Verify script pipeline was triggered directly or ran
    await bot_service._run_script_pipeline(session.project_id)
    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_SCRIPT_APPROVAL
    assert updated.script is not None


@pytest.mark.asyncio
async def test_telegram_bot_research_feedback_routing(
    mock_settings, memory_db, sample_research_report
):
    """Test text message while in AWAITING_RESEARCH_APPROVAL is routed as feedback."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_research_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "testuser"
    update.effective_chat.id = 456
    update.message.text = "Add more historical context about Einstein and Bohr"
    update.message.reply_text = AsyncMock()

    await bot_service._handle_message(update, MagicMock())

    update.message.reply_text.assert_called_once()
    assert "feedback received" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_telegram_bot_run_script_pipeline(
    mock_settings, memory_db, sample_research_report, sample_script
):
    """Test script pipeline generating script and transitioning to AWAITING_SCRIPT_APPROVAL."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.script_writer.generate_script = AsyncMock(return_value=sample_script)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing (5 min)"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )

    await bot_service._run_script_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_SCRIPT_APPROVAL
    assert updated.script is not None
    assert len(updated.script.scenes) == 3
    assert bot_service.script_writer.generate_script.call_count == 1
    assert mock_app.bot.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_telegram_bot_approve_script_callback(
    mock_settings, memory_db, sample_research_report, sample_script
):
    """Test clicking Approve Script callback triggers style pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_style_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )

    update = MagicMock()
    query = MagicMock()
    query.data = f"approve_script:{session.project_id}"
    query.answer = AsyncMock()
    query.message = MagicMock(spec=Message)
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    await bot_service._handle_callback_query(update, MagicMock())

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()
    assert "script approved" in query.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_telegram_bot_run_style_pipeline(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_scene_animation,
):
    """Test style pipeline generating style, rendering sample frame snapshot, and transitioning to AWAITING_STYLE_APPROVAL."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.planner.plan_style = AsyncMock(return_value=sample_animation_style)
    bot_service.animator.animate_scene = AsyncMock(return_value=sample_scene_animation)

    async def mock_render_frame(html_content, output_image_path, **kwargs):
        output_image_path.parent.mkdir(parents=True, exist_ok=True)
        output_image_path.write_bytes(b"\x89PNG\r\n\x1a\nFakePng")
        return output_image_path

    bot_service.renderer.render_sample_frame = AsyncMock(side_effect=mock_render_frame)

    mock_app = MagicMock()
    mock_app.bot.send_photo = AsyncMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )

    await bot_service._run_style_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_STYLE_APPROVAL
    assert updated.style is not None
    assert updated.style.style_name == sample_animation_style.style_name
    assert updated.sample_frame_path is not None

    assert bot_service.planner.plan_style.call_count == 1
    assert bot_service.animator.animate_scene.call_count == 1
    assert bot_service.renderer.render_sample_frame.call_count == 1
    assert mock_app.bot.send_photo.call_count == 1


@pytest.mark.asyncio
async def test_telegram_bot_style_feedback_routing(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
):
    """Test text message while in AWAITING_STYLE_APPROVAL is routed as style feedback."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_style_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_style(session.project_id, sample_animation_style)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.STYLING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_STYLE_APPROVAL
    )

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "testuser"
    update.effective_chat.id = 456
    update.message.text = "Make it darker with neon purple highlights"
    update.message.reply_text = AsyncMock()

    await bot_service._handle_message(update, MagicMock())

    update.message.reply_text.assert_called_once()
    assert (
        "style feedback received" in update.message.reply_text.call_args[0][0].lower()
    )


@pytest.mark.asyncio
async def test_telegram_bot_approve_style_callback(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
):
    """Test clicking Approve Style callback triggers full animation pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_full_animation_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_style(session.project_id, sample_animation_style)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.STYLING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_STYLE_APPROVAL
    )

    # Click approve_style button
    update = MagicMock()
    query = MagicMock()
    query.data = f"approve_style:{session.project_id}"
    query.answer = AsyncMock()
    query.message = MagicMock(spec=Message)
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    await bot_service._handle_callback_query(update, MagicMock())

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()
    assert (
        "animation style approved" in query.message.reply_text.call_args[0][0].lower()
    )


@pytest.mark.asyncio
async def test_telegram_bot_run_full_animation_pipeline(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_storyboard,
):
    """Test full animation pipeline rendering all scenes, assembling video, and delivering to Telegram."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneVideoBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    mock_app.bot.send_video = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_style(session.project_id, sample_animation_style)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.STYLING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_STYLE_APPROVAL
    )

    # Execute full animation pipeline
    await bot_service._run_full_animation_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.COMPLETED
    assert updated.storyboard is not None
    assert updated.final_video_path is not None

    assert bot_service.animator.animate_storyboard.call_count == 1
    assert bot_service.renderer.render_scene_video.call_count == len(
        sample_storyboard.scenes
    )
    assert bot_service.renderer.assemble_video.call_count == 1
    assert mock_app.bot.send_video.call_count == 1


@pytest.mark.asyncio
async def test_telegram_bot_script_feedback_routing(
    mock_settings, memory_db, sample_research_report, sample_script
):
    """Test text message while in AWAITING_SCRIPT_APPROVAL is routed as feedback."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_script_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.RESEARCHING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.SCRIPTING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL
    )

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "testuser"
    update.effective_chat.id = 456
    update.message.text = "Make scene 1 faster and punchier"
    update.message.reply_text = AsyncMock()

    await bot_service._handle_message(update, MagicMock())

    update.message.reply_text.assert_called_once()
    assert "feedback received" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_telegram_bot_send_research_results_summarized(
    mock_settings, memory_db, sample_research_report
):
    """Test that _send_research_results sends only the summary and not all section contents."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    await bot_service._send_research_results(
        chat_id=456, report=sample_research_report, project_id="proj-123"
    )

    # Should send exactly 1 concise message with the summary and inline button
    assert mock_app.bot.send_message.call_count == 1
    call_args = mock_app.bot.send_message.call_args[1]
    sent_text = call_args["text"]

    # Verify summary is present
    assert sample_research_report.summary in sent_text
    assert "Research Summary:" in sent_text
    assert call_args["reply_markup"] is not None

    # Verify individual section detailed contents are NOT included
    for section in sample_research_report.sections:
        assert section.content not in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_send_script_results_summarized(
    mock_settings, memory_db, sample_script
):
    """Test that _send_script_results sends only overview and scene summaries, without full narration."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    await bot_service._send_script_results(
        chat_id=456, script=sample_script, project_id="proj-123"
    )

    # Should send exactly 1 concise message with the overview, scene summaries, and inline button
    assert mock_app.bot.send_message.call_count == 1
    call_args = mock_app.bot.send_message.call_args[1]
    sent_text = call_args["text"]

    # Verify overview and scene titles/summaries are present
    assert sample_script.summary in sent_text
    assert "Video Script Summary:" in sent_text
    assert call_args["reply_markup"] is not None

    for scene in sample_script.scenes:
        assert f"Scene {scene.scene_number}: {scene.title}" in sent_text
        assert scene.summary in sent_text
        # Full narration and visual idea descriptions should NOT be sent
        assert scene.narration not in sent_text
        assert "Visual Idea:" not in sent_text
        if scene.description:
            assert scene.description not in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_send_style_results_summarized(
    mock_settings, memory_db, sample_animation_style, tmp_path
):
    """Test that _send_style_results sends visual style design and art direction without technical details."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_app.bot.send_photo = AsyncMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    sample_frame_path = tmp_path / "scene_1_sample.png"
    sample_frame_path.write_bytes(b"\x89PNG\r\n\x1a\nFakePng")

    await bot_service._send_style_results(
        chat_id=456,
        style=sample_animation_style,
        sample_frame_path=sample_frame_path,
        project_id="proj-123",
    )

    # Should send photo with caption
    assert mock_app.bot.send_photo.call_count == 1
    call_args = mock_app.bot.send_photo.call_args[1]
    caption = call_args["caption"]

    # Verify Visual Style Design and Art Direction are present
    assert f"Visual Style Design: {sample_animation_style.style_name}" in caption
    assert "Art Direction:" in caption
    assert sample_animation_style.visual_description in caption
    assert call_args["reply_markup"] is not None

    # Verify technical details are NOT included
    assert "Palette:" not in caption
    assert "Typography:" not in caption
    assert "Animation Guidelines:" not in caption
    assert sample_animation_style.animation_guidelines not in caption
