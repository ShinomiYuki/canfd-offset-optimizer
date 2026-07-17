from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    NetworkBatchResult,
    NetworkRunStatus,
)
from canfd_offset_optimizer.gui.view_models import (
    AssignmentFilterProxyModel,
    AssignmentTableModel,
    BatchSummaryFilterProxy,
    BatchSummaryTableModel,
)
from canfd_offset_optimizer.gui.widgets.assignment_table import AssignmentTable


def _mixed_batch(batch: BatchOptimizationResult) -> BatchOptimizationResult:
    successful = batch.network_results[0]
    failed = NetworkBatchResult(
        network_id=batch.network_results[1].network_id,
        network_name=batch.network_results[1].network_name,
        display_name=batch.network_results[1].display_name,
        source_file=batch.network_results[1].source_file,
        status=NetworkRunStatus.FAILED,
        weight_mode=successful.weight_mode,
        mode=successful.mode,
        error="failure",
    )
    return replace(batch, network_results=(successful, failed, batch.network_results[2]))


def test_batch_summary_filter_and_sort_use_raw_values(
    qapp, batch_result: BatchOptimizationResult
) -> None:
    batch = _mixed_batch(batch_result)
    model = BatchSummaryTableModel()
    proxy = BatchSummaryFilterProxy(model)
    model.set_batch(batch)
    assert model.columnCount() == 14
    assert proxy.rowCount() == 3

    proxy.set_query(batch.network_results[0].network_name)
    assert proxy.rowCount() == 1
    proxy.set_query("")
    proxy.set_status(NetworkRunStatus.FAILED)
    assert proxy.rowCount() == 1
    proxy.set_status(None)
    proxy.set_minimum_improvement(1)
    assert proxy.rowCount() == 2  # failed rows have no improvement and are excluded
    proxy.sort(4, Qt.SortOrder.DescendingOrder)
    qapp.processEvents()
    values = [
        proxy.index(row, 4).data(Qt.ItemDataRole.UserRole)
        for row in range(proxy.rowCount())
    ]
    assert values == sorted(values, reverse=True)


def test_each_summary_row_reads_its_own_network_result(
    qapp, batch_result: BatchOptimizationResult
) -> None:
    del qapp
    model = BatchSummaryTableModel()
    model.set_batch(batch_result)
    seen_metrics: set[tuple[object, ...]] = set()
    for row, item in enumerate(batch_result.network_results):
        result = item.result
        assert result is not None
        raw = tuple(
            model.index(row, column).data(Qt.ItemDataRole.UserRole)
            for column in range(model.columnCount())
        )
        assert raw[0] == item.network_name
        assert raw[1] == item.source_file
        assert raw[4] == result.original_metrics.zss
        assert raw[5] == result.optimized_metrics.zss
        assert raw[8] == result.optimized_metrics.standard_deviation
        assert raw[9] == result.original_metrics.zss - result.optimized_metrics.zss
        assert raw[10] == result.actual_attempts
        assert raw[11] == result.stop_reason
        assert raw[12] == result.elapsed_seconds
        assert (
            model.index(row, 0).data(BatchSummaryTableModel.NETWORK_ID_ROLE)
            == item.network_id
        )
        seen_metrics.add(raw[4:13])
    assert len(seen_metrics) == len(batch_result.network_results)


def test_assignment_filter_copy_and_dtos_remain_immutable(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = batch_result.network_results[0].result
    assert result is not None
    original_assignments = result.assignments
    model = AssignmentTableModel()
    proxy = AssignmentFilterProxyModel(model)
    model.set_assignments(result.assignments)
    proxy.set_changed_only(True)
    assert proxy.rowCount() == sum(row.change_us != 0 for row in result.assignments)
    changed = next(row for row in result.assignments if row.change_us != 0)
    proxy.set_query(changed.message_name)
    assert proxy.rowCount() == 1

    widget = AssignmentTable()
    qtbot.addWidget(widget)
    widget.set_result(result)
    widget.table.selectRow(0)
    qtbot.waitUntil(widget.copy_button.isEnabled)
    selected_message = str(widget.proxy.index(0, 0).data())
    widget.copy_selected_rows()
    clipboard = QGuiApplication.clipboard().text()
    assert clipboard.startswith("报文\tCAN ID")
    assert selected_message in clipboard
    assert result.assignments is original_assignments
    with pytest.raises(FrozenInstanceError):
        result.actual_attempts = 99  # type: ignore[misc]
