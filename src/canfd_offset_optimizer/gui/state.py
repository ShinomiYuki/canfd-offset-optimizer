"""Pure workflow state machine for import, inspection and batch optimization."""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    IDLE = "idle"
    IMPORTING = "importing"
    INSPECTING = "inspecting"
    AWAITING_SENDER_SELECTION = "awaiting_sender_selection"
    INCOMPLETE = "incomplete"
    READY = "ready"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_RESTARTS = frozenset(
    {
        WorkflowState.IMPORTING,
        WorkflowState.AWAITING_SENDER_SELECTION,
        WorkflowState.INCOMPLETE,
        WorkflowState.READY,
        WorkflowState.RUNNING,
    }
)
_ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.IDLE: frozenset({WorkflowState.IMPORTING}),
    WorkflowState.IMPORTING: frozenset(
        {
            WorkflowState.INSPECTING,
            WorkflowState.CANCELLING,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.INSPECTING: frozenset(
        {
            WorkflowState.READY,
            WorkflowState.AWAITING_SENDER_SELECTION,
            WorkflowState.INCOMPLETE,
            WorkflowState.CANCELLING,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.AWAITING_SENDER_SELECTION: frozenset(
        {
            WorkflowState.IMPORTING,
            WorkflowState.READY,
            WorkflowState.INCOMPLETE,
        }
    ),
    WorkflowState.INCOMPLETE: frozenset(
        {
            WorkflowState.IMPORTING,
            WorkflowState.AWAITING_SENDER_SELECTION,
            WorkflowState.READY,
        }
    ),
    WorkflowState.READY: frozenset(
        {
            WorkflowState.IMPORTING,
            WorkflowState.AWAITING_SENDER_SELECTION,
            WorkflowState.INCOMPLETE,
            WorkflowState.RUNNING,
        }
    ),
    WorkflowState.RUNNING: frozenset(
        {
            WorkflowState.CANCELLING,
            WorkflowState.SUCCEEDED,
            WorkflowState.PARTIAL,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.CANCELLING: frozenset(
        {
            WorkflowState.SUCCEEDED,
            WorkflowState.PARTIAL,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.SUCCEEDED: _TERMINAL_RESTARTS,
    WorkflowState.PARTIAL: _TERMINAL_RESTARTS,
    WorkflowState.FAILED: _TERMINAL_RESTARTS,
    WorkflowState.CANCELLED: _TERMINAL_RESTARTS,
}


class WorkflowStateMachine:
    def __init__(self) -> None:
        self._state = WorkflowState.IDLE

    @property
    def state(self) -> WorkflowState:
        return self._state

    def can_transition(self, target: WorkflowState) -> bool:
        return target in _ALLOWED_TRANSITIONS[self._state]

    def transition(self, target: WorkflowState) -> None:
        if not self.can_transition(target):
            raise RuntimeError(
                f"invalid GUI state transition: {self._state.value} -> {target.value}"
            )
        self._state = target

    def reset(self) -> None:
        self._state = WorkflowState.IDLE
