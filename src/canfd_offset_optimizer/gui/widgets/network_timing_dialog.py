"""Network-level nominal bitrate configuration dialog."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    """Edit one nominal bitrate per network without changing optimization inputs."""

    def __init__(
        self,
        networks: tuple[NetworkSummary, ...],
        configs: tuple[NetworkTimingConfig, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("网段速率参数")
        self.resize(780, 460)
        self._networks = networks
        self._original = {config.network_id: config for config in configs}
        self._editors: dict[str, QLineEdit] = {}
        self._source_items: dict[str, QTableWidgetItem] = {}
        self._status_items: dict[str, QTableWidgetItem] = {}
        self._timing_configs: tuple[NetworkTimingConfig, ...] | None = None

        intro = QLabel(
            "Nominal Bitrate 仅用于优化后的协议级保守占用时间诊断，不参与 GCLS。"
            "单位固定为 kbit/s；缺失不会阻止优化，也不会默认猜测 500。"
        )
        intro.setWordWrap(True)
        policy = QLabel(
            "CAN FD 保守模型整帧按 nominal bitrate 计时，假设 data-phase bitrate "
            "不低于 nominal bitrate；该值不是实际 CAN FD 帧时间。"
        )
        policy.setWordWrap(True)

        self.table = QTableWidget(len(networks), 5)
        self.table.setHorizontalHeaderLabels(
            ("网段", "类型", "Nominal Bitrate (kbit/s)", "来源", "状态")
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
            editor = QLineEdit()
            editor.setObjectName(f"nominal_bitrate_{network.network_id}")
            editor.setPlaceholderText("—")
            validator = QDoubleValidator(0.001, 100_000_000.0, 3, editor)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            editor.setValidator(validator)
            if config.nominal_bitrate_bps is not None:
                editor.setText(_format_kbit(config.nominal_bitrate_bps))
            source_item = QTableWidgetItem()
            status_item = QTableWidgetItem()
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, protocol_item)
            self.table.setCellWidget(row, 2, editor)
            self.table.setItem(row, 3, source_item)
            self.table.setItem(row, 4, status_item)
            self._editors[network.network_id] = editor
            self._source_items[network.network_id] = source_item
            self._status_items[network.network_id] = status_item
            editor.textChanged.connect(
                lambda _text, network_id=network.network_id: self._refresh_row(
                    network_id
                )
            )
            self._refresh_row(network.network_id)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.resizeSections(header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)

        self.batch_bitrate_spin = QDoubleSpinBox()
        self.batch_bitrate_spin.setRange(0.001, 100_000_000.0)
        self.batch_bitrate_spin.setDecimals(3)
        self.batch_bitrate_spin.setValue(500.0)
        self.batch_bitrate_spin.setSuffix(" kbit/s")
        self.batch_apply_button = QPushButton("应用到所有未配置 CAN FD 网段")
        self.batch_apply_button.clicked.connect(self.apply_to_unconfigured_fd)
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("批量值："))
        batch_row.addWidget(self.batch_bitrate_spin)
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

    @property
    def timing_configs(self) -> tuple[NetworkTimingConfig, ...] | None:
        return self._timing_configs

    @property
    def editors(self) -> dict[str, QLineEdit]:
        return dict(self._editors)

    def apply_to_unconfigured_fd(self) -> None:
        """Fill only currently empty CAN FD rows; never overwrite a value."""

        text = _format_kbit(int(self.batch_bitrate_spin.value() * 1_000))
        for network in self._networks:
            if network.frame_protocol is not FrameProtocol.CAN_FD:
                continue
            editor = self._editors[network.network_id]
            if not editor.text().strip():
                editor.setText(text)

    def accept(self) -> None:  # noqa: D102
        configs: list[NetworkTimingConfig] = []
        try:
            for network in self._networks:
                configs.append(self._config_for(network.network_id))
        except ValueError as exc:
            QMessageBox.warning(self, "Nominal Bitrate 无效", str(exc))
            return
        self._timing_configs = tuple(configs)
        super().accept()

    def _config_for(self, network_id: str) -> NetworkTimingConfig:
        text = self._editors[network_id].text().strip()
        bitrate = _parse_kbit(text)
        if bitrate is None:
            return NetworkTimingConfig(network_id)
        original = self._original.get(network_id)
        source = (
            original.source
            if original is not None
            and original.nominal_bitrate_bps == bitrate
            and original.source is not None
            else TimingConfigSource.MANUAL
        )
        return NetworkTimingConfig(network_id, bitrate, source, confirmed=True)

    def _refresh_row(self, network_id: str) -> None:
        try:
            config = self._config_for(network_id)
        except ValueError:
            self._source_items[network_id].setText("手动")
            self._status_items[network_id].setText("输入无效")
            self._status_items[network_id].setForeground(Qt.GlobalColor.red)
            return
        if config.nominal_bitrate_bps is None:
            self._source_items[network_id].setText("—")
            self._status_items[network_id].setText("待配置")
            self._status_items[network_id].setForeground(Qt.GlobalColor.darkYellow)
            return
        self._source_items[network_id].setText(
            "DBC" if config.source is TimingConfigSource.DBC else "手动"
        )
        self._status_items[network_id].setText("已配置")
        self._status_items[network_id].setForeground(Qt.GlobalColor.darkGreen)


def _parse_kbit(text: str) -> int | None:
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Nominal Bitrate 必须是正数。") from exc
    bps = value * 1_000
    if not value.is_finite() or value <= 0 or bps != bps.to_integral_value():
        raise ValueError("Nominal Bitrate 必须是可精确换算为 bit/s 的正数。")
    return int(bps)


def _format_kbit(bitrate_bps: int) -> str:
    value = Decimal(bitrate_bps) / Decimal(1_000)
    return format(value.normalize(), "f")
