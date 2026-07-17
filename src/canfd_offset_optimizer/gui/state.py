"""Pure workflow state machine used by the GUI controller."""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    IDLE = "idle"
    INSPECTING = "inspecting"
    READY = "ready"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.IDLE: frozenset({WorkflowState.INSPECTING}),
    WorkflowState.INSPECTING: frozenset(
        {WorkflowState.READY, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.READY: frozenset({WorkflowState.INSPECTING, WorkflowState.RUNNING}),
    WorkflowState.RUNNING: frozenset(
        {
            WorkflowState.CANCELLING,
            WorkflowState.SUCCEEDED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.CANCELLING: frozenset(
        {WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.SUCCEEDED: frozenset(
        {WorkflowState.INSPECTING, WorkflowState.READY, WorkflowState.RUNNING}
    ),
    WorkflowState.FAILED: frozenset(
        {WorkflowState.INSPECTING, WorkflowState.READY, WorkflowState.RUNNING}
    ),
    WorkflowState.CANCELLED: frozenset(
        {WorkflowState.INSPECTING, WorkflowState.READY, WorkflowState.RUNNING}
    ),
}


class WorkflowStateMachine:
    """Reject invalid lifecycle transitions instead of silently corrupting UI state."""

    def __init__(self) -> None:
        self._state = WorkflowState.IDLE

    @property
    def state(self) -> WorkflowState:
        return self._state

    def can_transition(self, target: WorkflowState) -> bool:
        return target in _ALLOWED_TRANSITIONS[self._state]

    def transition(self, target: WorkflowState) -> None:
        if not self.can_transition(target):
            raise RuntimeError(f"invalid GUI state transition: {self._state.value} -> {target.value}")
        self._state = target
