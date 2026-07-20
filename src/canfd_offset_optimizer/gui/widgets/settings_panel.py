"""Shared settings applied to every automatically discovered network."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...config import OffsetSearchConfig
from ...exceptions import ConfigurationError
from ..contracts import (
    FrameProtocol,
    GuiBatchOptimizationRequest,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    WeightMode,
    WorkspaceInspection,
)


class SettingsPanel(QGroupBox):
    """Expose a compact basic form and opt-in expert search settings."""

    details_requested = Signal()

    def __init__(self) -> None:
        super().__init__("批量优化设置")
        self._inspection: WorkspaceInspection | None = None
        self._last_physical_mode = OptimizationMode.BALANCED
        self._weight_forced_peak = False

        self.networks_label = QLabel("已发现网段：0 个")
        self.networks_label.setWordWrap(True)
        self.details_button = QPushButton("查看详情")
        self.details_button.setEnabled(False)
        network_summary = QWidget()
        network_summary_layout = QHBoxLayout(network_summary)
        network_summary_layout.setContentsMargins(0, 0, 0, 0)
        network_summary_layout.addWidget(self.networks_label, 1)
        network_summary_layout.addWidget(self.details_button)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Peak（严格峰值）", OptimizationMode.PEAK)
        self.mode_combo.addItem("Balanced（推荐）", OptimizationMode.BALANCED)
        self.mode_combo.addItem("Variance（实验）", OptimizationMode.VARIANCE)
        self.mode_combo.setCurrentIndex(1)

        self.offset_min_spin = self._offset_spin(minimum=0, value=15)
        self.offset_max_spin = self._offset_spin(minimum=0, value=100)
        self.offset_step_spin = self._offset_spin(minimum=1, value=5)
        offset_range = QWidget()
        offset_range_layout = QHBoxLayout(offset_range)
        offset_range_layout.setContentsMargins(0, 0, 0, 0)
        offset_range_layout.setSpacing(6)
        offset_range_layout.addWidget(self.offset_min_spin)
        offset_range_layout.addWidget(QLabel("～"))
        offset_range_layout.addWidget(self.offset_max_spin)
        offset_range_layout.addWidget(QLabel("ms"))
        offset_range_layout.addStretch(1)

        offset_step = QWidget()
        offset_step_layout = QHBoxLayout(offset_step)
        offset_step_layout.setContentsMargins(0, 0, 0, 0)
        offset_step_layout.setSpacing(6)
        offset_step_layout.addWidget(self.offset_step_spin)
        offset_step_layout.addWidget(QLabel("ms"))
        offset_step_layout.addStretch(1)

        self.offset_summary_label = QLabel()
        self.offset_summary_label.setWordWrap(True)

        basic = QFormLayout()
        basic.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        basic.addRow(network_summary)
        basic.addRow("模式：", self.mode_combo)
        basic.addRow("Offset 范围：", offset_range)
        basic.addRow("Offset 步长：", offset_step)
        basic.addRow("", self.offset_summary_label)

        self.advanced_button = QToolButton()
        self.advanced_button.setText("高级搜索设置")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setChecked(False)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

        self.advanced_content = QWidget()
        self.advanced_layout = QFormLayout(self.advanced_content)
        self.advanced_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 1.0)
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setSingleStep(0.01)
        self.tolerance_spin.setValue(0.05)
        self.tolerance_spin.setToolTip("Balanced 模式允许的峰值相对宽容量")

        self.restart_combo = QComboBox()
        self.restart_combo.addItem("自动（自适应）", RestartMode.ADAPTIVE)
        self.restart_combo.addItem("固定次数", RestartMode.FIXED)
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
        self.triple_warning_label = QLabel(
            "高质量离线搜索，可能显著增加全部网段运行时间"
        )
        self.triple_warning_label.setWordWrap(True)

        self.advanced_layout.addRow("Balanced tolerance：", self.tolerance_spin)
        self.advanced_layout.addRow("Restart：", self.restart_combo)
        self.advanced_layout.addRow("固定 attempts：", self.fixed_attempts_spin)
        self.advanced_layout.addRow("自动最少 attempts：", self.adaptive_min_spin)
        self.advanced_layout.addRow("自动最多 attempts：", self.adaptive_max_spin)
        self.advanced_layout.addRow("Candidate pool：", self.candidate_pool_combo)
        self.advanced_layout.addRow("", self.triple_search_check)
        self.advanced_layout.addRow("", self.triple_warning_label)
        self.advanced_content.setVisible(False)

        # Kept as a non-visual compatibility adapter for older callers/tests. The
        # production UI always selects the automatic per-protocol strategy.
        self.weight_combo = QComboBox(self)
        self.weight_combo.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(basic)
        layout.addWidget(self.advanced_button)
        layout.addWidget(self.advanced_content)

        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.weight_combo.currentIndexChanged.connect(self._update_weight_controls)
        self.restart_combo.currentIndexChanged.connect(self._update_restart_controls)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.details_button.clicked.connect(self.details_requested.emit)
        for spin in (self.offset_min_spin, self.offset_max_spin, self.offset_step_spin):
            spin.valueChanged.connect(self._update_offset_summary)
        self._update_offset_summary()
        self._update_restart_controls()
        self._update_mode_controls()

    @staticmethod
    def _offset_spin(*, minimum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, 2_147_483_647)
        spin.setValue(value)
        return spin

    def set_inspection(self, inspection: WorkspaceInspection) -> None:
        self._inspection = inspection
        discovered = len(inspection.networks)
        optimizable = len(inspection.optimizable_networks)
        self.networks_label.setText(
            f"发现网段：{discovered} / 可优化：{optimizable} / 已跳过：{discovered - optimizable}"
        )
        self.details_button.setEnabled(True)
        self._set_weight_options(self._automatic_fd_weight_options(inspection))

    @staticmethod
    def _automatic_fd_weight_options(
        inspection: WorkspaceInspection,
    ) -> tuple[WeightMode, ...]:
        fd_networks = tuple(
            network
            for network in inspection.optimizable_networks
            if network.frame_protocol is FrameProtocol.CAN_FD
        )
        if not fd_networks:
            return (WeightMode.PAYLOAD_BYTES,)
        common = {WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US}
        for network in fd_networks:
            common.intersection_update(network.available_weight_modes)
        return tuple(
            mode
            for mode in (WeightMode.FRAME_TIME_US, WeightMode.PAYLOAD_BYTES)
            if mode in common
        )

    def clear_inspection(self) -> None:
        self._inspection = None
        self.networks_label.setText("已发现网段：0 个")
        self.details_button.setEnabled(False)
        self.weight_combo.clear()

    def build_request(self) -> GuiBatchOptimizationRequest:
        if self._inspection is None:
            raise ValueError("尚未完成工程工作区检查")
        weight_mode = self._selected_weight_mode(required=True)
        assert weight_mode is not None
        try:
            offset_search = OffsetSearchConfig(
                self.offset_min_spin.value(),
                self.offset_max_spin.value(),
                self.offset_step_spin.value(),
            )
        except ConfigurationError as exc:
            raise ValueError(str(exc)) from exc
        return GuiBatchOptimizationRequest(
            inspection=self._inspection,
            weight_mode=weight_mode,
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
            output_root=self._inspection.session.workspace_root / "user_output",
            offset_search=offset_search,
        )

    def _update_offset_summary(self) -> None:
        try:
            config = OffsetSearchConfig(
                self.offset_min_spin.value(),
                self.offset_max_spin.value(),
                self.offset_step_spin.value(),
            )
        except ConfigurationError as exc:
            self.offset_summary_label.setText(f"Offset 搜索范围无效：{exc}")
            return
        warning = (
            "；候选较多，运行时间可能显著增加"
            if config.candidate_count > 1_000
            else ""
        )
        self.offset_summary_label.setText(
            f"候选 {config.candidate_count} 个，"
            f"实际最大值 {config.effective_max_offset_ms} ms{warning}"
        )

    def _set_weight_options(self, modes: tuple[WeightMode, ...]) -> None:
        self.weight_combo.blockSignals(True)
        self.weight_combo.clear()
        labels = {
            WeightMode.PAYLOAD_BYTES: "Payload 长度近似权重（payload_bytes）",
            WeightMode.FRAME_TIME_US: "帧时间（frame_time_us）",
        }
        for mode in modes:
            self.weight_combo.addItem(labels[mode], mode)
        preferred = (
            WeightMode.FRAME_TIME_US
            if WeightMode.FRAME_TIME_US in modes
            else (modes[0] if modes else None)
        )
        if preferred is not None:
            self._select_combo_value(self.weight_combo, preferred)
        self.weight_combo.setEnabled(len(modes) > 1)
        self.weight_combo.setToolTip(
            "兼容接口；正式 GUI 自动选择。CAN FD 使用帧时间，"
            "Classic CAN 固定使用 Payload 长度近似。手动值只应用于 CAN FD。"
        )
        self.weight_combo.blockSignals(False)
        self._update_weight_controls()

    def _selected_mode(self) -> OptimizationMode:
        value = self.mode_combo.currentData()
        return value if isinstance(value, OptimizationMode) else OptimizationMode(value)

    def _selected_weight_mode(self, *, required: bool = False) -> WeightMode | None:
        value = self.weight_combo.currentData()
        if value is None:
            if required:
                raise ValueError("当前工程没有全部 CAN FD 网段共同支持的自动权重")
            return None
        return value if isinstance(value, WeightMode) else WeightMode(value)

    def _selected_restart_mode(self) -> RestartMode:
        value = self.restart_combo.currentData()
        return value if isinstance(value, RestartMode) else RestartMode(value)

    @staticmethod
    def _select_combo_value(combo: QComboBox, target: Enum) -> None:
        for index in range(combo.count()):
            value = combo.itemData(index)
            if value == target or value == target.value:
                combo.setCurrentIndex(index)
                return

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_content.setVisible(expanded)
        self.advanced_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _update_restart_controls(self) -> None:
        fixed = self._selected_restart_mode() is RestartMode.FIXED
        self.advanced_layout.setRowVisible(self.fixed_attempts_spin, fixed)
        self.advanced_layout.setRowVisible(self.adaptive_min_spin, not fixed)
        self.advanced_layout.setRowVisible(self.adaptive_max_spin, not fixed)

    def _update_weight_controls(self) -> None:
        weight_mode = self._selected_weight_mode()
        payload_selected = weight_mode is WeightMode.PAYLOAD_BYTES or (
            self._inspection is not None
            and any(
                network.frame_protocol is FrameProtocol.CLASSIC_CAN
                for network in self._inspection.optimizable_networks
            )
        )
        if payload_selected and not self._weight_forced_peak:
            self._last_physical_mode = self._selected_mode()
            self._weight_forced_peak = True
            self._select_combo_value(self.mode_combo, OptimizationMode.PEAK)
        elif not payload_selected and self._weight_forced_peak:
            self._weight_forced_peak = False
            self._select_combo_value(self.mode_combo, self._last_physical_mode)
        self.mode_combo.setEnabled(not payload_selected)
        self._update_mode_controls()

    def _on_mode_changed(self) -> None:
        if not self._weight_forced_peak:
            self._last_physical_mode = self._selected_mode()
        self._update_mode_controls()

    def _update_mode_controls(self) -> None:
        show_tolerance = (
            not self._weight_forced_peak
            and self._selected_mode() is OptimizationMode.BALANCED
        )
        self.advanced_layout.setRowVisible(self.tolerance_spin, show_tolerance)
