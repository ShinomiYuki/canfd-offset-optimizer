"""Live project details dialog backed by the main session models."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..view_models import ImportDetailsTableModel, NetworkDetailsTableModel


class ProjectDetailsDialog(QDialog):
    """Non-modal detail view sharing the exact models owned by InputPanel."""

    def __init__(
        self,
        network_model: NetworkDetailsTableModel,
        import_model: ImportDetailsTableModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("工程导入与网段详情")
        self.setModal(False)
        self.resize(980, 560)
        self.tabs = QTabWidget()
        self.network_table = self._table(network_model)
        self.import_table = self._table(import_model)
        self.tabs.addTab(self.network_table, "网段详情")
        self.tabs.addTab(self.import_table, "导入文件详情")
        self.weight_strategy_label = QLabel(
            "权重策略：自动\n"
            "CAN FD：帧时间（frame_time_us）\n"
            "Classic CAN：Payload 长度近似（payload_bytes）"
        )
        self.weight_strategy_label.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.hide)
        layout = QVBoxLayout(self)
        layout.addWidget(self.weight_strategy_label)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def show_details(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.network_table.resizeColumnsToContents()
        self.import_table.resizeColumnsToContents()

    @staticmethod
    def _table(model: NetworkDetailsTableModel | ImportDetailsTableModel) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        return table
