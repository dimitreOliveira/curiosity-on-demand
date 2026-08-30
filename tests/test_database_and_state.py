"""Unit tests for DatabaseManager and PipelineStateMachine."""

import pytest

from core.models import WorkflowState
from core.state_machine import InvalidStateTransitionError, PipelineStateMachine


@pytest.mark.asyncio
async def test_database_crud_lifecycle(memory_db, sample_research_report):
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
    assert len(updated.research_report.sections) == 3


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

    # RESEARCHING -> COMPLETED
    p2 = await sm.transition(project.project_id, WorkflowState.COMPLETED)
    assert p2.state == WorkflowState.COMPLETED


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
