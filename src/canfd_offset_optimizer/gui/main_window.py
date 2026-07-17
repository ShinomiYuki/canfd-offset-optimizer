"""Workspace-oriented all-network desktop workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .contracts import (
    BackendAvailability,
    BatchOptimizationResult,
    BatchRunStatus,
    CancellationToken,
    GuiOptimizationResult,
    ImportSession,
    NetworkBatchResult,
    OptimizationBackend,
    ProgressCallback,
    ProgressUpdate,
    WorkspaceInspection,
)
from .formatting import export_assignments_csv
from .state import WorkflowState, WorkflowStateMachine
from .widgets.assignment_table import AssignmentTable
from .widgets.input_panel import InputPanel
from .widgets.load_chart import LoadChart
from .widgets.load_heatmap import LoadHeatmap
from .widgets.metrics_panel import BatchSummaryPanel
from .widgets.progress_panel import ProgressPanel
from .widgets.quick_start_page import QuickStartPage
from .widgets.settings_panel import SettingsPanel
from .workers import BackendOperation, BackendWorker, WorkerFailure

DialogHandler = Callable[[str, str, str | None], None]
CloseConfirmation = Callable[[], bool]
OpenDirectoryHandler = Callable[[Path], bool]


class MainWindow(QMainWindow):
    """Import one project workspace and optimize every discovered network."""

    def __init__(
        self,
        backend: OptimizationBackend,
        *,
        dialog_handler: DialogHandler | None = None,
        close_confirmation: CloseConfirmation | None = None,
        open_directory_handler: OpenDirectoryHandler | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._backend_availability = getattr(
            backend,
            "availability",
            BackendAvailability(True, type(backend).__name__),
        )
        self._dialog_handler = dialog_handler or self._default_dialog
        self._close_confirmation = close_confirmation or self._default_close_confirmation
        self._open_directory_handler = open_directory_handler or self._default_open_directory
        self._state = WorkflowStateMachine()
        self._session: ImportSession | None = None
        self._inspection: WorkspaceInspection | None = None
        self._result: BatchOptimizationResult | None = None
        self._selected_network_id: str | None = None
        self._thread: QThread | None = None
        self._worker: BackendWorker | None = None
        self._token: CancellationToken | None = None
        self._task_kind: str | None = None
        self._task_started = 0.0
        self._pending_inspection = False
        self._close_pending = False
        self._global_logs: list[str] = []

        self.setWindowTitle("CAN FD Offset Optimizer — 工程批量工作区")
        self.resize(1280, 800)
        self.input_panel = InputPanel()
        self.settings_panel = SettingsPanel()
        self.progress_panel = ProgressPanel()
        self.summary_panel = BatchSummaryPanel()
        self.metrics_panel = self.summary_panel
        self.assignment_table = AssignmentTable()
        self.load_chart = LoadChart()
        self.load_heatmap = LoadHeatmap()
        self.quick_start_page = QuickStartPage()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("选择汇总表中的网段后显示日志、错误和警告详情")
        self.details_network_label = QLabel("当前网段：请选择一个网段")
        details_page = QWidget()
        details_layout = QVBoxLayout(details_page)
        details_layout.addWidget(self.details_network_label)
        details_layout.addWidget(self.log_view, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.backend_status_label = QLabel()
        if self._backend_availability.can_optimize:
            self.backend_status_label.setText(
                f"后端：{self._backend_availability.backend_name}（真实核心）"
            )
        else:
            self.backend_status_label.setText(
                f"仅预览 / 优化不可用：{self._backend_availability.message}"
            )
            self.backend_status_label.setStyleSheet("color: #b00020; font-weight: bold;")
        self.backend_status_label.setWordWrap(True)
        left_layout.addWidget(self.backend_status_label)
        left_layout.addWidget(self.input_panel)
        left_layout.addWidget(self.settings_panel)
        left_layout.addWidget(self.progress_panel)
        left_layout.addStretch(1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.quick_start_page, "快速开始")
        self.tabs.addTab(self.summary_panel, "结果概览")
        self.tabs.addTab(self.assignment_table, "Offset 修改")
        self.tabs.addTab(self.load_chart, "负载曲线")
        self.tabs.addTab(self.load_heatmap, "负载热力图")
        self.tabs.addTab(details_page, "运行日志与详情")
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.input_panel.sources_selected.connect(self.import_sources)
        self.input_panel.clear_requested.connect(self.clear_current_session)
        self.settings_panel.details_requested.connect(self.input_panel.show_details)
        self.progress_panel.run_requested.connect(self.start_optimization)
        self.progress_panel.cancel_requested.connect(self.request_cancel)
        self.summary_panel.network_selected.connect(self._select_network)
        self.summary_panel.open_output_requested.connect(self.open_output_directory)
        self.assignment_table.export_requested.connect(self._choose_assignment_export)
        self.load_chart.export_requested.connect(self._choose_chart_export)
        self.load_heatmap.export_requested.connect(self._choose_heatmap_export)
        self.load_heatmap.network_selected.connect(self._select_network_from_heatmap)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._refresh_controls()

    @property
    def workflow_state(self) -> WorkflowState:
        return self._state.state

    @property
    def import_session(self) -> ImportSession | None:
        return self._session

    @property
    def inspection(self) -> WorkspaceInspection | None:
        return self._inspection

    @property
    def result(self) -> BatchOptimizationResult | None:
        return self._result

    @property
    def selected_network(self) -> NetworkBatchResult | None:
        if self._result is None or self._selected_network_id is None:
            return None
        return self._result.network_items_by_id.get(self._selected_network_id)

    @property
    def selected_network_id(self) -> str | None:
        return self._selected_network_id

    @property
    def task_active(self) -> bool:
        return self._thread is not None

    def import_sources(self, value: object) -> None:
        if self.task_active or not isinstance(value, (tuple, list)) or not value:
            return
        sources = tuple(Path(path) for path in value)
        if not self._state.can_transition(WorkflowState.IMPORTING):
            return
        self._state.transition(WorkflowState.IMPORTING)
        self._reset_current_results()
        self._session = None
        self._inspection = None
        self.settings_panel.clear_inspection()
        self._append_log(f"开始导入 {len(sources)} 个文件/目录入口。")

        def operation(callback: ProgressCallback, token: CancellationToken) -> object:
            return self._backend.import_inputs(sources, callback, token)

        self._start_task("import", operation)

    def start_optimization(self) -> None:
        if not self._backend_availability.can_optimize:
            self._append_log(
                f"优化不可用：{self._backend_availability.message}"
            )
            return
        if self.task_active or self._inspection is None or not self._inspection.can_optimize:
            return
        try:
            request = self.settings_panel.build_request()
        except (TypeError, ValueError) as exc:
            self._append_log(f"批量设置错误：{exc}")
            self._show_error("无法开始批量优化", str(exc))
            return
        if not self._state.can_transition(WorkflowState.RUNNING):
            return
        self._state.transition(WorkflowState.RUNNING)
        self._reset_current_results()
        self._append_log(
            f"开始批量优化 {len(request.inspection.optimizable_networks)} 个网段；"
            f"权重={request.weight_mode.value}，模式={request.mode.value}。"
        )

        def operation(callback: ProgressCallback, token: CancellationToken) -> object:
            return self._backend.optimize_all_networks(request, callback, token)

        self._start_task("optimize", operation)

    def request_cancel(self) -> None:
        if self._token is None or self._state.state is WorkflowState.CANCELLING:
            return
        if self._state.can_transition(WorkflowState.CANCELLING):
            self._state.transition(WorkflowState.CANCELLING)
        self._token.cancel()
        self._append_log("已请求协作式停止；当前网段将在安全检查点结束，后续网段不会启动。")
        self._refresh_controls()

    def clear_current_session(self) -> None:
        if self.task_active:
            return
        self._session = None
        self._inspection = None
        self._reset_current_results()
        self._state.reset()
        self.input_panel.clear_display()
        self.settings_panel.clear_inspection()
        self._global_logs = ["当前会话已从界面清空；原始文件和历史 user_input 会话均未删除。"]
        self.log_view.setPlainText(self._global_logs[0])
        self._refresh_controls()

    def export_assignments_to(self, path: Path) -> Path:
        result = self._selected_result()
        exported = export_assignments_csv(result, path)
        self._append_log(f"{result.network_name} Offset CSV 已导出：{exported}")
        return exported

    def export_chart_to(self, path: Path) -> Path:
        result = self._selected_result()
        del result
        exported = self.load_chart.export_png(path)
        self._append_log(f"当前网段负载曲线已导出：{exported}")
        return exported

    def export_heatmap_to(self, path: Path) -> Path:
        result = self._selected_result()
        del result
        exported = self.load_heatmap.export_png(path)
        self._append_log(f"当前网段负载热力图已导出：{exported}")
        return exported

    def open_output_directory(self) -> None:
        if self._result is None:
            return
        try:
            if not self._open_directory_handler(self._result.output_directory):
                raise OSError("系统未能打开输出目录")
        except Exception as exc:  # GUI slot must not leak exceptions to the event loop.
            self._report_action_failure("打开输出目录", exc)

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

    def _start_inspection(self) -> None:
        if self.task_active or self._session is None:
            return
        if not self._state.can_transition(WorkflowState.INSPECTING):
            return
        self._state.transition(WorkflowState.INSPECTING)

        def operation(callback: ProgressCallback, token: CancellationToken) -> object:
            assert self._session is not None
            return self._backend.inspect_workspace(self._session, callback, token)

        self._start_task("inspect", operation)

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
        if self._task_kind == "import":
            if not isinstance(value, ImportSession):
                self._on_failed(WorkerFailure("后端导入会话缺失或类型无效。", repr(value)))
                return
            self._session = value
            self.input_panel.set_session(value)
            self._pending_inspection = True
            self._append_log(f"导入会话已创建：{value.session_directory}")
        elif self._task_kind == "inspect":
            if not isinstance(value, WorkspaceInspection):
                self._on_failed(WorkerFailure("后端工作区检查结果无效。", repr(value)))
                return
            self._inspection = value
            self._session = value.session
            self.input_panel.set_inspection(value)
            self.settings_panel.set_inspection(value)
            target = WorkflowState.READY if value.can_optimize else WorkflowState.INCOMPLETE
            self._state.transition(target)
            for kind in value.missing_required:
                self._append_log(f"缺少必需输入：{self.input_panel.kind_label(kind)}")
            for error in value.errors:
                self._append_log(f"工程冲突：{error}")
            for warning in value.warnings:
                self._append_log(f"警告：{warning}")
        else:
            if not isinstance(value, BatchOptimizationResult):
                self._on_failed(WorkerFailure("后端批量结果缺失或类型无效。", repr(value)))
                return
            self._apply_batch_result(value)
            target = {
                BatchRunStatus.SUCCEEDED: WorkflowState.SUCCEEDED,
                BatchRunStatus.PARTIAL: WorkflowState.PARTIAL,
                BatchRunStatus.FAILED: WorkflowState.FAILED,
                BatchRunStatus.CANCELLED: WorkflowState.CANCELLED,
            }[value.status]
            self._state.transition(target)
            self.progress_panel.finish_progress()
        self._refresh_controls()

    def _on_failed(self, value: object) -> None:
        failure = (
            value
            if isinstance(value, WorkerFailure)
            else WorkerFailure("后台任务返回了无效错误对象。", repr(value))
        )
        self._pending_inspection = False
        if self._state.can_transition(WorkflowState.FAILED):
            self._state.transition(WorkflowState.FAILED)
        self._append_log(f"工程级错误：{failure.user_message}")
        self._show_error("任务失败", failure.user_message, failure.technical_details)
        self._refresh_controls()

    def _on_cancelled(self, value: object) -> None:
        self._pending_inspection = False
        if isinstance(value, BatchOptimizationResult):
            self._apply_batch_result(value)
        if self._state.can_transition(WorkflowState.CANCELLED):
            self._state.transition(WorkflowState.CANCELLED)
        self._append_log("后台已停止；已完成网段结果和 user_output 汇总已保留。")
        self._refresh_controls()

    def _on_thread_finished(self) -> None:
        self._elapsed_timer.stop()
        self._thread = None
        self._worker = None
        self._token = None
        self._task_kind = None
        self._refresh_controls()
        if self._close_pending:
            self._pending_inspection = False
            self._close_pending = False
            QTimer.singleShot(0, self.close)
        elif self._pending_inspection:
            self._pending_inspection = False
            QTimer.singleShot(0, self._start_inspection)

    def _apply_batch_result(self, result: BatchOptimizationResult) -> None:
        self._result = result
        self.load_heatmap.set_batch(result)
        self.summary_panel.set_batch(result)
        self._append_log(
            f"批量汇总：成功 {result.succeeded_count}，失败 {result.failed_count}，"
            f"跳过 {result.skipped_count}，取消 {result.cancelled_count}。"
        )

    def _select_network(self, value: object) -> None:
        if value is None:
            self._clear_selected_network()
            return
        if not isinstance(value, str) or self._result is None:
            self._clear_selected_network()
            return
        item = self._result.network_items_by_id.get(value)
        if item is None:
            self._clear_selected_network()
            return
        self._selected_network_id = item.network_id
        self.details_network_label.setText(f"当前网段：{item.display_name}")
        self.details_network_label.setToolTip(
            f"network_id：{item.network_id}\n来源 DBC：{item.source_file}"
        )
        if item.result is None:
            self.assignment_table.clear_result(
                "无成功结果",
                network_id=item.network_id,
                display_name=item.display_name,
            )
            self.load_chart.clear_result(
                "无成功结果",
                network_id=item.network_id,
                display_name=item.display_name,
            )
            self.load_heatmap.clear_result(
                "无成功结果",
                network_id=item.network_id,
                display_name=item.display_name,
            )
        else:
            self.assignment_table.set_result(item.result)
            self.load_chart.set_result(item.result)
            self.load_heatmap.set_result(item.result)
        details = [
            f"网段：{item.network_name}",
            f"network_id：{item.network_id}",
            f"来源 DBC：{item.source_file}",
            f"状态：{item.status.value}",
        ]
        if item.error:
            details.append(f"错误：{item.error}")
        details.extend(f"警告：{warning}" for warning in item.warnings)
        details.extend(item.logs)
        self.log_view.setPlainText("\n".join(details))

    def _select_network_from_heatmap(self, network_id: str) -> None:
        if not self.summary_panel.select_network_id(network_id):
            self._select_network(network_id)

    def _clear_selected_network(self) -> None:
        self._selected_network_id = None
        self.assignment_table.clear_result()
        self.load_chart.clear_result()
        self.load_heatmap.clear_result()
        self.details_network_label.setText("当前网段：请选择一个网段")
        self.details_network_label.setToolTip("")
        self.log_view.setPlainText("请选择一个网段")

    def _selected_result(self) -> GuiOptimizationResult:
        selected = self.selected_network
        if selected is None or selected.result is None:
            raise RuntimeError("当前选中网段没有可导出的成功结果")
        return selected.result

    def _reset_current_results(self) -> None:
        self._result = None
        self._selected_network_id = None
        self.summary_panel.clear()
        self.load_heatmap.clear_batch()
        self._clear_selected_network()

    def _refresh_controls(self) -> None:
        active = self.task_active or self._state.state in {
            WorkflowState.IMPORTING,
            WorkflowState.INSPECTING,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLING,
        }
        self.input_panel.set_task_locked(active)
        ready = (
            self._backend_availability.can_optimize
            and self._inspection is not None
            and self._inspection.can_optimize
        )
        self.settings_panel.setEnabled(not active and ready)
        self.progress_panel.set_state(self._state.state, ready_to_run=ready and not active)
        if self._state.state is WorkflowState.INCOMPLETE and self._inspection is not None:
            if self._inspection.missing_required:
                missing = "、".join(
                    self.input_panel.kind_label(kind)
                    for kind in self._inspection.missing_required
                )
                reason = f"工程缺少必需输入：{missing}"
            elif self._inspection.errors:
                reason = "工程存在配置冲突，不能开始"
            else:
                reason = "没有可优化网段；DBC 必须包含周期 CAN FD TX 报文"
            self.progress_panel.set_unavailable_reason(reason)

    def _refresh_elapsed(self) -> None:
        if self._task_started:
            self.progress_panel.elapsed_label.setText(
                f"{perf_counter() - self._task_started:.1f} s"
            )

    def _append_log(self, message: str) -> None:
        self._global_logs.append(message)
        if self._selected_network_id is None:
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
            "批量任务仍在运行",
            "是否停止当前网段、跳过尚未开始的网段并在安全检查点退出？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer is QMessageBox.StandardButton.Yes

    @staticmethod
    def _default_open_directory(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _default_export_directory(self) -> Path:
        selected = self.selected_network
        if selected is not None and selected.result is not None:
            directory = selected.result.output_directory
            if directory is not None:
                return directory
        if self._result is not None:
            return self._result.output_directory
        return Path.cwd()

    def _choose_assignment_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前网段 Offset CSV",
            str(self._default_export_directory() / "offsets_copy.csv"),
            "CSV (*.csv)",
        )
        if path:
            self._safe_export("导出 Offset CSV", lambda: self.export_assignments_to(Path(path)))

    def _choose_chart_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前网段负载曲线",
            str(self._default_export_directory() / "load_curve.png"),
            "PNG (*.png)",
        )
        if path:
            self._safe_export("导出负载曲线", lambda: self.export_chart_to(Path(path)))

    def _choose_heatmap_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前网段负载热力图",
            str(self._default_export_directory() / "load_heatmap.png"),
            "PNG (*.png)",
        )
        if path:
            self._safe_export(
                "导出负载热力图", lambda: self.export_heatmap_to(Path(path))
            )

    def _safe_export(self, action_name: str, action: Callable[[], Path]) -> None:
        try:
            action()
        except Exception as exc:  # GUI slot must not leak exceptions to the event loop.
            self._report_action_failure(action_name, exc)

    def _report_action_failure(self, action_name: str, exc: Exception) -> None:
        self._append_log(f"{action_name}失败：{exc}")
        self._show_error(
            f"{action_name}失败",
            f"无法完成{action_name}，请检查输出路径、权限和系统关联设置。",
            f"{type(exc).__name__}: {exc}",
        )
