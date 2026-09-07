"""Unit tests for TelegramBotService and interactive research & scripting orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update
from telegram.error import BadRequest, TimedOut

from core.models import EvaluationResult, WorkflowState
from services.telegram_bot import (
    TelegramBotService,
    extract_target_duration,
    split_message_chunks,
)


def test_extract_target_duration():
    """Test extracting video duration from topics."""
    assert (
        extract_target_duration(
            "The lifecycle o the Alie's Xenomorph (1:30 minute video)"
        )
        == "1m 30s"
    )
    assert extract_target_duration("Short animation 0:45 min") == "45 seconds"
    assert extract_target_duration("Epic saga 2:00") == "2 minutes"
    assert extract_target_duration("Space 1m 30s video") == "1m 30s"
    assert (
        extract_target_duration("Explain quantum computing (5 min video)")
        == "5 minutes"
    )
    assert extract_target_duration("History of Rome in 15 minutes") == "15 minutes"
    assert extract_target_duration("Black holes 2m short") == "2 minutes"
    assert (
        extract_target_duration(
            "A 3-minute video about the different chinese cuisine Traditions"
        )
        == "3 minutes"
    )
    assert extract_target_duration("A 3-min video about dinosaurs") == "3 minutes"
    assert extract_target_duration("Quick 45-second overview") == "45 seconds"
    assert extract_target_duration("Quick 30s recap") == "30 seconds"
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
    """Test clicking Approve Script callback triggers narration pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_narration_pipeline = AsyncMock()

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
    assert session.project_folder in updated.sample_frame_path

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

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=20.0)

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
    assert updated.state == WorkflowState.AWAITING_PUBLISH_APPROVAL
    assert updated.storyboard is not None
    assert updated.final_video_path is not None
    assert session.project_folder in updated.final_video_path

    assert bot_service.animator.animate_storyboard.call_count == 1
    assert bot_service.renderer.render_scene_video.call_count == len(
        sample_storyboard.scenes
    )
    assert mock_app.bot.send_video.call_count == 1
    send_video_kwargs = mock_app.bot.send_video.call_args[1]
    assert send_video_kwargs["supports_streaming"] is True
    assert (
        send_video_kwargs["read_timeout"]
        == mock_settings.telegram_upload_timeout_seconds
    )
    assert (
        send_video_kwargs["write_timeout"]
        == mock_settings.telegram_upload_timeout_seconds
    )
    caption_sent = send_video_kwargs["caption"]
    assert "Est. Cost:" in caption_sent
    assert "⏱️ *Duration:* 0m 20s" in caption_sent
    assert "(Preview)" not in caption_sent
    assert mock_app.bot.send_message.call_count >= 1
    # Check that a breakdown message was sent
    breakdown_calls = [
        call
        for call in mock_app.bot.send_message.call_args_list
        if "Resource & Cost Breakdown" in call[1].get("text", "")
    ]
    assert len(breakdown_calls) == 1


@pytest.mark.asyncio
async def test_full_animation_pipeline_large_video_sends_preview(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_storyboard,
    tmp_path,
):
    """Test that videos exceeding duration limit generate and send a 3-minute preview with proper notice."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneVideoBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"Sample1MinPreviewBytes")

    async def mock_preview(video_path, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"Sample1MinPreviewBytes")
        return output_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    # Total duration is 5 minutes 24 seconds (324s > 60s preview limit)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=324.0)
    bot_service.renderer.create_video_preview = AsyncMock(side_effect=mock_preview)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    mock_app.bot.send_video = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="History of Rome"
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

    await bot_service._run_full_animation_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_PUBLISH_APPROVAL

    # Verify create_video_preview was called with 60.0s max duration
    assert bot_service.renderer.create_video_preview.call_count == 1
    call_kwargs = bot_service.renderer.create_video_preview.call_args[1]
    assert call_kwargs["max_duration_seconds"] == 60.0

    # Verify preview video bytes were sent
    assert mock_app.bot.send_video.call_count == 1
    sent_video = mock_app.bot.send_video.call_args[1]["video"]
    assert sent_video == b"Sample1MinPreviewBytes"

    # Verify caption mentions preview duration, total duration, and informational notice
    caption = mock_app.bot.send_video.call_args[1]["caption"]
    assert "⏱️ *Duration:* 1m 00s (Preview) • Total: 5m 24s" in caption
    assert "Preview Notice" in caption
    assert "50MB" in caption
    assert "saved on the server" in caption


@pytest.mark.asyncio
async def test_full_animation_pipeline_send_failure_graceful_handling(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_storyboard,
):
    """Test that Telegram send failure does not cause illegal COMPLETED->FAILED transition."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneVideoBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=20.0)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    # Simulate network error on send_video
    mock_app.bot.send_video = AsyncMock(
        side_effect=Exception("Request Entity Too Large")
    )
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Black Holes"
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

    # Pipeline should complete without crashing with InvalidStateTransitionError
    await bot_service._run_full_animation_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    # Project state remains AWAITING_PUBLISH_APPROVAL because render and assembly succeeded
    assert updated.state == WorkflowState.AWAITING_PUBLISH_APPROVAL

    # Verify error message sent to user
    failure_msgs = [
        call[1]["text"]
        for call in mock_app.bot.send_message.call_args_list
        if "delivery via Telegram failed" in call[1].get("text", "")
    ]
    assert len(failure_msgs) == 1
    assert "Request Entity Too Large" in failure_msgs[0]
    assert "safely saved on the server" in failure_msgs[0]


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


@pytest.mark.asyncio
async def test_telegram_bot_run_narration_pipeline(
    mock_settings,
    memory_db,
    sample_script,
    sample_narration_plan,
    sample_scene_audio,
):
    """Test narration pipeline generating plan, sample audio, and transitioning to AWAITING_NARRATION_APPROVAL."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.narrator.determine_plan_and_sample = AsyncMock(
        return_value=(sample_narration_plan, sample_scene_audio)
    )
    bot_service._send_narration_results = AsyncMock()

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
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

    await bot_service._run_narration_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_NARRATION_APPROVAL
    assert updated.narration_plan is not None
    assert updated.narration_plan.voice_name == "Zephyr"
    assert updated.sample_audio_path == sample_scene_audio.audio_path

    bot_service.narrator.determine_plan_and_sample.assert_called_once()
    call_kwargs = bot_service.narrator.determine_plan_and_sample.call_args.kwargs
    assert session.project_folder in str(call_kwargs["output_dir"])
    bot_service._send_narration_results.assert_called_once_with(
        chat_id=456,
        plan=sample_narration_plan,
        sample_audio=sample_scene_audio,
        project_id=session.project_id,
    )


@pytest.mark.asyncio
async def test_telegram_bot_send_narration_results(
    mock_settings, memory_db, sample_narration_plan, sample_scene_audio
):
    """Test _send_narration_results sending voice message preview with approval buttons."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_app.bot.send_voice = AsyncMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    await bot_service._send_narration_results(
        chat_id=456,
        plan=sample_narration_plan,
        sample_audio=sample_scene_audio,
        project_id="proj-123",
    )

    assert mock_app.bot.send_voice.call_count == 1
    assert mock_app.bot.send_message.call_count >= 1

    call_args = mock_app.bot.send_voice.call_args[1]
    assert call_args["chat_id"] == 456
    assert "Scene 1 Voice Preview" in call_args["caption"]


@pytest.mark.asyncio
async def test_telegram_bot_approve_narration_callback(
    mock_settings, memory_db, sample_script, sample_narration_plan
):
    """Test clicking Approve Narration callback triggers style pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_style_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_narration_plan(session.project_id, sample_narration_plan)
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
        session.project_id, WorkflowState.NARRATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_NARRATION_APPROVAL
    )

    update = MagicMock()
    query = MagicMock()
    query.data = f"approve_narration:{session.project_id}"
    query.answer = AsyncMock()
    query.message = MagicMock(spec=Message)
    query.message.reply_text = AsyncMock()
    update.callback_query = query

    await bot_service._handle_callback_query(update, MagicMock())

    query.answer.assert_called_once()
    query.message.reply_text.assert_called_once()
    assert "approved" in query.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_telegram_bot_narration_feedback_flow(
    mock_settings, memory_db, sample_script, sample_narration_plan
):
    """Test user submitting feedback during AWAITING_NARRATION_APPROVAL restarts narration pipeline."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service._run_narration_pipeline = AsyncMock()

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum Computing"
    )
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_narration_plan(session.project_id, sample_narration_plan)
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
        session.project_id, WorkflowState.NARRATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_NARRATION_APPROVAL
    )

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "testuser"
    update.effective_chat.id = 456
    update.message = MagicMock(spec=Message)
    update.message.text = "Please make the tone more playful and use Puck voice"
    update.message.reply_text = AsyncMock()

    await bot_service._handle_message(update, MagicMock())

    update.message.reply_text.assert_called_once()
    assert (
        "narration feedback received"
        in update.message.reply_text.call_args[0][0].lower()
    )
    bot_service._run_narration_pipeline.assert_called_once_with(
        session.project_id,
        user_feedback="Please make the tone more playful and use Puck voice",
    )


@pytest.mark.asyncio
async def test_full_animation_pipeline_concurrent_narration_and_animation(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_storyboard,
    sample_narration_plan,
    sample_narration_storyboard,
):
    """Test that voice synthesis and scene animation run concurrently and apply configured concurrency."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)
    bot_service.narrator.generate_full_narration = AsyncMock(
        return_value=sample_narration_storyboard
    )

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneVideoBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=20.0)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    mock_app.bot.send_video = AsyncMock()
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Parallel Pipeline"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, sample_script)
    await memory_db.save_narration_plan(
        session.project_id, sample_narration_plan, "storage/sample.wav"
    )
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
        session.project_id, WorkflowState.NARRATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_NARRATION_APPROVAL
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.STYLING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_STYLE_APPROVAL
    )

    await bot_service._run_full_animation_pipeline(session.project_id)

    # Verify both agents were invoked with configured concurrency
    assert bot_service.narrator.generate_full_narration.call_count == 1
    assert (
        bot_service.narrator.generate_full_narration.call_args[1]["concurrency"]
        == mock_settings.tts_concurrency
    )
    assert bot_service.animator.animate_storyboard.call_count == 1
    assert (
        bot_service.animator.animate_storyboard.call_args[1]["concurrency"]
        == mock_settings.animation_concurrency
    )

    # Verify narration storyboard persisted
    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_PUBLISH_APPROVAL
    assert updated.narration_storyboard is not None


@pytest.mark.asyncio
async def test_telegram_bot_get_project_video_duration(mock_settings, memory_db):
    """Test TelegramBotService._get_project_video_duration precedence."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    # 1. Fallback to settings default (5 mins = 300s)
    session = await memory_db.create_project(
        user_id=1, chat_id=2, topic="Quantum Computing"
    )
    assert bot_service._get_project_video_duration(session) == 300.0

    # 2. Parsed from topic text
    session_topic = await memory_db.create_project(
        user_id=1, chat_id=2, topic="Quantum Computing (2 min video)"
    )
    assert bot_service._get_project_video_duration(session_topic) == 120.0

    session_sec = await memory_db.create_project(
        user_id=1, chat_id=2, topic="Black holes in 45 seconds"
    )
    assert bot_service._get_project_video_duration(session_sec) == 45.0

    # 3. Parsed from script scenes
    from core.models import Script, ScriptScene

    script = Script(
        topic="General Relativity",
        summary="A brief overview",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="S1",
                summary="Sum1",
                description="Desc1",
                duration_seconds=40,
                narration="Intro",
            ),
            ScriptScene(
                scene_number=2,
                title="S2",
                summary="Sum2",
                description="Desc2",
                duration_seconds=50,
                narration="Climax",
            ),
        ],
    )
    session.script = script
    assert bot_service._get_project_video_duration(session) == 90.0

    # 4. Narration storyboard total duration takes highest precedence
    from core.models import NarrationPlan, NarrationStoryboard

    session.narration_storyboard = NarrationStoryboard(
        topic="General Relativity",
        plan=NarrationPlan(
            audio_profile_name="Doc",
            audio_profile_role="Narrator",
            scene_environment="Studio",
            directors_notes="Clear",
            sample_context="Start",
        ),
        total_duration_seconds=88.5,
    )
    assert bot_service._get_project_video_duration(session) == 88.5


@pytest.mark.asyncio
async def test_telegram_bot_run_style_pipeline_vertical_format(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_animation_style,
    sample_scene_animation,
):
    """Test that videos with duration <= 2 min generate vertical 1080x1920 assets during styling."""
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

    from core.models import Script, ScriptScene

    short_script = Script(
        topic="Quantum in 60s",
        summary="A 60-second short video",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="Intro",
                summary="Hook",
                description="Metaphor",
                duration_seconds=30,
                narration="Look at quantum physics in 60 seconds.",
            ),
            ScriptScene(
                scene_number=2,
                title="Takeaway",
                summary="Outro",
                description="Climax",
                duration_seconds=30,
                narration="And that's superposition.",
            ),
        ],
    )

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quantum in 60s"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, short_script)

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

    assert bot_service.animator.animate_scene.call_count == 1
    anim_kwargs = bot_service.animator.animate_scene.call_args[1]
    assert anim_kwargs["is_vertical"] is True
    assert anim_kwargs["width"] == 1080
    assert anim_kwargs["height"] == 1920

    assert bot_service.renderer.render_sample_frame.call_count == 1
    render_kwargs = bot_service.renderer.render_sample_frame.call_args[1]
    assert render_kwargs["width"] == 1080
    assert render_kwargs["height"] == 1920

    assert mock_app.bot.send_photo.call_count == 1
    photo_caption = mock_app.bot.send_photo.call_args[1]["caption"]
    assert "Vertical 9:16 (1080x1920 • YouTube Shorts style)" in photo_caption


@pytest.mark.asyncio
async def test_telegram_bot_run_full_pipeline_vertical_format(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_animation_style,
    sample_storyboard,
):
    """Test that full pipeline for <= 2 min video renders and sends vertical 1080x1920 video."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=60.0)

    mock_app = MagicMock()
    mock_app.bot.send_video = AsyncMock()
    mock_app.bot.send_message = AsyncMock()
    bot_service.app = mock_app

    from core.models import Script, ScriptScene

    short_script = Script(
        topic="Quick Quantum (1 min)",
        summary="Short",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="S1",
                summary="Sum",
                description="Desc",
                duration_seconds=30,
                narration="Narr 1",
            ),
            ScriptScene(
                scene_number=2,
                title="S2",
                summary="Sum",
                description="Desc",
                duration_seconds=30,
                narration="Narr 2",
            ),
        ],
    )

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Quick Quantum (1 min)"
    )
    await memory_db.save_research_report(session.project_id, sample_research_report)
    await memory_db.save_script(session.project_id, short_script)
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

    await bot_service._run_full_animation_pipeline(session.project_id)

    # Check animate_storyboard called with vertical parameters
    assert bot_service.animator.animate_storyboard.call_count == 1
    storyboard_kwargs = bot_service.animator.animate_storyboard.call_args[1]
    assert storyboard_kwargs["is_vertical"] is True
    assert storyboard_kwargs["width"] == 1080
    assert storyboard_kwargs["height"] == 1920

    # Check send_video called with vertical dimensions and badge
    assert mock_app.bot.send_video.call_count == 1
    send_video_kwargs = mock_app.bot.send_video.call_args[1]
    assert send_video_kwargs["width"] == 1080
    assert send_video_kwargs["height"] == 1920
    assert "Vertical 9:16 (1080x1920 • Shorts)" in send_video_kwargs["caption"]


@pytest.mark.asyncio
async def test_telegram_bot_publish_youtube_flow(
    mock_settings,
    memory_db,
    tmp_path,
):
    """Test full YouTube publishing workflow from callback approval to live URL notification."""
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.app = mock_app

    # Create project and set up final video path
    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="How Photosynthesis Works"
    )
    video_file = tmp_path / "final_video.mp4"
    video_file.write_bytes(b"dummy mp4 video data")

    # Fast-forward to AWAITING_PUBLISH_APPROVAL
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
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.ANIMATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
    )

    # Attach video path to database record
    async with memory_db.session_factory() as db_session:
        from sqlalchemy import update

        from core.database import ProjectRecord

        await db_session.execute(
            update(ProjectRecord)
            .where(ProjectRecord.project_id == session.project_id)
            .values(final_video_path=str(video_file))
        )
        await db_session.commit()

    # 1. Test Callback Query "publish_youtube:"
    mock_query = MagicMock()
    mock_query.data = f"publish_youtube:{session.project_id}"
    mock_query.answer = AsyncMock()
    mock_query.message = MagicMock(spec=Message)
    mock_query.message.reply_text = AsyncMock()

    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query

    with patch.object(
        bot_service, "_run_youtube_publish_pipeline", new_callable=AsyncMock
    ) as mock_pipe:
        await bot_service._handle_callback_query(mock_update, MagicMock())
        mock_pipe.assert_called_once()

    mock_query.answer.assert_called_once()
    mock_query.message.reply_text.assert_called_once()
    assert "upload" in mock_query.message.reply_text.call_args[0][0].lower()

    # 2. Execute pipeline directly with mocked publisher
    from core.models import YouTubePublishResult

    bot_service.youtube_publisher.is_configured = MagicMock(return_value=True)
    bot_service.youtube_publisher.publish_video = AsyncMock(
        return_value=YouTubePublishResult(
            video_id="yt_12345",
            video_url="https://youtu.be/yt_12345",
            title="How Photosynthesis Works",
            privacy_status="public",
            is_short=False,
        )
    )

    await bot_service._run_youtube_publish_pipeline(session.project_id)

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.COMPLETED
    assert updated.youtube_url == "https://youtu.be/yt_12345"

    # Verify live URL message sent to user
    success_msgs = [
        call[1]["text"]
        for call in mock_app.bot.send_message.call_args_list
        if "live on YouTube" in call[1].get("text", "")
    ]
    assert len(success_msgs) == 1
    assert "https://youtu.be/yt_12345" in success_msgs[0]
    assert "How Photosynthesis Works" in success_msgs[0]


@pytest.mark.asyncio
async def test_telegram_bot_skip_publish_callback(
    mock_settings,
    memory_db,
):
    """Test clicking skip_publish transitions to COMPLETED without uploading."""
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Skip Publish"
    )

    # Fast-forward to AWAITING_PUBLISH_APPROVAL
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
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.ANIMATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
    )

    mock_query = AsyncMock()
    mock_query.data = f"skip_publish:{session.project_id}"
    mock_query.message = AsyncMock(spec=Message)

    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query

    await bot_service._handle_callback_query(mock_update, MagicMock())

    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.COMPLETED
    assert updated.youtube_url is None
    assert mock_query.message.reply_text.call_count == 1
    assert "Video generation completed" in mock_query.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_bot_publish_unconfigured_notice(
    mock_settings,
    memory_db,
    tmp_path,
):
    """Test that attempting to publish when unconfigured warns user with retry/skip options."""
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Unconfigured Publish"
    )
    video_file = tmp_path / "vid.mp4"
    video_file.write_bytes(b"data")

    # Fast-forward to AWAITING_PUBLISH_APPROVAL
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
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.ANIMATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
    )

    async with memory_db.session_factory() as db_session:
        from sqlalchemy import update

        from core.database import ProjectRecord

        await db_session.execute(
            update(ProjectRecord)
            .where(ProjectRecord.project_id == session.project_id)
            .values(final_video_path=str(video_file))
        )
        await db_session.commit()

    # Ensure publisher reports unconfigured
    bot_service.youtube_publisher.is_configured = MagicMock(return_value=False)

    await bot_service._run_youtube_publish_pipeline(session.project_id)

    # Verify notice sent
    warning_msgs = [
        call[1]["text"]
        for call in mock_app.bot.send_message.call_args_list
        if "YouTube publishing is not configured" in call[1].get("text", "")
    ]
    assert len(warning_msgs) == 1
    assert "YOUTUBE_CLIENT_ID" in warning_msgs[0]


@pytest.mark.asyncio
async def test_telegram_bot_text_during_awaiting_publish(
    mock_settings,
    memory_db,
):
    """Test text message received while waiting for publish approval prompts buttons."""
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="Publish Text Test"
    )
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
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.ANIMATING
    )
    await bot_service.state_machine.transition(
        session.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
    )

    mock_msg = AsyncMock(spec=Message)
    mock_msg.chat_id = 456
    mock_msg.from_user.id = 123
    mock_msg.from_user.username = "tester"
    mock_msg.text = "Can I publish it now?"

    mock_update = MagicMock(spec=Update)
    mock_update.message = mock_msg
    mock_update.effective_chat.id = 456
    mock_update.effective_user.id = 123
    mock_update.effective_user.username = "tester"

    await bot_service._handle_message(mock_update, MagicMock())

    assert mock_msg.reply_text.call_count == 1
    reply_text = mock_msg.reply_text.call_args[0][0]
    assert "Your video is ready!" in reply_text


@pytest.mark.asyncio
async def test_telegram_bot_setup_commands(mock_settings, memory_db):
    """Test setup_bot_commands successfully registers the 4 core bot commands."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_bot = AsyncMock()
    mock_app.bot = mock_bot
    bot_service.app = mock_app

    await bot_service.setup_bot_commands()

    mock_bot.set_my_commands.assert_called_once()
    registered_cmds = mock_bot.set_my_commands.call_args[0][0]
    cmd_names = [c.command for c in registered_cmds]
    assert cmd_names == ["start", "help", "status", "cancel"]


@pytest.mark.asyncio
async def test_telegram_bot_setup_commands_handles_error(mock_settings, memory_db):
    """Test setup_bot_commands gracefully handles TelegramError without raising."""
    from telegram.error import TelegramError

    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()
    mock_bot = AsyncMock()
    mock_bot.set_my_commands.side_effect = TelegramError("Connection failed")
    mock_app.bot = mock_bot
    bot_service.app = mock_app

    # Should not raise exception
    await bot_service.setup_bot_commands()


@pytest.mark.asyncio
async def test_telegram_bot_handle_start_authorized(mock_settings, memory_db):
    """Test /start sends the full pipeline welcome message to authorized users."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_update.effective_chat = mock_chat
    mock_update.effective_user.id = 123
    mock_update.effective_user.username = "tester"

    await bot_service._handle_start(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once()
    sent_text = mock_chat.send_message.call_args[0][0]
    assert "Welcome to Curiosity On Demand!" in sent_text
    assert "Grounded Research" in sent_text
    assert "Voice Direction" in sent_text
    assert "Visual Styling" in sent_text
    assert "YouTube Publishing" in sent_text
    assert "YouTube Shorts" in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_handle_start_unauthorized(mock_settings, memory_db):
    """Test /start rejects unauthorized users when allowed list is active."""
    mock_settings.telegram_allowed_users = [999]
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_update.effective_chat = mock_chat
    mock_update.effective_user.id = 123
    mock_update.effective_user.username = "unauthorized_user"

    await bot_service._handle_start(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once()
    sent_text = mock_chat.send_message.call_args[0][0]
    assert "not authorized" in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_handle_help(mock_settings, memory_db):
    """Test /help sends the detailed guide including review flow and duration tips."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_update.effective_chat = mock_chat

    await bot_service._handle_help(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once()
    sent_text = mock_chat.send_message.call_args[0][0]
    assert "Curiosity On Demand - Help & Guide" in sent_text
    assert "Human-in-the-Loop Review" in sent_text
    assert "/start" in sent_text
    assert "/status" in sent_text
    assert "/cancel" in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_handle_status_no_project(mock_settings, memory_db):
    """Test /status notifies user when no active project exists."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_chat.id = 9999
    mock_update.effective_chat = mock_chat

    await bot_service._handle_status(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once()
    sent_text = mock_chat.send_message.call_args[0][0]
    assert "No active project found" in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_handle_status_active_project(mock_settings, memory_db):
    """Test /status displays current stage and details of active project."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    session = await memory_db.create_project(
        user_id=123, chat_id=8888, topic="How do stars form?"
    )

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_chat.id = 8888
    mock_update.effective_chat = mock_chat

    await bot_service._handle_status(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once()
    sent_text = mock_chat.send_message.call_args[0][0]
    assert "Active Project Status" in sent_text
    assert "How do stars form?" in sent_text
    assert session.project_id[:8] in sent_text


@pytest.mark.asyncio
async def test_telegram_bot_handle_cancel_no_project(mock_settings, memory_db):
    """Test /cancel notifies user when there is no active project to cancel."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_chat.id = 9999
    mock_update.effective_chat = mock_chat

    await bot_service._handle_cancel(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once_with("No active project to cancel.")


@pytest.mark.asyncio
async def test_telegram_bot_handle_cancel_active_project(mock_settings, memory_db):
    """Test /cancel transitions active project to FAILED and confirms cancellation."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    session = await memory_db.create_project(
        user_id=123, chat_id=7777, topic="Black Holes (2 min)"
    )

    mock_update = MagicMock(spec=Update)
    mock_chat = AsyncMock()
    mock_chat.id = 7777
    mock_update.effective_chat = mock_chat

    await bot_service._handle_cancel(mock_update, MagicMock())

    mock_chat.send_message.assert_called_once_with("❌ Project cancelled.")
    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.FAILED
    assert updated.error_message == "Cancelled by user."


@pytest.mark.asyncio
async def test_telegram_bot_build_application_timeout_configuration(
    mock_settings, memory_db
):
    """Test that build_application configures connect, read, write, and media timeouts."""
    mock_settings.telegram_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    mock_settings.telegram_upload_timeout_seconds = 240.0
    mock_settings.telegram_request_timeout_seconds = 45.0
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    app = await bot_service.build_application()
    req = app.bot.request
    assert req._client_kwargs["timeout"].connect == 30.0
    assert req._client_kwargs["timeout"].read == 45.0
    assert req._client_kwargs["timeout"].write == 45.0
    assert req._media_write_timeout == 240.0


@pytest.mark.asyncio
async def test_full_animation_pipeline_send_video_retry_on_timeout_success(
    mock_settings,
    memory_db,
    sample_research_report,
    sample_script,
    sample_animation_style,
    sample_storyboard,
    tmp_path,
):
    """Test that if send_video times out on attempt 1, it retries and succeeds on attempt 2."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    async def mock_render_video(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeSceneVideoBytes")
        return output_video_path

    async def mock_assemble(scene_video_paths, output_video_path, *args, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(b"FakeMasterVideoBytes")
        return output_video_path

    bot_service.renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)
    bot_service.renderer.assemble_video = AsyncMock(side_effect=mock_assemble)
    bot_service.renderer.get_media_duration = AsyncMock(return_value=20.0)
    bot_service.animator.animate_storyboard = AsyncMock(return_value=sample_storyboard)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    # First call raises TimedOut, second call succeeds
    mock_app.bot.send_video = AsyncMock(
        side_effect=[TimedOut("Telegram read timeout"), MagicMock()]
    )
    bot_service.app = mock_app

    session = await memory_db.create_project(
        user_id=123, chat_id=456, topic="History of Rome"
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

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await bot_service._run_full_animation_pipeline(session.project_id)
        mock_sleep.assert_called_once_with(2.0)

    # Should have retried once: 2 calls total
    assert mock_app.bot.send_video.call_count == 2
    updated = await memory_db.get_project(session.project_id)
    assert updated is not None
    assert updated.state == WorkflowState.AWAITING_PUBLISH_APPROVAL


def test_split_message_chunks():
    """Test message chunking preserving paragraph and line boundaries."""
    # Under limit
    short_text = "Hello world!"
    assert split_message_chunks(short_text, max_chars=100) == ["Hello world!"]

    # Multi-paragraph exceeding limit
    para_text = "Para 1\n\nPara 2\n\nPara 3"
    chunks = split_message_chunks(para_text, max_chars=10)
    assert len(chunks) == 3
    assert chunks[0] == "Para 1"
    assert chunks[1] == "Para 2"
    assert chunks[2] == "Para 3"

    # Single paragraph with lines exceeding limit
    lines_text = "Line 1\nLine 2\nLine 3"
    chunks = split_message_chunks(lines_text, max_chars=14)
    assert len(chunks) == 2
    assert chunks[0] == "Line 1\nLine 2"
    assert chunks[1] == "Line 3"

    # Giant line fallback
    giant_text = "A" * 50
    chunks = split_message_chunks(giant_text, max_chars=20)
    assert len(chunks) == 3
    assert len(chunks[0]) == 20
    assert len(chunks[1]) == 20
    assert len(chunks[2]) == 10


@pytest.mark.asyncio
async def test_send_message_chunks_markdown_entity_parse_fallback(
    mock_settings, memory_db
):
    """Test that _send_message_chunks falls back to plain text if Markdown parsing fails."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    mock_app = MagicMock()

    # First call with parse_mode=MARKDOWN raises BadRequest (entity parse error)
    # Second call without parse_mode succeeds
    mock_app.bot.send_message = AsyncMock(
        side_effect=[
            BadRequest(
                "Can't parse entities: can't find end of the entity starting at byte offset 4135"
            ),
            MagicMock(),
        ]
    )
    bot_service.app = mock_app

    bad_markdown = "This has an unclosed *bold entity without ending."
    await bot_service._send_message_chunks(chat_id=1234, text=bad_markdown)

    assert mock_app.bot.send_message.call_count == 2
    # First call attempted with MARKDOWN
    first_call_kwargs = mock_app.bot.send_message.call_args_list[0][1]
    assert first_call_kwargs["parse_mode"] is not None

    # Second call fell back to plain text (parse_mode=None)
    second_call_kwargs = mock_app.bot.send_message.call_args_list[1][1]
    assert second_call_kwargs["parse_mode"] is None
    assert second_call_kwargs["text"] == bad_markdown


@pytest.mark.asyncio
async def test_get_project_video_duration_mm_ss_format(mock_settings, memory_db):
    """Test that _get_project_video_duration correctly resolves 1:30 to 90 seconds."""
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)
    session = await memory_db.create_project(
        user_id=123,
        chat_id=456,
        topic="The lifecycle o the Alie's Xenomorph (1:30 minute video)",
    )

    duration = bot_service._get_project_video_duration(session)
    assert duration == 90.0
