"""Unit tests for DatabaseManager and PipelineStateMachine."""

import pytest

from core.models import WorkflowState
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine


@pytest.mark.asyncio
async def test_database_crud_lifecycle(
    memory_db, sample_research_report, sample_pitch_summary, sample_video_script
):
    """Test full database lifecycle for creating and updating project state."""
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
    updated = await memory_db.save_research_report(
        project.project_id, sample_research_report
    )
    assert updated is not None
    assert updated.research_report is not None
    assert updated.research_report.topic == sample_research_report.topic

    # 4. Save pitch summary
    updated = await memory_db.save_pitch_summary(
        project.project_id, sample_pitch_summary
    )
    assert updated is not None
    assert updated.pitch_summary is not None
    assert updated.pitch_summary.title_options == sample_pitch_summary.title_options

    # 5. Save script
    updated = await memory_db.save_video_script(project.project_id, sample_video_script)
    assert updated is not None
    assert updated.script is not None
    assert len(updated.script.scenes) == 2

    # 6. Save media outputs
    updated = await memory_db.save_media_outputs(
        project_id=project.project_id,
        final_video_path="/path/to/final.mp4",
        sample_clip_path="/path/to/sample.mp4",
        short_paths=["/path/to/short_1.mp4"],
        youtube_url="https://youtu.be/test1234",
    )
    assert updated is not None
    assert updated.final_video_path == "/path/to/final.mp4"
    assert updated.sample_clip_path == "/path/to/sample.mp4"
    assert updated.short_video_paths == ["/path/to/short_1.mp4"]
    assert updated.youtube_url == "https://youtu.be/test1234"


@pytest.mark.asyncio
async def test_state_machine_valid_transitions(memory_db):
    """Test valid sequential state transitions through the pipeline."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(
        user_id=1, chat_id=1, topic="Deep Sea Creatures"
    )

    # IDLE -> RESEARCHING
    p1 = await sm.transition(project.project_id, WorkflowState.RESEARCHING)
    assert p1.state == WorkflowState.RESEARCHING

    # RESEARCHING -> VERIFYING
    p2 = await sm.transition(project.project_id, WorkflowState.VERIFYING)
    assert p2.state == WorkflowState.VERIFYING

    # VERIFYING -> RESEARCHING (loop back)
    p3 = await sm.transition(project.project_id, WorkflowState.RESEARCHING)
    assert p3.state == WorkflowState.RESEARCHING

    # RESEARCHING -> VERIFYING
    p4 = await sm.transition(project.project_id, WorkflowState.VERIFYING)
    assert p4.state == WorkflowState.VERIFYING

    # VERIFYING -> AWAITING_APPROVAL
    p5 = await sm.transition(project.project_id, WorkflowState.AWAITING_APPROVAL)
    assert p5.state == WorkflowState.AWAITING_APPROVAL

    # AWAITING_APPROVAL -> AWAITING_APPROVAL (revision loop)
    p6 = await sm.transition(project.project_id, WorkflowState.AWAITING_APPROVAL)
    assert p6.state == WorkflowState.AWAITING_APPROVAL

    # AWAITING_APPROVAL -> GENERATING_SCRIPT
    p7 = await sm.transition(project.project_id, WorkflowState.GENERATING_SCRIPT)
    assert p7.state == WorkflowState.GENERATING_SCRIPT

    # GENERATING_SCRIPT -> GENERATING_SAMPLE
    p8 = await sm.transition(project.project_id, WorkflowState.GENERATING_SAMPLE)
    assert p8.state == WorkflowState.GENERATING_SAMPLE

    # GENERATING_SAMPLE -> GENERATING_ASSETS
    p9 = await sm.transition(project.project_id, WorkflowState.GENERATING_ASSETS)
    assert p9.state == WorkflowState.GENERATING_ASSETS

    # GENERATING_ASSETS -> ASSEMBLING
    p10 = await sm.transition(project.project_id, WorkflowState.ASSEMBLING)
    assert p10.state == WorkflowState.ASSEMBLING

    # ASSEMBLING -> UPLOADING
    p11 = await sm.transition(project.project_id, WorkflowState.UPLOADING)
    assert p11.state == WorkflowState.UPLOADING

    # UPLOADING -> COMPLETED
    p12 = await sm.transition(project.project_id, WorkflowState.COMPLETED)
    assert p12.state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_state_machine_invalid_transition(memory_db):
    """Test that illegal state transitions raise InvalidStateTransitionError."""
    sm = PipelineStateMachine(db=memory_db)
    project = await memory_db.create_project(user_id=1, chat_id=1, topic="Invalid Flow")

    # Attempt illegal transition: IDLE -> COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        await sm.transition(project.project_id, WorkflowState.COMPLETED)


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
