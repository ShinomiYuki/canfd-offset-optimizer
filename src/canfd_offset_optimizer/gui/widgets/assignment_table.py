"""Sortable and filterable Offset assignment table."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..contracts import GuiOptimizationResult
from ..view_models import AssignmentFilterProxyModel, AssignmentTableModel


class AssignmentTable(QWidget):
    export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("按报文名或 CAN ID 筛选")
        self.changed_only_check = QCheckBox("只看已修改报文")
        self.copy_button = QPushButton("复制选中行")
        self.export_button = QPushButton("导出 Offset CSV")
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.model = AssignmentTableModel()
        self.proxy = AssignmentFilterProxyModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        controls = QHBoxLayout()
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(self.changed_only_check)
        controls.addWidget(self.copy_button)
        controls.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table, 1)
        self.filter_edit.textChanged.connect(self.proxy.set_query)
        self.changed_only_check.toggled.connect(self.proxy.set_changed_only)
        self.copy_button.clicked.connect(self.copy_selected_rows)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.table.selectionModel().selectionChanged.connect(self._update_copy_enabled)
        self._copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self._copy_shortcut.activated.connect(self.copy_selected_rows)

    def set_result(self, result: GuiOptimizationResult) -> None:
        self.model.set_assignments(result.assignments)
        self.table.resizeColumnsToContents()
        self.export_button.setEnabled(True)
        self._update_copy_enabled()

    def _update_copy_enabled(self) -> None:
        self.copy_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def copy_selected_rows(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        lines = ["\t".join(AssignmentTableModel.HEADERS)]
        for row in rows:
            cells: list[str] = []
            for column in range(self.proxy.columnCount()):
                value = self.proxy.index(row, column).data()
                cells.append(str(value))
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines))
