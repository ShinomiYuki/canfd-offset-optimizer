from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.state import WorkflowState

from test_main_window import import_until_ready


def test_import_can_be_cancelled_cooperatively(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0.02),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window.import_sources((source_project,))
    window.request_cancel()
    assert window.workflow_state is WorkflowState.CANCELLING
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.CANCELLED,
        timeout=5_000,
    )
    assert window.inspection is None
    assert not window.progress_panel.cancel_button.isEnabled()


def test_batch_cancellation_retains_completed_rows_and_restores_controls(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0.005),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))
    window.start_optimization()
    qtbot.waitUntil(
        lambda: window.progress_panel.network_index_label.text() == "2/3",
        timeout=5_000,
    )
    window.request_cancel()
    assert window.workflow_state is WorkflowState.CANCELLING
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.CANCELLED,
        timeout=5_000,
    )
    assert window.result is not None
    assert window.result.succeeded_count >= 1
    assert window.summary_panel.model.rowCount() == 3
    assert window.input_panel.add_button.isEnabled()
    assert window.settings_panel.isEnabled()
    assert window.progress_panel.run_button.isEnabled()


def test_close_while_running_can_decline_then_confirm_safe_stop(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    decisions = iter((False, True))
    confirmations: list[bool] = []

    def confirm() -> bool:
        result = next(decisions)
        confirmations.append(result)
        return result

    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0.01),
        dialog_handler=lambda *_args: None,
        close_confirmation=confirm,
    )
    qtbot.addWidget(window)
    window.show()
    import_until_ready(qtbot, window, (source_project,))
    window.start_optimization()
    window.close()
    assert window.isVisible()
    assert window.workflow_state is WorkflowState.RUNNING
    window.close()
    assert window.workflow_state is WorkflowState.CANCELLING
    qtbot.waitUntil(lambda: not window.task_active and not window.isVisible(), timeout=5_000)
    assert confirmations == [False, True]
    assert window.workflow_state is WorkflowState.CANCELLED
