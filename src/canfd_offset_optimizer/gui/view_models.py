"""Qt models built exclusively from immutable GUI DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from .contracts import GuiOptimizationResult, OffsetAssignmentRow
from .formatting import format_can_id, format_integer, format_milliseconds


@dataclass(frozen=True, slots=True)
class MetricComparisonRow:
    label: str
    original: str
    optimized: str
    tooltip: str


def metric_rows(result: GuiOptimizationResult) -> tuple[MetricComparisonRow, ...]:
    before = result.original_metrics
    after = result.optimized_metrics
    return (
        MetricComparisonRow(
            "Zss", format_integer(before.zss), format_integer(after.zss), "稳态时隙峰值负载"
        ),
        MetricComparisonRow(
            "Qss", format_integer(before.qss), format_integer(after.qss), "稳态时隙负载平方和"
        ),
        MetricComparisonRow(
            "标准差",
            f"{before.standard_deviation:.3f}",
            f"{after.standard_deviation:.3f}",
            "稳态时隙负载标准差",
        ),
        MetricComparisonRow(
            "Zst", format_integer(before.zst), format_integer(after.zst), "启动窗口峰值负载"
        ),
        MetricComparisonRow(
            "Qst", format_integer(before.qst), format_integer(after.qst), "启动窗口负载平方和"
        ),
        MetricComparisonRow(
            "Nvio", str(before.nvio), str(after.nvio), "超过物理阈值的稳态时隙数量"
        ),
        MetricComparisonRow(
            "Vvio", format_integer(before.vvio), format_integer(after.vvio), "稳态阈值总超限量"
        ),
    )


class AssignmentTableModel(QAbstractTableModel):
    """Read-only table model that copies only the result tuple reference."""

    HEADERS: Final[tuple[str, ...]] = (
        "报文",
        "CAN ID",
        "周期(ms)",
        "原 Offset(ms)",
        "新 Offset(ms)",
        "变化(ms)",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[OffsetAssignmentRow, ...] = ()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        raw: tuple[object, ...] = (
            row.message_name,
            row.can_id,
            row.cycle_time_us,
            row.original_offset_us,
            row.optimized_offset_us,
            row.change_us,
        )
        if role == int(Qt.ItemDataRole.UserRole):
            return raw[index.column()]
        if role == int(Qt.ItemDataRole.TextAlignmentRole) and index.column() >= 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        display: tuple[str, ...] = (
            row.message_name,
            format_can_id(row.can_id),
            format_milliseconds(row.cycle_time_us),
            format_milliseconds(row.original_offset_us),
            format_milliseconds(row.optimized_offset_us),
            format_milliseconds(row.change_us),
        )
        return display[index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if role == int(Qt.ItemDataRole.DisplayRole) and orientation is Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def set_assignments(self, rows: tuple[OffsetAssignmentRow, ...]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def assignment_at(self, row: int) -> OffsetAssignmentRow:
        return self._rows[row]


class AssignmentFilterProxyModel(QSortFilterProxyModel):
    """Filter by text and changed-only while sorting on raw values."""

    def __init__(self, source: AssignmentTableModel) -> None:
        super().__init__()
        self._query = ""
        self._changed_only = False
        self.setSourceModel(source)
        self.setSortRole(int(Qt.ItemDataRole.UserRole))
        self.setDynamicSortFilter(True)

    def set_query(self, query: str) -> None:
        self._query = query.strip().casefold()
        self._invalidate_rows()

    def set_changed_only(self, enabled: bool) -> None:
        self._changed_only = enabled
        self._invalidate_rows()

    def _invalidate_rows(self) -> None:
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # PySide6 6.7/6.8 compatibility.
            self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        source = cast(AssignmentTableModel, self.sourceModel())
        row = source.assignment_at(source_row)
        if self._changed_only and row.change_us == 0:
            return False
        if not self._query:
            return True
        return (
            self._query in row.message_name.casefold()
            or self._query in format_can_id(row.can_id).casefold()
        )
