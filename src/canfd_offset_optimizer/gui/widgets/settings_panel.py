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
    GuiBatchOptimizationRequest,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    FrameProtocol,
    WeightMode,
    WorkspaceInspection,
)


class SettingsPanel(QGroupBox):
    """Expose one configuration snapshot for the full network batch."""

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
        self.weight_combo = QComboBox()
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
        basic.addRow(network_summary)
        basic.addRow("权重：", self.weight_combo)
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
        self.offset_min_spin = QSpinBox()
        self.offset_max_spin = QSpinBox()
        self.offset_step_spin = QSpinBox()
        for spin in (self.offset_min_spin, self.offset_max_spin):
            spin.setRange(0, 2_147_483_647)
            spin.setSuffix(" ms")
        self.offset_step_spin.setRange(1, 2_147_483_647)
        self.offset_step_spin.setSuffix(" ms")
        self.offset_min_spin.setValue(15)
        self.offset_max_spin.setValue(100)
        self.offset_step_spin.setValue(5)
        self.offset_summary_label = QLabel()
        self.offset_summary_label.setWordWrap(True)
        triple_warning = QLabel("高质量离线搜索，可能显著增加全部网段总运行时间")
        triple_warning.setWordWrap(True)
        advanced.addRow("固定 attempts：", self.fixed_attempts_spin)
        advanced.addRow("自适应最少 attempts：", self.adaptive_min_spin)
        advanced.addRow("自适应最多 attempts：", self.adaptive_max_spin)
        advanced.addRow("Candidate pool：", self.candidate_pool_combo)
        advanced.addRow("Offset 最小值：", self.offset_min_spin)
        advanced.addRow("Offset 最大值：", self.offset_max_spin)
        advanced.addRow("Offset 步长：", self.offset_step_spin)
        advanced.addRow("", self.offset_summary_label)
        advanced.addRow("", self.triple_search_check)
        advanced.addRow("", triple_warning)
        self.advanced_content.setVisible(False)

        layout = QVBoxLayout(self)
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

    def set_inspection(self, inspection: WorkspaceInspection) -> None:
        self._inspection = inspection
        discovered = len(inspection.networks)
        optimizable = len(inspection.optimizable_networks)
        self.networks_label.setText(
            f"发现网段：{discovered} / 可优化：{optimizable} / 已跳过：{discovered - optimizable}"
        )
        self.details_button.setEnabled(True)
        fd_networks = tuple(
            network
            for network in inspection.optimizable_networks
            if network.frame_protocol is FrameProtocol.CAN_FD
        )
        if fd_networks:
            available = {WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US}
            for network in fd_networks:
                available.intersection_update(network.available_weight_modes)
            modes = tuple(
                mode
                for mode in (WeightMode.FRAME_TIME_US, WeightMode.PAYLOAD_BYTES)
                if mode in available
            )
        else:
            modes = (WeightMode.PAYLOAD_BYTES,)
        self._set_weight_options(modes)

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
        warning = "；候选较多，运行时间可能显著增加" if config.candidate_count > 1_000 else ""
        self.offset_summary_label.setText(
            f"范围 {config.min_offset_ms}～{config.max_offset_ms} ms，"
            f"步长 {config.offset_step_ms} ms，候选 {config.candidate_count} 个，"
            f"实际最大值 {config.effective_max_offset_ms} ms{warning}"
        )

    def _set_weight_options(self, modes: tuple[WeightMode, ...]) -> None:
        previous = self._selected_weight_mode()
        labels = {
            WeightMode.PAYLOAD_BYTES: "Payload 长度近似权重（payload_bytes）",
            WeightMode.FRAME_TIME_US: "帧时间（frame_time_us）",
        }
        self.weight_combo.blockSignals(True)
        self.weight_combo.clear()
        for mode in modes:
            self.weight_combo.addItem(labels[mode], mode)
        preferred = (
            previous
            if previous in modes
            else (WeightMode.FRAME_TIME_US if WeightMode.FRAME_TIME_US in modes else None)
        )
        if preferred is not None:
            self._select_combo_value(self.weight_combo, preferred)
        self.weight_combo.setEnabled(len(modes) > 1)
        self.weight_combo.setToolTip(
            "该选项只应用于 CAN FD 网段；Classic CAN 固定使用 Payload 长度近似权重。"
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
                raise ValueError("当前工程没有全部网段共同支持的权重")
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
        self.fixed_attempts_spin.setEnabled(fixed)
        self.adaptive_min_spin.setEnabled(not fixed)
        self.adaptive_max_spin.setEnabled(not fixed)

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
        self.tolerance_spin.setEnabled(
            not self._weight_forced_peak
            and self._selected_mode() is OptimizationMode.BALANCED
        )
