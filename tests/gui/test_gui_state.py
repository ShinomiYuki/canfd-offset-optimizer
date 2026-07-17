import pytest

from canfd_offset_optimizer.gui.state import WorkflowState, WorkflowStateMachine


@pytest.mark.parametrize(
    "terminal",
    [
        WorkflowState.SUCCEEDED,
        WorkflowState.PARTIAL,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    ],
)
def test_import_inspection_run_can_reach_every_terminal_state(
    terminal: WorkflowState,
) -> None:
    machine = WorkflowStateMachine()
    machine.transition(WorkflowState.IMPORTING)
    machine.transition(WorkflowState.INSPECTING)
    machine.transition(WorkflowState.READY)
    machine.transition(WorkflowState.RUNNING)
    if terminal is WorkflowState.CANCELLED:
        machine.transition(WorkflowState.CANCELLING)
    machine.transition(terminal)
    assert machine.state is terminal
    assert machine.can_transition(WorkflowState.IMPORTING)


def test_incomplete_project_must_be_reimported_before_run() -> None:
    machine = WorkflowStateMachine()
    machine.transition(WorkflowState.IMPORTING)
    machine.transition(WorkflowState.INSPECTING)
    machine.transition(WorkflowState.INCOMPLETE)
    assert not machine.can_transition(WorkflowState.RUNNING)
    assert machine.can_transition(WorkflowState.IMPORTING)
    with pytest.raises(RuntimeError, match="invalid GUI state transition"):
        machine.transition(WorkflowState.RUNNING)
