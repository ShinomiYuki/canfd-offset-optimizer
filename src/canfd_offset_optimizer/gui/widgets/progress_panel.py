"""Run controls and compact progress presentation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QProgressBar, QPushButton

from ..contracts import ProgressUpdate
from ..state import WorkflowState


class ProgressPanel(QGroupBox):
    run_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__("运行状态")
        self.status_label = QLabel("等待选择输入")
        self.phase_label = QLabel("—")
        self.attempt_label = QLabel("—")
        self.elapsed_label = QLabel("0.0 s")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.run_button = QPushButton("开始优化")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        layout = QGridLayout(self)
        layout.addWidget(QLabel("状态："), 0, 0)
        layout.addWidget(self.status_label, 0, 1, 1, 3)
        layout.addWidget(QLabel("阶段："), 1, 0)
        layout.addWidget(self.phase_label, 1, 1, 1, 3)
        layout.addWidget(QLabel("Attempt："), 2, 0)
        layout.addWidget(self.attempt_label, 2, 1)
        layout.addWidget(QLabel("已用时间："), 2, 2)
        layout.addWidget(self.elapsed_label, 2, 3)
        layout.addWidget(self.progress_bar, 3, 0, 1, 4)
        layout.addWidget(self.run_button, 4, 2)
        layout.addWidget(self.cancel_button, 4, 3)
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

    def set_state(self, state: WorkflowState, *, ready_to_run: bool) -> None:
        labels = {
            WorkflowState.IDLE: "等待选择输入",
            WorkflowState.INSPECTING: "正在读取输入",
            WorkflowState.READY: "输入已就绪",
            WorkflowState.RUNNING: "正在优化",
            WorkflowState.CANCELLING: "正在请求停止",
            WorkflowState.SUCCEEDED: "优化完成",
            WorkflowState.FAILED: "任务失败",
            WorkflowState.CANCELLED: "任务已取消",
        }
        self.status_label.setText(labels[state])
        active = state in {
            WorkflowState.INSPECTING,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLING,
        }
        self.run_button.setEnabled(ready_to_run and not active)
        self.cancel_button.setEnabled(active and state is not WorkflowState.CANCELLING)

    def update_progress(self, update: ProgressUpdate) -> None:
        self.phase_label.setText(update.message)
        self.elapsed_label.setText(f"{update.elapsed_seconds:.1f} s")
        if update.attempt is None or update.total_attempts is None:
            self.attempt_label.setText("—")
            self.progress_bar.setRange(0, 0)
        else:
            self.attempt_label.setText(f"{update.attempt}/{update.total_attempts}")
            self.progress_bar.setRange(0, update.total_attempts)
            self.progress_bar.setValue(update.attempt)

    def finish_progress(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
