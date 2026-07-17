"""All-network summary table and project-level output actions."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ..contracts import BatchOptimizationResult, NetworkBatchResult, NetworkRunStatus
from ..view_models import BatchSummaryFilterProxy, BatchSummaryTableModel


class BatchSummaryPanel(QGroupBox):
    """Default result page showing one row per network."""

    network_selected = Signal(object)
    open_output_requested = Signal()

    def __init__(self) -> None:
        super().__init__("全网段结果概览")
        self.network_filter = QLineEdit()
        self.network_filter.setPlaceholderText("按网段名筛选")
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部状态", None)
        for label, status in (
            ("成功", NetworkRunStatus.SUCCEEDED),
            ("失败", NetworkRunStatus.FAILED),
            ("跳过", NetworkRunStatus.SKIPPED),
            ("取消", NetworkRunStatus.CANCELLED),
        ):
            self.status_filter.addItem(label, status)
        self.improvement_filter = QSpinBox()
        self.improvement_filter.setRange(0, 1_000_000_000)
        self.improvement_filter.setPrefix("Zss 改善 ≥ ")
        self.model = BatchSummaryTableModel()
        self.proxy = BatchSummaryFilterProxy(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        filters = QHBoxLayout()
        filters.addWidget(self.network_filter, 1)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.improvement_filter)
        self.count_label = QLabel("成功 0 / 失败 0 / 跳过 0 / 取消 0")
        self.elapsed_label = QLabel("总耗时：—")
        self.output_label = QLabel("输出目录：—")
        self.output_label.setWordWrap(True)
        self.open_output_button = QPushButton("打开输出目录")
        self.open_output_button.setEnabled(False)
        summary = QGridLayout()
        summary.addWidget(self.count_label, 0, 0)
        summary.addWidget(self.elapsed_label, 0, 1)
        summary.addWidget(self.output_label, 1, 0, 1, 2)
        summary.addWidget(self.open_output_button, 1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addLayout(summary)
        self.network_filter.textChanged.connect(self.proxy.set_query)
        self.status_filter.currentIndexChanged.connect(self._update_status_filter)
        self.improvement_filter.valueChanged.connect(self.proxy.set_minimum_improvement)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.open_output_button.clicked.connect(self.open_output_requested.emit)

    def set_batch(self, batch: BatchOptimizationResult) -> None:
        self.network_filter.clear()
        self.status_filter.setCurrentIndex(0)
        self.improvement_filter.setValue(0)
        self.model.set_batch(batch)
        self.count_label.setText(
            f"成功 {batch.succeeded_count} / 失败 {batch.failed_count} / "
            f"跳过 {batch.skipped_count} / 取消 {batch.cancelled_count}"
        )
        self.elapsed_label.setText(f"总耗时：{batch.elapsed_seconds:.3f} s")
        self.output_label.setText(f"输出目录：{batch.output_directory}")
        self.output_label.setToolTip(str(batch.output_directory))
        self.open_output_button.setEnabled(True)
        self.table.resizeColumnsToContents()
        first_success = next(
            (
                item.network_id
                for item in batch.network_results
                if item.status is NetworkRunStatus.SUCCEEDED
            ),
            None,
        )
        if first_success is not None:
            self.select_network_id(first_success)
        else:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
            self.network_selected.emit(None)

    def clear(self) -> None:
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.model.clear()
        self.count_label.setText("成功 0 / 失败 0 / 跳过 0 / 取消 0")
        self.elapsed_label.setText("总耗时：—")
        self.output_label.setText("输出目录：—")
        self.output_label.setToolTip("")
        self.open_output_button.setEnabled(False)
        self.network_selected.emit(None)

    def selected_network_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        source_index = self.proxy.mapToSource(rows[0])
        return self.model.network_id_at(source_index.row())

    def selected_network(self) -> NetworkBatchResult | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        source_index = self.proxy.mapToSource(rows[0])
        return self.model.network_at(source_index.row())

    def select_network_id(self, network_id: str) -> bool:
        for source_row in range(self.model.rowCount()):
            if self.model.network_id_at(source_row) != network_id:
                continue
            proxy_index = self.proxy.mapFromSource(self.model.index(source_row, 0))
            if not proxy_index.isValid():
                return False
            self.table.setCurrentIndex(proxy_index)
            self.table.selectRow(proxy_index.row())
            return True
        return False

    def _update_status_filter(self) -> None:
        value = self.status_filter.currentData()
        status = None
        if value is not None:
            status = value if isinstance(value, NetworkRunStatus) else NetworkRunStatus(value)
        self.proxy.set_status(status)

    def _selection_changed(self, selected: object, deselected: object) -> None:
        del selected, deselected
        self.network_selected.emit(self.selected_network_id())
