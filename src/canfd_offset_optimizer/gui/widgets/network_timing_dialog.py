"""Network-level timing configuration for conservative result diagnostics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..contracts import (
    FrameProtocol,
    NetworkSummary,
    NetworkTimingConfig,
    TimingConfigSource,
)


class NetworkTimingDialog(QDialog):
    """Edit result-only timing metadata without changing optimization inputs."""

    def __init__(
        self,
        networks: tuple[NetworkSummary, ...],
        configs: tuple[NetworkTimingConfig, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("网段速率参数")
        self.resize(1120, 500)
        self._networks = networks
        self._network_by_id = {network.network_id: network for network in networks}
        self._original = {config.network_id: config for config in configs}
        self._editors: dict[str, QLineEdit] = {}
        self._data_editors: dict[str, QLineEdit] = {}
        self._brs_combos: dict[str, QComboBox] = {}
        self._source_items: dict[str, QTableWidgetItem] = {}
        self._status_items: dict[str, QTableWidgetItem] = {}
        self._timing_configs: tuple[NetworkTimingConfig, ...] | None = None

        intro = QLabel(
            "这些参数仅用于优化后的协议级保守占用时间诊断，不参与 GCLS。"
            "Classic CAN 只需 Nominal Bitrate；CAN FD 按 Nominal、Data 和有效 BRS 分阶段计时。"
        )
        intro.setWordWrap(True)
        policy = QLabel(
            "DBC 有可靠值时自动使用；缺失值可按网段人工确认。"
            "BRS 未确认，或 BRS 开启但缺少 Data Bitrate 时，仅该诊断显示为不可计算，Offset 结果仍有效。"
        )
        policy.setWordWrap(True)

        self.table = QTableWidget(len(networks), 7)
        self.table.setHorizontalHeaderLabels(
            (
                "网段",
                "类型",
                "Nominal Bitrate (kbit/s)",
                "Data Bitrate (kbit/s)",
                "BRS",
                "来源",
                "状态",
            )
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for row, network in enumerate(networks):
            config = self._original.get(
                network.network_id, NetworkTimingConfig(network.network_id)
            )
            name_item = QTableWidgetItem(network.display_name)
            name_item.setToolTip(
                f"network_id：{network.network_id}\n来源 DBC：{network.source_file}"
            )
            protocol_item = QTableWidgetItem(
                "Classic CAN"
                if network.frame_protocol is FrameProtocol.CLASSIC_CAN
                else "CAN FD"
            )
            nominal_editor = self._bitrate_editor(
                f"nominal_bitrate_{network.network_id}"
            )
            if config.nominal_bitrate_bps is not None:
                nominal_editor.setText(_format_kbit(config.nominal_bitrate_bps))
            data_editor = self._bitrate_editor(f"data_bitrate_{network.network_id}")
            brs_combo = QComboBox()
            brs_combo.setObjectName(f"brs_{network.network_id}")
            if network.frame_protocol is FrameProtocol.CLASSIC_CAN:
                data_editor.setEnabled(False)
                data_editor.setPlaceholderText("—")
                brs_combo.addItem("—", None)
                brs_combo.setEnabled(False)
            else:
                if config.data_bitrate_bps is not None:
                    data_editor.setText(_format_kbit(config.data_bitrate_bps))
                if config.dbc_brs_complete:
                    text = "来自 DBC / 按报文"
                    if config.dbc_brs_mixed:
                        text += "（混合）"
                    brs_combo.addItem(text, "dbc_by_message")
                    brs_combo.setEnabled(False)
                else:
                    brs_combo.addItem("未确认", None)
                    brs_combo.addItem("开启", True)
                    brs_combo.addItem("关闭", False)
                    index = brs_combo.findData(config.default_brs)
                    brs_combo.setCurrentIndex(max(0, index))
            source_item = QTableWidgetItem()
            status_item = QTableWidgetItem()
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, protocol_item)
            self.table.setCellWidget(row, 2, nominal_editor)
            self.table.setCellWidget(row, 3, data_editor)
            self.table.setCellWidget(row, 4, brs_combo)
            self.table.setItem(row, 5, source_item)
            self.table.setItem(row, 6, status_item)
            self._editors[network.network_id] = nominal_editor
            self._data_editors[network.network_id] = data_editor
            self._brs_combos[network.network_id] = brs_combo
            self._source_items[network.network_id] = source_item
            self._status_items[network.network_id] = status_item
            nominal_editor.textChanged.connect(
                lambda _text, network_id=network.network_id: self._refresh_row(
                    network_id
                )
            )
            data_editor.textChanged.connect(
                lambda _text, network_id=network.network_id: self._refresh_row(
                    network_id
                )
            )
            brs_combo.currentIndexChanged.connect(
                lambda _index, network_id=network.network_id: self._refresh_row(
                    network_id
                )
            )
            self._refresh_row(network.network_id)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.resizeSections(header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)

        self.batch_bitrate_spin = self._batch_spin(500.0)
        self.batch_data_bitrate_spin = self._batch_spin(2000.0)
        self.batch_brs_combo = QComboBox()
        self.batch_brs_combo.addItem("开启", True)
        self.batch_brs_combo.addItem("关闭", False)
        self.batch_brs_combo.addItem("未确认", None)
        self.batch_apply_button = QPushButton("应用到所有未配置 CAN FD 网段")
        self.batch_apply_button.clicked.connect(self.apply_to_unconfigured_fd)
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("批量 Nominal："))
        batch_row.addWidget(self.batch_bitrate_spin)
        batch_row.addWidget(QLabel("Data："))
        batch_row.addWidget(self.batch_data_bitrate_spin)
        batch_row.addWidget(QLabel("BRS："))
        batch_row.addWidget(self.batch_brs_combo)
        batch_row.addWidget(self.batch_apply_button)
        batch_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(policy)
        layout.addWidget(self.table, 1)
        layout.addLayout(batch_row)
        layout.addWidget(buttons)

    @staticmethod
    def _bitrate_editor(name: str) -> QLineEdit:
        editor = QLineEdit()
        editor.setObjectName(name)
        editor.setPlaceholderText("—")
        validator = QDoubleValidator(0.001, 100_000_000.0, 3, editor)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        editor.setValidator(validator)
        return editor

    @staticmethod
    def _batch_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.001, 100_000_000.0)
        spin.setDecimals(3)
        spin.setValue(value)
        spin.setSuffix(" kbit/s")
        return spin

    @property
    def timing_configs(self) -> tuple[NetworkTimingConfig, ...] | None:
        return self._timing_configs

    @property
    def editors(self) -> dict[str, QLineEdit]:
        """Compatibility name for the Nominal Bitrate editors."""

        return dict(self._editors)

    @property
    def data_editors(self) -> dict[str, QLineEdit]:
        return dict(self._data_editors)

    @property
    def brs_combos(self) -> dict[str, QComboBox]:
        return dict(self._brs_combos)

    def apply_to_unconfigured_fd(self) -> None:
        """Fill empty CAN FD fields only after the explicit batch action."""

        nominal_text = _format_kbit(int(self.batch_bitrate_spin.value() * 1_000))
        data_text = _format_kbit(
            int(self.batch_data_bitrate_spin.value() * 1_000)
        )
        batch_brs = self.batch_brs_combo.currentData()
        for network in self._networks:
            if network.frame_protocol is not FrameProtocol.CAN_FD:
                continue
            nominal_editor = self._editors[network.network_id]
            data_editor = self._data_editors[network.network_id]
            brs_combo = self._brs_combos[network.network_id]
            if not nominal_editor.text().strip():
                nominal_editor.setText(nominal_text)
            if not data_editor.text().strip():
                data_editor.setText(data_text)
            if brs_combo.isEnabled() and brs_combo.currentData() is None:
                index = brs_combo.findData(batch_brs)
                brs_combo.setCurrentIndex(max(0, index))

    def accept(self) -> None:  # noqa: D102
        configs: list[NetworkTimingConfig] = []
        try:
            for network in self._networks:
                configs.append(self._config_for(network.network_id))
        except ValueError as exc:
            QMessageBox.warning(self, "网段时序参数无效", str(exc))
            return
        self._timing_configs = tuple(configs)
        super().accept()

    def _config_for(self, network_id: str) -> NetworkTimingConfig:
        network = self._network_by_id[network_id]
        original = self._original.get(network_id, NetworkTimingConfig(network_id))
        nominal = _parse_kbit(
            self._editors[network_id].text().strip(), "Nominal Bitrate"
        )
        nominal_source = _preserved_or_manual_source(
            nominal, original.nominal_bitrate_bps, original.nominal_source
        )
        if network.frame_protocol is FrameProtocol.CLASSIC_CAN:
            return NetworkTimingConfig(
                network_id,
                nominal,
                nominal_source,
                confirmed=nominal is not None,
            )

        data = _parse_kbit(
            self._data_editors[network_id].text().strip(), "Data Bitrate"
        )
        data_source = _preserved_or_manual_source(
            data, original.data_bitrate_bps, original.data_source
        )
        if original.dbc_brs_complete:
            default_brs = original.default_brs
            brs_source = original.brs_source
        else:
            raw_brs = self._brs_combos[network_id].currentData()
            default_brs = raw_brs if isinstance(raw_brs, bool) else None
            brs_source = _preserved_or_manual_source(
                default_brs, original.default_brs, original.brs_source
            )
        return NetworkTimingConfig(
            network_id=network_id,
            nominal_bitrate_bps=nominal,
            nominal_source=nominal_source,
            confirmed=nominal is not None,
            data_bitrate_bps=data,
            default_brs=default_brs,
            data_source=data_source,
            brs_source=brs_source,
            dbc_brs_complete=original.dbc_brs_complete,
            dbc_brs_mixed=original.dbc_brs_mixed,
            dbc_brs_has_on=original.dbc_brs_has_on,
        )

    def _refresh_row(self, network_id: str) -> None:
        status_item = self._status_items[network_id]
        try:
            config = self._config_for(network_id)
        except ValueError:
            self._source_items[network_id].setText("手动")
            status_item.setText("输入无效")
            status_item.setToolTip("Bitrate 必须能精确换算为正整数 bit/s。")
            status_item.setForeground(Qt.GlobalColor.red)
            return
        network = self._network_by_id[network_id]
        self._source_items[network_id].setText(_sources_text(config, network))
        if config.nominal_bitrate_bps is None:
            status_item.setText("待配置：缺少 Nominal")
            status_item.setToolTip("优化仍可运行；保守占用时间不可计算。")
            status_item.setForeground(Qt.GlobalColor.darkYellow)
            return
        if network.frame_protocol is FrameProtocol.CAN_FD:
            if not config.has_complete_brs():
                status_item.setText("待确认：BRS")
                status_item.setToolTip("BRS 未知不会自动按开启或关闭猜测。")
                status_item.setForeground(Qt.GlobalColor.darkYellow)
                return
            if config.requires_data_bitrate() and config.data_bitrate_bps is None:
                status_item.setText("待配置：缺少 Data")
                status_item.setToolTip("存在 BRS 开启报文，必须提供 Data Bitrate。")
                status_item.setForeground(Qt.GlobalColor.darkYellow)
                return
            if (
                config.data_bitrate_bps is not None
                and config.data_bitrate_bps < config.nominal_bitrate_bps
            ):
                status_item.setText("已配置（Data < Nominal）")
                status_item.setToolTip(
                    "这是少见配置；数值会按输入保存并计算，不会被自动修改。"
                )
                status_item.setForeground(Qt.GlobalColor.darkYellow)
                return
        status_item.setText("已配置")
        status_item.setToolTip("")
        status_item.setForeground(Qt.GlobalColor.darkGreen)


def _preserved_or_manual_source(
    value: object | None,
    original_value: object | None,
    original_source: TimingConfigSource | None,
) -> TimingConfigSource | None:
    if value is None:
        return None
    if value == original_value and original_source is not None:
        return original_source
    return TimingConfigSource.MANUAL


def _sources_text(
    config: NetworkTimingConfig, network: NetworkSummary
) -> str:
    def label(source: TimingConfigSource | None) -> str:
        if source is TimingConfigSource.DBC:
            return "DBC"
        if source is TimingConfigSource.MANUAL:
            return "手动"
        return "—"

    parts = [f"N:{label(config.nominal_source)}"]
    if network.frame_protocol is FrameProtocol.CAN_FD:
        parts.append(f"D:{label(config.data_source)}")
        if config.dbc_brs_complete:
            parts.append("BRS:DBC/按报文")
        else:
            parts.append(f"BRS:{label(config.brs_source)}")
    return "；".join(parts)


def _parse_kbit(text: str, field_name: str = "Bitrate") -> int | None:
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} 必须是正数。") from exc
    bps = value * 1_000
    if not value.is_finite() or value <= 0 or bps != bps.to_integral_value():
        raise ValueError(f"{field_name} 必须是可精确换算为 bit/s 的正数。")
    return int(bps)


def _format_kbit(bitrate_bps: int) -> str:
    value = Decimal(bitrate_bps) / Decimal(1_000)
    return format(value.normalize(), "f")