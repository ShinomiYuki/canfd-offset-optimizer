from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiOptimizationRequest,
    GuiOptimizationResult,
    InputInspectionRequest,
    InputSummary,
    ProgressCallback,
)
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.state import WorkflowState


class CountingBackend:
    def __init__(self, backend: MockBackend) -> None:
        self.backend = backend
        self.inspect_calls = 0
        self.optimize_calls = 0

    def inspect_input(
        self,
        request: InputInspectionRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> InputSummary:
        self.inspect_calls += 1
        return self.backend.inspect_input(request, progress_callback, cancellation_token)

    def optimize(
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> GuiOptimizationResult:
        self.optimize_calls += 1
        return self.backend.optimize(request, progress_callback, cancellation_token)


class InvalidResultBackend(CountingBackend):
    def optimize(  # type: ignore[override]
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> object:
        del request, progress_callback, cancellation_token
        self.optimize_calls += 1
        return {"incomplete": True}


class UnexpectedFailureBackend(CountingBackend):
    def optimize(
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> GuiOptimizationResult:
        del request, progress_callback, cancellation_token
        self.optimize_calls += 1
        raise RuntimeError("internal implementation detail")


def configure_window(
    window: MainWindow, inspection: InputInspectionRequest, output_directory: Path
) -> None:
    window.input_panel.dbc_row.set_path(inspection.dbc_path)
    window.input_panel.config_row.set_path(inspection.config_path)
    if inspection.arxml_directory is not None:
        window.input_panel.arxml_row.set_path(inspection.arxml_directory)
    window.input_panel.output_row.set_path(output_directory)


def inspect_until_ready(qtbot, window: MainWindow) -> None:
    window.start_inspection()
    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.READY,
        timeout=3_000,
    )


def test_network_loading_success_duplicate_guard_and_result_display(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    backend = CountingBackend(MockBackend(delay_seconds=0))
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    configure_window(window, gui_inputs, tmp_path / "user-output")

    inspect_until_ready(qtbot, window)

    assert backend.inspect_calls == 1
    assert window.settings_panel.network_combo.count() == 3
    assert window.settings_panel.network_combo.currentText() == "PT"
    assert window.settings_panel.network_combo.currentData() == "PT"
    assert window.progress_panel.run_button.isEnabled()

    window.start_optimization()
    assert window.workflow_state is WorkflowState.RUNNING
    assert window.task_active
    assert not window.input_panel.inspect_button.isEnabled()
    assert not window.settings_panel.isEnabled()
    assert not window.progress_panel.run_button.isEnabled()
    assert window.progress_panel.cancel_button.isEnabled()
    window.start_optimization()

    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.SUCCEEDED,
        timeout=3_000,
    )

    assert backend.optimize_calls == 1
    assert window.result is not None
    assert window.metrics_panel.weight_mode_label.text().endswith("（frame_time_us）")
    assert window.metrics_panel.attempts_label.text() == "20"
    assert window.metrics_panel.export_summary_button.isEnabled()
    assert window.assignment_table.model.rowCount() == 12
    assert window.assignment_table.export_button.isEnabled()
    assert window.load_chart.export_button.isEnabled()


def test_backend_failure_is_shown_without_raw_traceback_in_primary_message(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    dialogs: list[tuple[str, str, str | None]] = []
    window = MainWindow(
        MockBackend(delay_seconds=0, fail_optimization=True),
        dialog_handler=lambda title, message, details: dialogs.append((title, message, details)),
    )
    qtbot.addWidget(window)
    configure_window(window, gui_inputs, tmp_path / "user-output")
    inspect_until_ready(qtbot, window)

    window.start_optimization()
    qtbot.waitUntil(lambda: not window.task_active, timeout=3_000)

    assert window.workflow_state is WorkflowState.FAILED
    assert dialogs
    assert "模拟优化失败" in dialogs[-1][1]
    assert "Traceback" not in dialogs[-1][1]
    assert dialogs[-1][2] is not None


def test_invalid_backend_result_fails_and_result_warning_is_visible(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    dialogs: list[tuple[str, str, str | None]] = []
    invalid_window = MainWindow(
        InvalidResultBackend(MockBackend(delay_seconds=0)),
        dialog_handler=lambda title, message, details: dialogs.append((title, message, details)),
    )
    qtbot.addWidget(invalid_window)
    configure_window(invalid_window, gui_inputs, tmp_path / "invalid-output")
    inspect_until_ready(qtbot, invalid_window)
    invalid_window.start_optimization()
    qtbot.waitUntil(lambda: not invalid_window.task_active, timeout=3_000)
    assert invalid_window.workflow_state is WorkflowState.FAILED
    assert "结果缺失" in dialogs[-1][1]

    warning_window = MainWindow(
        MockBackend(delay_seconds=0, extra_warning="测试警告"),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(warning_window)
    configure_window(warning_window, gui_inputs, tmp_path / "warning-output")
    inspect_until_ready(qtbot, warning_window)
    warning_window.start_optimization()
    qtbot.waitUntil(
        lambda: not warning_window.task_active
        and warning_window.workflow_state is WorkflowState.SUCCEEDED,
        timeout=3_000,
    )
    assert "测试警告" in warning_window.metrics_panel.warning_label.text()
    assert "警告：测试警告" in warning_window.log_view.toPlainText()


def test_unexpected_backend_exception_uses_safe_summary_and_expandable_details(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    dialogs: list[tuple[str, str, str | None]] = []
    window = MainWindow(
        UnexpectedFailureBackend(MockBackend(delay_seconds=0)),
        dialog_handler=lambda title, message, details: dialogs.append((title, message, details)),
    )
    qtbot.addWidget(window)
    configure_window(window, gui_inputs, tmp_path / "user-output")
    inspect_until_ready(qtbot, window)

    window.start_optimization()
    qtbot.waitUntil(lambda: not window.task_active, timeout=3_000)

    assert window.workflow_state is WorkflowState.FAILED
    assert dialogs[-1][1] == "后台任务发生意外错误，请展开技术详情。"
    assert "internal implementation detail" not in dialogs[-1][1]
    assert dialogs[-1][2] is not None
    assert "RuntimeError: internal implementation detail" in dialogs[-1][2]
