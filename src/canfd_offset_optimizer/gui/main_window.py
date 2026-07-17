"""Main desktop workflow composed only against OptimizationBackend."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .contracts import (
    CancellationToken,
    GuiOptimizationResult,
    InputSummary,
    OptimizationBackend,
    ProgressCallback,
    ProgressUpdate,
)
from .formatting import export_assignments_csv, export_summary_json
from .state import WorkflowState, WorkflowStateMachine
from .widgets.assignment_table import AssignmentTable
from .widgets.input_panel import InputPanel
from .widgets.load_chart import LoadChart
from .widgets.metrics_panel import MetricsPanel
from .widgets.progress_panel import ProgressPanel
from .widgets.settings_panel import SettingsPanel
from .workers import BackendOperation, BackendWorker, WorkerFailure

DialogHandler = Callable[[str, str, str | None], None]
CloseConfirmation = Callable[[], bool]


class MainWindow(QMainWindow):
    """Engineering-oriented one-window GUI with a mock-first backend boundary."""

    def __init__(
        self,
        backend: OptimizationBackend,
        *,
        dialog_handler: DialogHandler | None = None,
        close_confirmation: CloseConfirmation | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._dialog_handler = dialog_handler or self._default_dialog
        self._close_confirmation = close_confirmation or self._default_close_confirmation
        self._state = WorkflowStateMachine()
        self._input_summary: InputSummary | None = None
        self._result: GuiOptimizationResult | None = None
        self._inputs_dirty = True
        self._thread: QThread | None = None
        self._worker: BackendWorker | None = None
        self._token: CancellationToken | None = None
        self._task_kind: str | None = None
        self._task_started = 0.0
        self._close_pending = False

        self.setWindowTitle("CAN FD Offset Optimizer — Mock 后端")
        self.resize(1180, 760)
        self.input_panel = InputPanel()
        self.settings_panel = SettingsPanel()
        self.progress_panel = ProgressPanel()
        self.metrics_panel = MetricsPanel()
        self.assignment_table = AssignmentTable()
        self.load_chart = LoadChart()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("运行日志摘要")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.input_panel)
        left_layout.addWidget(self.settings_panel)
        left_layout.addWidget(self.progress_panel)
        left_layout.addStretch(1)
        tabs = QTabWidget()
        tabs.addTab(self.metrics_panel, "结果概览")
        tabs.addTab(self.assignment_table, "Offset 修改")
        tabs.addTab(self.load_chart, "负载曲线")
        tabs.addTab(self.log_view, "运行日志")
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.input_panel.source_changed.connect(self._mark_inputs_dirty)
        self.input_panel.output_changed.connect(self._refresh_controls)
        self.input_panel.inspect_requested.connect(self.start_inspection)
        self.progress_panel.run_requested.connect(self.start_optimization)
        self.progress_panel.cancel_requested.connect(self.request_cancel)
        self.assignment_table.export_requested.connect(self._choose_assignment_export)
        self.load_chart.export_requested.connect(self._choose_chart_export)
        self.metrics_panel.export_summary_button.clicked.connect(self._choose_summary_export)
        self.metrics_panel.open_output_button.clicked.connect(self.open_output_directory)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._refresh_controls()

    @property
    def workflow_state(self) -> WorkflowState:
        return self._state.state

    @property
    def result(self) -> GuiOptimizationResult | None:
        return self._result

    @property
    def task_active(self) -> bool:
        return self._thread is not None

    def start_inspection(self) -> None:
        if self.task_active:
            return
        request = self.input_panel.inspection_request()
        errors = request.validation_errors()
        if errors:
            self._show_error("输入检查失败", "\n".join(errors))
            return
        if not self._state.can_transition(WorkflowState.INSPECTING):
            return
        self._state.transition(WorkflowState.INSPECTING)
        self._append_log("开始读取输入；GUI 不直接解析核心模型。")

        def operation(callback: ProgressCallback, token: CancellationToken) -> object:
            return self._backend.inspect_input(request, callback, token)

        self._start_task("inspect", operation)

    def start_optimization(self) -> None:
        if self.task_active or self._input_summary is None or self._inputs_dirty:
            return
        try:
            request = self.settings_panel.build_request(
                self.input_panel.inspection_request(), self.input_panel.output_directory()
            )
        except (TypeError, ValueError) as exc:
            self._show_error("优化设置无效", str(exc))
            return
        errors = request.validation_errors()
        if errors:
            self._show_error("无法开始优化", "\n".join(errors))
            return
        if not self._state.can_transition(WorkflowState.RUNNING):
            return
        self._state.transition(WorkflowState.RUNNING)
        self._append_log(
            f"开始 Mock 优化：网段={request.network_name}，模式={request.mode.value}，"
            f"3-opt={'开启' if request.enable_triple_search else '关闭'}"
        )

        def operation(callback: ProgressCallback, token: CancellationToken) -> object:
            return self._backend.optimize(request, callback, token)

        self._start_task("optimize", operation)

    def request_cancel(self) -> None:
        if self._token is None or self._state.state is WorkflowState.CANCELLING:
            return
        if self._state.can_transition(WorkflowState.CANCELLING):
            self._state.transition(WorkflowState.CANCELLING)
        self._token.cancel()
        self._append_log("已请求协作式停止，等待当前安全检查点。")
        self._refresh_controls()

    def export_assignments_to(self, path: Path) -> Path:
        if self._result is None:
            raise RuntimeError("no optimization result to export")
        exported = export_assignments_csv(self._result, path)
        self._append_log(f"Offset CSV 已导出：{exported}")
        return exported

    def export_summary_to(self, path: Path) -> Path:
        if self._result is None:
            raise RuntimeError("no optimization result to export")
        exported = export_summary_json(self._result, path)
        self._append_log(f"运行摘要已导出：{exported}")
        return exported

    def export_chart_to(self, path: Path) -> Path:
        if self._result is None:
            raise RuntimeError("no optimization result to export")
        exported = self.load_chart.export_png(path)
        self._append_log(f"负载曲线已导出：{exported}")
        return exported

    def open_output_directory(self) -> None:
        path = self.input_panel.output_directory()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.task_active:
            if not self._close_confirmation():
                event.ignore()
                return
            self._close_pending = True
            self.request_cancel()
            event.ignore()
            return
        event.accept()

    def _start_task(self, kind: str, operation: BackendOperation) -> None:
        token = CancellationToken()
        thread = QThread(self)
        worker = BackendWorker(operation, token)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._token = token
        self._thread = thread
        self._worker = worker
        self._task_kind = kind
        self._task_started = perf_counter()
        self._elapsed_timer.start()
        self._refresh_controls()
        thread.start()

    def _on_progress(self, value: object) -> None:
        if not isinstance(value, ProgressUpdate):
            self._show_error("后端进度无效", "后端返回了未知进度对象。", repr(value))
            return
        self.progress_panel.update_progress(value)
        self._append_log(value.message)

    def _on_succeeded(self, value: object) -> None:
        if self._task_kind == "inspect":
            if not isinstance(value, InputSummary):
                self._on_failed(WorkerFailure("后端输入摘要缺失或类型无效。", repr(value)))
                return
            self._input_summary = value
            self.settings_panel.set_input_summary(value)
            self._inputs_dirty = False
            self._state.transition(WorkflowState.READY)
            for warning in value.warnings:
                self._append_log(f"警告：{warning}")
        else:
            if not isinstance(value, GuiOptimizationResult):
                self._on_failed(WorkerFailure("后端结果缺失或类型无效。", repr(value)))
                return
            self._result = value
            self.metrics_panel.set_result(value)
            self.assignment_table.set_result(value)
            self.load_chart.set_result(value)
            self._state.transition(WorkflowState.SUCCEEDED)
            self.progress_panel.finish_progress()
            for warning in value.warnings:
                self._append_log(f"警告：{warning}")
        self._refresh_controls()

    def _on_failed(self, value: object) -> None:
        failure = (
            value
            if isinstance(value, WorkerFailure)
            else WorkerFailure("后台任务返回了无效错误对象。", repr(value))
        )
        if self._state.can_transition(WorkflowState.FAILED):
            self._state.transition(WorkflowState.FAILED)
        self._append_log(f"错误：{failure.user_message}")
        self._show_error("任务失败", failure.user_message, failure.technical_details)
        self._refresh_controls()

    def _on_cancelled(self) -> None:
        if self._state.can_transition(WorkflowState.CANCELLED):
            self._state.transition(WorkflowState.CANCELLED)
        self._append_log("后台已在安全检查点停止。")
        self._refresh_controls()

    def _on_thread_finished(self) -> None:
        self._elapsed_timer.stop()
        self._thread = None
        self._worker = None
        self._token = None
        self._task_kind = None
        self._refresh_controls()
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def _mark_inputs_dirty(self) -> None:
        if self.task_active:
            return
        self._inputs_dirty = True
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        active = self.task_active or self._state.state in {
            WorkflowState.INSPECTING,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLING,
        }
        self.input_panel.set_task_locked(active)
        self.settings_panel.setEnabled(not active and self._input_summary is not None)
        output_ready = bool(self.input_panel.output_row.path_text)
        ready_to_run = (
            self._input_summary is not None
            and not self._inputs_dirty
            and output_ready
            and not active
        )
        self.progress_panel.set_state(self._state.state, ready_to_run=ready_to_run)

    def _refresh_elapsed(self) -> None:
        if self._task_started:
            self.progress_panel.elapsed_label.setText(
                f"{perf_counter() - self._task_started:.1f} s"
            )

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _show_error(self, title: str, message: str, technical_details: str | None = None) -> None:
        self._dialog_handler(title, message, technical_details)

    def _default_dialog(self, title: str, message: str, technical_details: str | None) -> None:
        box = QMessageBox(QMessageBox.Icon.Critical, title, message, parent=self)
        if technical_details:
            box.setDetailedText(technical_details)
        box.exec()

    def _default_close_confirmation(self) -> bool:
        answer = QMessageBox.question(
            self,
            "任务仍在运行",
            "是否请求停止后台任务并在安全检查点退出？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer is QMessageBox.StandardButton.Yes

    def _default_export_path(self, filename: str) -> str:
        return str(self.input_panel.output_directory() / filename)

    def _choose_assignment_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Offset CSV", self._default_export_path("offsets.csv"), "CSV (*.csv)"
        )
        if path:
            self.export_assignments_to(Path(path))

    def _choose_summary_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出运行摘要",
            self._default_export_path("summary.json"),
            "JSON (*.json)",
        )
        if path:
            self.export_summary_to(Path(path))

    def _choose_chart_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出负载曲线",
            self._default_export_path("load_curve.png"),
            "PNG (*.png)",
        )
        if path:
            self.export_chart_to(Path(path))
