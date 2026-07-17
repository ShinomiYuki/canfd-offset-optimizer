"""Default and advanced optimization settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..contracts import (
    GuiOptimizationRequest,
    InputInspectionRequest,
    InputSummary,
    OptimizationMode,
    RestartMode,
    RestartSettings,
)


class SettingsPanel(QGroupBox):
    """Expose stable project settings while retaining current core defaults."""

    def __init__(self) -> None:
        super().__init__("优化设置")
        self.network_combo = QComboBox()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Peak（严格峰值）", OptimizationMode.PEAK)
        self.mode_combo.addItem("Balanced（推荐）", OptimizationMode.BALANCED)
        self.mode_combo.addItem("Variance（实验）", OptimizationMode.VARIANCE)
        self.mode_combo.setCurrentIndex(1)
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 1.0)
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setSingleStep(0.01)
        self.tolerance_spin.setValue(0.05)
        self.tolerance_spin.setToolTip("Balanced 模式允许的峰值相对宽容量")
        self.restart_combo = QComboBox()
        self.restart_combo.addItem("自动（自适应）", RestartMode.ADAPTIVE)
        self.restart_combo.addItem("固定 attempts", RestartMode.FIXED)

        basic = QFormLayout()
        basic.addRow("网段：", self.network_combo)
        basic.addRow("模式：", self.mode_combo)
        basic.addRow("Balanced tolerance：", self.tolerance_spin)
        basic.addRow("Restart：", self.restart_combo)

        self.advanced_button = QToolButton()
        self.advanced_button.setText("高级选项")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_content = QWidget()
        advanced = QFormLayout(self.advanced_content)
        self.fixed_attempts_spin = QSpinBox()
        self.fixed_attempts_spin.setRange(1, 10_000)
        self.fixed_attempts_spin.setValue(21)
        self.adaptive_min_spin = QSpinBox()
        self.adaptive_min_spin.setRange(1, 10_000)
        self.adaptive_min_spin.setValue(20)
        self.adaptive_max_spin = QSpinBox()
        self.adaptive_max_spin.setRange(1, 10_000)
        self.adaptive_max_spin.setValue(80)
        self.candidate_pool_combo = QComboBox()
        for size in (1, 4, 8, 16, 32):
            self.candidate_pool_combo.addItem(str(size), size)
        self.triple_search_check = QCheckBox("启用冲突导向 3-opt")
        self.triple_search_check.setChecked(False)
        triple_warning = QLabel("高质量离线搜索，可能显著增加运行时间")
        triple_warning.setWordWrap(True)
        triple_warning.setToolTip("3-opt 默认关闭；仅在明确需要时启用")
        advanced.addRow("固定 attempts：", self.fixed_attempts_spin)
        advanced.addRow("自适应最少 attempts：", self.adaptive_min_spin)
        advanced.addRow("自适应最多 attempts：", self.adaptive_max_spin)
        advanced.addRow("Candidate pool：", self.candidate_pool_combo)
        advanced.addRow("", self.triple_search_check)
        advanced.addRow("", triple_warning)
        self.advanced_content.setVisible(False)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.restart_combo.currentIndexChanged.connect(self._update_restart_controls)
        self.mode_combo.currentIndexChanged.connect(self._update_mode_controls)

        layout = QVBoxLayout(self)
        layout.addLayout(basic)
        layout.addWidget(self.advanced_button)
        layout.addWidget(self.advanced_content)
        self._update_restart_controls()
        self._update_mode_controls()

    def set_input_summary(self, summary: InputSummary) -> None:
        self.network_combo.clear()
        for network in summary.networks:
            self.network_combo.addItem(
                f"{network.name}（{network.message_count} 条）", network.name
            )
        self.network_combo.setToolTip("\n".join(item.description for item in summary.networks))

    def build_request(
        self, inspection: InputInspectionRequest, output_directory: Path
    ) -> GuiOptimizationRequest:
        return GuiOptimizationRequest(
            inspection=inspection,
            network_name=str(self.network_combo.currentData() or ""),
            mode=self._selected_mode(),
            balanced_tolerance=self.tolerance_spin.value(),
            restart=RestartSettings(
                mode=self._selected_restart_mode(),
                fixed_attempts=self.fixed_attempts_spin.value(),
                min_attempts=self.adaptive_min_spin.value(),
                max_attempts=self.adaptive_max_spin.value(),
            ),
            candidate_pool_size=int(self.candidate_pool_combo.currentData()),
            enable_triple_search=self.triple_search_check.isChecked(),
            output_directory=output_directory,
        )

    def _selected_mode(self) -> OptimizationMode:
        value = self.mode_combo.currentData()
        return value if isinstance(value, OptimizationMode) else OptimizationMode(value)

    def _selected_restart_mode(self) -> RestartMode:
        value = self.restart_combo.currentData()
        return value if isinstance(value, RestartMode) else RestartMode(value)

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_content.setVisible(expanded)
        self.advanced_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _update_restart_controls(self) -> None:
        fixed = self._selected_restart_mode() is RestartMode.FIXED
        self.fixed_attempts_spin.setEnabled(fixed)
        self.adaptive_min_spin.setEnabled(not fixed)
        self.adaptive_max_spin.setEnabled(not fixed)

    def _update_mode_controls(self) -> None:
        self.tolerance_spin.setEnabled(self._selected_mode() is OptimizationMode.BALANCED)
