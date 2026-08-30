"""State machine managing video research pipeline transitions, validations, and events."""

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from core.database import DatabaseManager, get_db_manager
from core.models import ProjectSession, WorkflowState

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, current_state: WorkflowState, target_state: WorkflowState):
        super().__init__(
            f"Illegal state transition from {current_state.value} to {target_state.value}"
        )
        self.current_state = current_state
        self.target_state = target_state


class PipelineStateMachine:
    """State machine governing the video research workflow."""

    # Allowed transitions graph
    ALLOWED_TRANSITIONS: ClassVar[dict[WorkflowState, set[WorkflowState]]] = {
        WorkflowState.IDLE: {
            WorkflowState.RESEARCHING,
            WorkflowState.FAILED,
        },
        WorkflowState.RESEARCHING: {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
        },
        WorkflowState.COMPLETED: set(),  # Terminal state
        WorkflowState.FAILED: {
            WorkflowState.IDLE,
            WorkflowState.RESEARCHING,  # Allow retry
        },
    }

    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or get_db_manager()
        self._listeners: dict[
            WorkflowState, list[Callable[[ProjectSession], Awaitable[None]]]
        ] = {}

    def register_listener(
        self,
        state: WorkflowState,
        callback: Callable[[ProjectSession], Awaitable[None]],
    ) -> None:
        """Register an async callback invoked when entering a specific state."""
        if state not in self._listeners:
            self._listeners[state] = []
        self._listeners[state].append(callback)

    def can_transition(
        self, current_state: WorkflowState, target_state: WorkflowState
    ) -> bool:
        """Check if transition from current_state to target_state is permitted."""
        allowed = self.ALLOWED_TRANSITIONS.get(current_state, set())
        return target_state in allowed

    async def transition(
        self,
        project_id: str,
        target_state: WorkflowState,
        error_message: str | None = None,
    ) -> ProjectSession:
        """Perform a state transition, persist it in the database, and trigger registered listeners."""
        session = await self.db.get_project(project_id)
        if not session:
            raise ValueError(f"Project with ID '{project_id}' not found")

        current_state = session.state

        if not self.can_transition(current_state, target_state):
            raise InvalidStateTransitionError(current_state, target_state)

        logger.info(
            "Project %s transitioning state: %s -> %s",
            project_id,
            current_state.value,
            target_state.value,
        )

        updated_session = await self.db.update_project_state(
            project_id=project_id,
            state=target_state,
            error_message=error_message,
        )

        if not updated_session:
            raise RuntimeError(
                f"Failed to update project '{project_id}' state in database"
            )

        # Notify state listeners
        listeners = self._listeners.get(target_state, [])
        for callback in listeners:
            try:
                await callback(updated_session)
            except Exception:
                logger.exception(
                    "Error executing state listener for state %s",
                    target_state.value,
                )

        return updated_session
