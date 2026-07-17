"""Batch run controls and project/network progress presentation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QProgressBar, QPushButton

from ..contracts import NetworkRunStatus, ProgressPhase, ProgressUpdate
from ..state import WorkflowState


class ProgressPanel(QGroupBox):
    run_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__("批量运行状态")
        self.status_label = QLabel("等待导入工程")
        self.phase_label = QLabel("—")
        self.network_label = QLabel("—")
        self.network_index_label = QLabel("—")
        self.network_status_label = QLabel("—")
        self.attempt_label = QLabel("—")
        self.elapsed_label = QLabel("0.0 s")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.run_button = QPushButton("开始全部网段优化")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        layout = QGridLayout(self)
        layout.addWidget(QLabel("状态："), 0, 0)
        layout.addWidget(self.status_label, 0, 1, 1, 3)
        layout.addWidget(QLabel("阶段："), 1, 0)
        layout.addWidget(self.phase_label, 1, 1, 1, 3)
        layout.addWidget(QLabel("当前网段："), 2, 0)
        layout.addWidget(self.network_label, 2, 1)
        layout.addWidget(QLabel("网段进度："), 2, 2)
        layout.addWidget(self.network_index_label, 2, 3)
        layout.addWidget(QLabel("网段状态："), 3, 0)
        layout.addWidget(self.network_status_label, 3, 1)
        layout.addWidget(QLabel("Attempt："), 3, 2)
        layout.addWidget(self.attempt_label, 3, 3)
        layout.addWidget(QLabel("总耗时："), 4, 0)
        layout.addWidget(self.elapsed_label, 4, 1)
        layout.addWidget(QLabel("总体进度："), 4, 2)
        layout.addWidget(self.progress_bar, 4, 3)
        layout.addWidget(self.run_button, 5, 2)
        layout.addWidget(self.cancel_button, 5, 3)
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

    def set_state(self, state: WorkflowState, *, ready_to_run: bool) -> None:
        labels = {
            WorkflowState.IDLE: "等待导入工程",
            WorkflowState.IMPORTING: "正在复制并分类输入",
            WorkflowState.INSPECTING: "正在检查工作区",
            WorkflowState.INCOMPLETE: "工程输入不完整或存在冲突",
            WorkflowState.READY: "全部网段已就绪",
            WorkflowState.RUNNING: "正在顺序优化全部网段",
            WorkflowState.CANCELLING: "正在请求停止当前网段",
            WorkflowState.SUCCEEDED: "全部网段优化完成",
            WorkflowState.PARTIAL: "批量运行完成（部分失败或跳过）",
            WorkflowState.FAILED: "工程级任务失败",
            WorkflowState.CANCELLED: "批量任务已取消，已完成结果已保留",
        }
        self.status_label.setText(labels[state])
        active = state in {
            WorkflowState.IMPORTING,
            WorkflowState.INSPECTING,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLING,
        }
        self.run_button.setEnabled(ready_to_run and not active)
        self.cancel_button.setEnabled(active and state is not WorkflowState.CANCELLING)

    def update_progress(self, update: ProgressUpdate) -> None:
        self.phase_label.setText(update.message)
        self.elapsed_label.setText(f"{update.elapsed_seconds:.1f} s")
        if update.network_name:
            self.network_label.setText(update.network_name)
        elif update.phase is not ProgressPhase.NETWORK_RUNNING:
            self.network_label.setText("—")
        if update.network_index is not None and update.network_total is not None:
            self.network_index_label.setText(f"{update.network_index}/{update.network_total}")
        elif update.phase is not ProgressPhase.NETWORK_RUNNING:
            self.network_index_label.setText("—")
        if update.network_status is not None:
            self.network_status_label.setText(self._status_text(update.network_status))
        elif update.phase is ProgressPhase.NETWORK_RUNNING:
            self.network_status_label.setText("运行中")
        else:
            self.network_status_label.setText("—")
        if update.attempt is not None and update.total_attempts is not None:
            self.attempt_label.setText(f"{update.attempt}/{update.total_attempts}")
        else:
            self.attempt_label.setText("—")
        if update.overall_total:
            self.progress_bar.setRange(0, update.overall_total)
            self.progress_bar.setValue(update.overall_completed)
        else:
            self.progress_bar.setRange(0, 0)

    def finish_progress(self) -> None:
        maximum = max(1, self.progress_bar.maximum())
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(maximum)

    def set_unavailable_reason(self, message: str) -> None:
        self.status_label.setText(message)

    @staticmethod
    def _status_text(status: NetworkRunStatus) -> str:
        return {
            NetworkRunStatus.SUCCEEDED: "成功",
            NetworkRunStatus.FAILED: "失败",
            NetworkRunStatus.SKIPPED: "跳过",
            NetworkRunStatus.CANCELLED: "已取消",
        }[status]
