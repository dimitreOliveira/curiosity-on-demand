"""Unit tests for DatabaseManager and PipelineStateMachine."""

import pytest

from core.models import WorkflowState
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine


@pytest.mark.asyncio
async def test_database_crud_lifecycle(
    memory_db,
    sample_research_report,
    sample_script,
    sample_narration_plan,
    sample_narration_storyboard,
    sample_animation_style,
    sample_storyboard,
):
    """Test full database lifecycle for creating and updating project state, research, script, narration, and animation."""
    # 1. Create project
    project = await memory_db.create_project(
        user_id=100, chat_id=200, topic="Origin of Language"
    )
    assert project.project_id is not None
    assert project.state == WorkflowState.IDLE
    assert project.topic == "Origin of Language"

    # 2. Get active project for chat
    active = await memory_db.get_active_project_for_chat(200)
    assert active is not None
    assert active.project_id == project.project_id

    # 3. Save research report
    updated_res = await memory_db.save_research_report(
        project.project_id, sample_research_report
    )
    assert updated_res is not None
    assert updated_res.research_report is not None
    assert updated_res.research_report.topic == sample_research_report.topic
    assert len(updated_res.research_report.sections) == 3

    # 4. Save script
    updated_script = await memory_db.save_script(project.project_id, sample_script)
    assert updated_script is not None
    assert updated_script.script is not None
    assert updated_script.script.topic == sample_script.topic

    # 5. Save narration plan
    updated_np = await memory_db.save_narration_plan(
        project.project_id,
        sample_narration_plan,
        sample_audio_path="/tmp/sample.wav",
    )
    assert updated_np is not None
    assert updated_np.narration_plan is not None
    assert updated_np.narration_plan.voice_name == "Zephyr"
    assert updated_np.sample_audio_path == "/tmp/sample.wav"

    # 6. Save narration storyboard
    updated_ns = await memory_db.save_narration_storyboard(
        project.project_id, sample_narration_storyboard
    )
    assert updated_ns is not None
    assert updated_ns.narration_storyboard is not None
    assert len(updated_ns.narration_storyboard.scenes_audio) == 3

    # 7. Save animation style
    updated_style = await memory_db.save_style(
        project.project_id,
        sample_animation_style,
        sample_frame_path="/tmp/sample.png",
    )
    assert updated_style is not None
    assert updated_style.style is not None
    assert updated_style.style.style_name == sample_animation_style.style_name
    assert updated_style.sample_frame_path == "/tmp/sample.png"

    # 8. Save storyboard
    updated_sb = await memory_db.save_storyboard(
        project.project_id,
        sample_storyboard,
        final_video_path="/tmp/final.mp4",
    )
    assert updated_sb is not None
    assert updated_sb.storyboard is not None
    assert len(updated_sb.storyboard.scenes) == 3
    assert updated_sb.final_video_path == "/tmp/final.mp4"

    # 9. Save YouTube URL
    updated_yt = await memory_db.save_youtube_url(
        project.project_id,
        "https://youtu.be/sample_yt_id",
    )
    assert updated_yt is not None
    assert updated_yt.youtube_url == "https://youtu.be/sample_yt_id"


@pytest.mark.asyncio
async def test_state_machine_valid_transitions(memory_db):
    """Test valid sequential state transitions through research, scripting, narration, animation, and YouTube publishing."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="Deep Sea Creatures"
    )

    # IDLE -> RESEARCHING
    p1 = await sm.transition(project.project_id, WorkflowState.RESEARCHING)
    assert p1.state == WorkflowState.RESEARCHING

    # RESEARCHING -> AWAITING_RESEARCH_APPROVAL
    p2 = await sm.transition(
        project.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL
    )
    assert p2.state == WorkflowState.AWAITING_RESEARCH_APPROVAL

    # AWAITING_RESEARCH_APPROVAL -> RESEARCHING (Feedback loop)
    p2_feedback = await sm.transition(project.project_id, WorkflowState.RESEARCHING)
    assert p2_feedback.state == WorkflowState.RESEARCHING

    # RESEARCHING -> AWAITING_RESEARCH_APPROVAL
    await sm.transition(project.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL)

    # AWAITING_RESEARCH_APPROVAL -> SCRIPTING (Approval)
    p3 = await sm.transition(project.project_id, WorkflowState.SCRIPTING)
    assert p3.state == WorkflowState.SCRIPTING

    # SCRIPTING -> AWAITING_SCRIPT_APPROVAL
    p4 = await sm.transition(project.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL)
    assert p4.state == WorkflowState.AWAITING_SCRIPT_APPROVAL

    # AWAITING_SCRIPT_APPROVAL -> SCRIPTING (Feedback loop)
    p4_feedback = await sm.transition(project.project_id, WorkflowState.SCRIPTING)
    assert p4_feedback.state == WorkflowState.SCRIPTING

    # SCRIPTING -> AWAITING_SCRIPT_APPROVAL
    await sm.transition(project.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL)

    # AWAITING_SCRIPT_APPROVAL -> NARRATING (Approval for TTS)
    p5_nar = await sm.transition(project.project_id, WorkflowState.NARRATING)
    assert p5_nar.state == WorkflowState.NARRATING

    # NARRATING -> AWAITING_NARRATION_APPROVAL
    p5_nar_app = await sm.transition(
        project.project_id, WorkflowState.AWAITING_NARRATION_APPROVAL
    )
    assert p5_nar_app.state == WorkflowState.AWAITING_NARRATION_APPROVAL

    # AWAITING_NARRATION_APPROVAL -> NARRATING (Feedback loop)
    p5_nar_fb = await sm.transition(project.project_id, WorkflowState.NARRATING)
    assert p5_nar_fb.state == WorkflowState.NARRATING

    # NARRATING -> AWAITING_NARRATION_APPROVAL
    await sm.transition(project.project_id, WorkflowState.AWAITING_NARRATION_APPROVAL)

    # AWAITING_NARRATION_APPROVAL -> STYLING (Approval)
    p5 = await sm.transition(project.project_id, WorkflowState.STYLING)
    assert p5.state == WorkflowState.STYLING

    # STYLING -> AWAITING_STYLE_APPROVAL
    p6 = await sm.transition(project.project_id, WorkflowState.AWAITING_STYLE_APPROVAL)
    assert p6.state == WorkflowState.AWAITING_STYLE_APPROVAL

    # AWAITING_STYLE_APPROVAL -> STYLING (Feedback loop)
    p6_feedback = await sm.transition(project.project_id, WorkflowState.STYLING)
    assert p6_feedback.state == WorkflowState.STYLING

    # STYLING -> AWAITING_STYLE_APPROVAL
    await sm.transition(project.project_id, WorkflowState.AWAITING_STYLE_APPROVAL)

    # AWAITING_STYLE_APPROVAL -> ANIMATING (Approval)
    p7 = await sm.transition(project.project_id, WorkflowState.ANIMATING)
    assert p7.state == WorkflowState.ANIMATING

    # ANIMATING -> AWAITING_PUBLISH_APPROVAL (Video ready, prompt for publish)
    p8 = await sm.transition(
        project.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL
    )
    assert p8.state == WorkflowState.AWAITING_PUBLISH_APPROVAL

    # AWAITING_PUBLISH_APPROVAL -> PUBLISHING (User approves publishing)
    p9 = await sm.transition(project.project_id, WorkflowState.PUBLISHING)
    assert p9.state == WorkflowState.PUBLISHING

    # PUBLISHING -> COMPLETED (Video live on YouTube)
    p10 = await sm.transition(project.project_id, WorkflowState.COMPLETED)
    assert p10.state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_state_machine_publish_skip_transition(memory_db):
    """Test skipping YouTube publishing transitions directly from AWAITING_PUBLISH_APPROVAL to COMPLETED."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="Skip Publish Test"
    )

    await sm.transition(project.project_id, WorkflowState.RESEARCHING)
    await sm.transition(project.project_id, WorkflowState.AWAITING_RESEARCH_APPROVAL)
    await sm.transition(project.project_id, WorkflowState.SCRIPTING)
    await sm.transition(project.project_id, WorkflowState.AWAITING_SCRIPT_APPROVAL)
    await sm.transition(project.project_id, WorkflowState.STYLING)
    await sm.transition(project.project_id, WorkflowState.AWAITING_STYLE_APPROVAL)
    await sm.transition(project.project_id, WorkflowState.ANIMATING)
    await sm.transition(project.project_id, WorkflowState.AWAITING_PUBLISH_APPROVAL)

    # Skip publishing
    p_comp = await sm.transition(project.project_id, WorkflowState.COMPLETED)
    assert p_comp.state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_state_machine_invalid_transition(memory_db):
    """Test that illegal state transitions raise InvalidStateTransitionError."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(user_id=1, chat_id=1, topic="Invalid Flow")

    # Attempt illegal transition: IDLE -> COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        await sm.transition(project.project_id, WorkflowState.COMPLETED)

    # Attempt illegal transition: IDLE -> SCRIPTING
    with pytest.raises(InvalidStateTransitionError):
        await sm.transition(project.project_id, WorkflowState.SCRIPTING)


@pytest.mark.asyncio
async def test_state_machine_listener_callback(memory_db):
    """Test that state transition listeners execute as expected."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="Listener Test"
    )

    callback_invoked = False
    received_session = None

    async def on_researching(session):
        nonlocal callback_invoked, received_session
        callback_invoked = True
        received_session = session

    sm.register_listener(WorkflowState.RESEARCHING, on_researching)

    await sm.transition(project.project_id, WorkflowState.RESEARCHING)

    assert callback_invoked is True
    assert received_session is not None
    assert received_session.state == WorkflowState.RESEARCHING


@pytest.mark.asyncio
async def test_project_folder_persistence_and_fallback(memory_db):
    """Test that project_folder is persisted in DB and legacy records fall back gracefully."""
    from core.database import ProjectRecord

    # 1. New project has project_folder persisted
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="The Dinossaurs eras"
    )
    assert project.project_folder.startswith("the_dinossaurs_eras_")

    fetched = await memory_db.get_project(project.project_id)
    assert fetched is not None
    assert fetched.project_folder == project.project_folder

    # 2. Legacy record with project_folder as None falls back gracefully
    async with memory_db.session_factory() as session:
        legacy_record = ProjectRecord(
            project_id="legacy_project_123",
            project_folder=None,
            user_id=1,
            chat_id=1,
            topic="Ancient Rome",
            state=WorkflowState.IDLE.value,
        )
        session.add(legacy_record)
        await session.commit()

    legacy_fetched = await memory_db.get_project("legacy_project_123")
    assert legacy_fetched is not None
    assert legacy_fetched.project_folder.startswith("ancient_rome_")
