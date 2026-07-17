from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from canfd_offset_optimizer.gui.contracts import GuiOptimizationResult
from canfd_offset_optimizer.gui.view_models import (
    AssignmentFilterProxyModel,
    AssignmentTableModel,
    metric_rows,
)
from canfd_offset_optimizer.gui.widgets.assignment_table import AssignmentTable


def test_metrics_and_assignment_filter_sort_use_result_data_without_mutation(
    qapp, gui_result: GuiOptimizationResult
) -> None:
    original_assignments = gui_result.assignments
    rows = metric_rows(gui_result)
    assert [row.label for row in rows] == ["Zss", "Qss", "标准差", "Zst", "Qst", "Nvio", "Vvio"]
    assert rows[0].original == "648"

    model = AssignmentTableModel()
    proxy = AssignmentFilterProxyModel(model)
    model.set_assignments(gui_result.assignments)
    proxy.set_changed_only(True)
    assert proxy.rowCount() == sum(row.change_us != 0 for row in gui_result.assignments)
    proxy.set_query("Message_02")
    assert proxy.rowCount() == 1
    proxy.set_changed_only(False)
    proxy.set_query("")
    proxy.sort(1, Qt.SortOrder.DescendingOrder)
    qapp.processEvents()
    assert proxy.index(0, 1).data(Qt.ItemDataRole.UserRole) == max(
        row.can_id for row in gui_result.assignments
    )
    assert gui_result.assignments is original_assignments
    with pytest.raises(FrozenInstanceError):
        gui_result.actual_attempts = 99  # type: ignore[misc]


def test_assignment_table_copies_selected_rows(qtbot, gui_result: GuiOptimizationResult) -> None:
    widget = AssignmentTable()
    qtbot.addWidget(widget)
    widget.set_result(gui_result)
    assert not widget.copy_button.isEnabled()

    widget.table.selectRow(0)
    qtbot.waitUntil(widget.copy_button.isEnabled)
    selected_message = str(widget.proxy.index(0, 0).data())
    widget.copy_selected_rows()

    clipboard = QGuiApplication.clipboard().text()
    assert clipboard.startswith("报文\tCAN ID")
    assert selected_message in clipboard
