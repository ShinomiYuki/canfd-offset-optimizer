"""Optimization metric comparison panel."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QPushButton

from ..contracts import GuiOptimizationResult
from ..view_models import metric_rows


class MetricsPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("结果概览")
        self._layout = QGridLayout(self)
        self._layout.addWidget(QLabel("指标"), 0, 0)
        self._layout.addWidget(QLabel("原始"), 0, 1)
        self._layout.addWidget(QLabel("优化后"), 0, 2)
        self._value_labels: list[tuple[QLabel, QLabel, QLabel]] = []
        for index in range(7):
            name = QLabel("—")
            before = QLabel("—")
            after = QLabel("—")
            self._layout.addWidget(name, index + 1, 0)
            self._layout.addWidget(before, index + 1, 1)
            self._layout.addWidget(after, index + 1, 2)
            self._value_labels.append((name, before, after))
        self.attempts_label = QLabel("—")
        self.stop_reason_label = QLabel("—")
        self.total_time_label = QLabel("—")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.export_summary_button = QPushButton("导出运行摘要 JSON")
        self.open_output_button = QPushButton("打开输出目录")
        self.export_summary_button.setEnabled(False)
        self.open_output_button.setEnabled(False)
        row = len(self._value_labels) + 1
        self._layout.addWidget(QLabel("实际 attempts："), row, 0)
        self._layout.addWidget(self.attempts_label, row, 1, 1, 2)
        self._layout.addWidget(QLabel("停止原因："), row + 1, 0)
        self._layout.addWidget(self.stop_reason_label, row + 1, 1, 1, 2)
        self._layout.addWidget(QLabel("总耗时："), row + 2, 0)
        self._layout.addWidget(self.total_time_label, row + 2, 1, 1, 2)
        self._layout.addWidget(self.warning_label, row + 3, 0, 1, 3)
        self._layout.addWidget(self.export_summary_button, row + 4, 1)
        self._layout.addWidget(self.open_output_button, row + 4, 2)

    def set_result(self, result: GuiOptimizationResult) -> None:
        for labels, row in zip(self._value_labels, metric_rows(result), strict=True):
            name, before, after = labels
            name.setText(row.label)
            name.setToolTip(row.tooltip)
            before.setText(row.original)
            after.setText(row.optimized)
        self.attempts_label.setText(str(result.actual_attempts))
        self.stop_reason_label.setText(result.stop_reason)
        self.total_time_label.setText(f"{result.elapsed_seconds:.3f} s")
        self.warning_label.setText("\n".join(f"⚠ {item}" for item in result.warnings))
        self.export_summary_button.setEnabled(True)
        self.open_output_button.setEnabled(True)
