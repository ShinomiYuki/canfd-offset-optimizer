"""Live project details dialog backed by the main session models."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..view_models import (
    ImportDetailsTableModel,
    MessageEligibilityFilterProxy,
    MessageEligibilityTableModel,
    NetworkDetailsTableModel,
    RouteExclusionFilterProxy,
    RouteExclusionTableModel,
    SenderSelectionSummaryTableModel,
)


class ProjectDetailsDialog(QDialog):
    """Non-modal detail view sharing the exact models owned by InputPanel."""

    def __init__(
        self,
        network_model: NetworkDetailsTableModel,
        import_model: ImportDetailsTableModel,
        routing_model: RouteExclusionTableModel,
        sender_summary_model: SenderSelectionSummaryTableModel,
        message_eligibility_model: MessageEligibilityTableModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("工程导入与网段详情")
        self.setModal(False)
        self.resize(980, 560)
        self.tabs = QTabWidget()
        self.network_table = self._table(network_model)
        self.import_table = self._table(import_model)
        self.routing_proxy = RouteExclusionFilterProxy(routing_model)
        self.routing_table = self._table(self.routing_proxy)
        self.routing_filter = QComboBox()
        for label, value in (
            ("全部", "all"),
            ("已匹配并排除", "excluded"),
            ("未找到", "not_found"),
            ("匹配歧义", "ambiguous"),
            ("名称不一致", "name_mismatch"),
            ("重复记录", "duplicate"),
        ):
            self.routing_filter.addItem(label, value)
        self.routing_filter.currentIndexChanged.connect(
            lambda _index: self.routing_proxy.set_filter_name(
                str(self.routing_filter.currentData())
            )
        )
        self.sender_summary_table = self._table(sender_summary_model)
        self.message_eligibility_proxy = MessageEligibilityFilterProxy(
            message_eligibility_model
        )
        self.message_eligibility_table = self._table(
            self.message_eligibility_proxy
        )
        self.message_filter = QComboBox()
        for label, value in (
            ("全部", "all"),
            ("参与优化", "final"),
            ("其他 ECU 报文", "unselected"),
            ("路由报文", "routing"),
            ("非周期报文", "non_periodic"),
            ("异常报文", "error"),
        ):
            self.message_filter.addItem(label, value)
        self.message_filter.currentIndexChanged.connect(
            lambda _index: self.message_eligibility_proxy.set_filter_name(
                str(self.message_filter.currentData())
            )
        )
        sender_page = QWidget()
        sender_layout = QVBoxLayout(sender_page)
        sender_layout.addWidget(QLabel("DBC 级发送节点筛选摘要"))
        sender_layout.addWidget(self.sender_summary_table, 1)
        sender_filter_layout = QHBoxLayout()
        sender_filter_layout.addWidget(QLabel("报文筛选："))
        sender_filter_layout.addWidget(self.message_filter)
        sender_filter_layout.addStretch(1)
        sender_layout.addLayout(sender_filter_layout)
        sender_layout.addWidget(QLabel("报文级资格与排除原因"))
        sender_layout.addWidget(self.message_eligibility_table, 2)

        routing_page = QWidget()
        routing_layout = QVBoxLayout(routing_page)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("筛选："))
        filter_layout.addWidget(self.routing_filter)
        filter_layout.addStretch(1)
        routing_layout.addLayout(filter_layout)
        routing_layout.addWidget(self.routing_table)
        self.tabs.addTab(self.network_table, "网段详情")
        self.tabs.addTab(self.import_table, "导入文件详情")
        self.tabs.addTab(sender_page, "发送节点筛选")
        self.tabs.addTab(routing_page, "路由报文排除")
        self.weight_strategy_label = QLabel(
            "权重策略：按物理网段独立应用\n"
            "Classic CAN：固定为 Payload 长度近似（payload_bytes）\n"
            "CAN FD：使用批量优化设置中的 CAN FD 权重"
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
        self.routing_table.resizeColumnsToContents()
        self.sender_summary_table.resizeColumnsToContents()
        self.message_eligibility_table.resizeColumnsToContents()

    @staticmethod
    def _table(model: QAbstractItemModel) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        return table
