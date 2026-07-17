from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import InputInspectionRequest
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.state import WorkflowState

from test_main_window import configure_window, inspect_until_ready


def test_inspection_can_be_cancelled_before_networks_are_loaded(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    window = MainWindow(MockBackend(delay_seconds=0.02), dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    configure_window(window, gui_inputs, tmp_path / "user-output")

    window.start_inspection()
    window.request_cancel()
    assert window.workflow_state is WorkflowState.CANCELLING
    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.CANCELLED,
        timeout=3_000,
    )
    assert window.settings_panel.network_combo.count() == 0


def test_user_cancellation_is_cooperative_and_restores_controls(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    window = MainWindow(MockBackend(delay_seconds=0.01), dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    configure_window(window, gui_inputs, tmp_path / "user-output")
    inspect_until_ready(qtbot, window)

    window.start_optimization()
    window.request_cancel()
    assert window.workflow_state is WorkflowState.CANCELLING
    assert not window.progress_panel.cancel_button.isEnabled()
    assert "等待当前安全检查点" in window.log_view.toPlainText()

    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.CANCELLED,
        timeout=3_000,
    )
    assert window.input_panel.inspect_button.isEnabled()
    assert window.settings_panel.isEnabled()
    assert window.progress_panel.run_button.isEnabled()


def test_close_while_running_can_decline_then_confirm_cooperative_stop(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    decisions = iter((False, True))
    confirmations: list[bool] = []

    def confirm() -> bool:
        result = next(decisions)
        confirmations.append(result)
        return result

    window = MainWindow(
        MockBackend(delay_seconds=0.02),
        dialog_handler=lambda *_args: None,
        close_confirmation=confirm,
    )
    qtbot.addWidget(window)
    window.show()
    configure_window(window, gui_inputs, tmp_path / "user-output")
    inspect_until_ready(qtbot, window)
    window.start_optimization()

    window.close()
    assert window.isVisible()
    assert window.workflow_state is WorkflowState.RUNNING

    window.close()
    assert window.workflow_state is WorkflowState.CANCELLING
    qtbot.waitUntil(lambda: not window.task_active and not window.isVisible(), timeout=3_000)

    assert confirmations == [False, True]
    assert window.workflow_state is WorkflowState.CANCELLED
