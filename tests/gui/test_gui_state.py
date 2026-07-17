import pytest

from canfd_offset_optimizer.gui.state import WorkflowState, WorkflowStateMachine


def test_full_success_and_cancellation_state_paths() -> None:
    machine = WorkflowStateMachine()
    machine.transition(WorkflowState.INSPECTING)
    machine.transition(WorkflowState.READY)
    machine.transition(WorkflowState.RUNNING)
    machine.transition(WorkflowState.SUCCEEDED)
    machine.transition(WorkflowState.RUNNING)
    machine.transition(WorkflowState.CANCELLING)
    machine.transition(WorkflowState.CANCELLED)
    assert machine.state is WorkflowState.CANCELLED


def test_invalid_duplicate_run_transition_is_rejected() -> None:
    machine = WorkflowStateMachine()
    with pytest.raises(RuntimeError, match="invalid GUI state transition"):
        machine.transition(WorkflowState.RUNNING)
