"""Qt models built exclusively from immutable GUI batch DTOs."""

from __future__ import annotations

from typing import Final, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from .contracts import (
    BatchOptimizationResult,
    ImportRecord,
    ImportSession,
    NetworkBatchResult,
    NetworkRunStatus,
    OffsetAssignmentRow,
    WorkspaceInspection,
)
from .formatting import format_can_id, format_integer, format_milliseconds


class BatchSummaryTableModel(QAbstractTableModel):
    """Read-only project summary with raw values available for sorting."""

    NETWORK_ID_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 1

    HEADERS: Final[tuple[str, ...]] = (
        "网段",
        "来源 DBC",
        "状态",
        "模式",
        "原始 Zss",
        "优化后 Zss",
        "原始 Qss",
        "优化后 Qss",
        "标准差",
        "Zss 改善",
        "Attempts",
        "停止原因",
        "耗时(s)",
        "警告",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[NetworkBatchResult, ...] = ()

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
        item = self._rows[index.row()]
        result = item.result
        raw: tuple[object | None, ...] = (
            item.network_name,
            item.source_file,
            item.status.value,
            item.mode.value,
            result.original_metrics.zss if result else None,
            result.optimized_metrics.zss if result else None,
            result.original_metrics.qss if result else None,
            result.optimized_metrics.qss if result else None,
            result.optimized_metrics.standard_deviation if result else None,
            item.zss_improvement,
            result.actual_attempts if result else None,
            result.stop_reason if result else None,
            result.elapsed_seconds if result else None,
            len(item.warnings),
        )
        if role == self.NETWORK_ID_ROLE:
            return item.network_id
        if role == int(Qt.ItemDataRole.UserRole):
            return raw[index.column()]
        if role == int(Qt.ItemDataRole.ToolTipRole) and index.column() in {0, 1}:
            return (
                f"显示名称：{item.display_name}\n"
                f"network_id：{item.network_id}\n来源 DBC：{item.source_file}"
            )
        if role == int(Qt.ItemDataRole.TextAlignmentRole) and index.column() >= 4:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        status_labels = {
            NetworkRunStatus.SUCCEEDED: "成功",
            NetworkRunStatus.FAILED: "失败",
            NetworkRunStatus.SKIPPED: "跳过",
            NetworkRunStatus.CANCELLED: "取消",
        }
        display: tuple[str, ...] = (
            item.network_name,
            item.source_file,
            status_labels[item.status],
            item.mode.value,
            format_integer(result.original_metrics.zss) if result else "—",
            format_integer(result.optimized_metrics.zss) if result else "—",
            format_integer(result.original_metrics.qss) if result else "—",
            format_integer(result.optimized_metrics.qss) if result else "—",
            f"{result.optimized_metrics.standard_deviation:.3f}" if result else "—",
            format_integer(item.zss_improvement) if item.zss_improvement is not None else "—",
            str(result.actual_attempts) if result else "—",
            result.stop_reason if result else "—",
            f"{result.elapsed_seconds:.3f}" if result else "—",
            str(len(item.warnings)),
        )
        return display[index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if role == int(Qt.ItemDataRole.DisplayRole) and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def set_batch(self, batch: BatchOptimizationResult) -> None:
        self.beginResetModel()
        self._rows = batch.network_results
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = ()
        self.endResetModel()

    def network_at(self, row: int) -> NetworkBatchResult:
        return self._rows[row]

    def network_id_at(self, row: int) -> str:
        return self._rows[row].network_id


class BatchSummaryFilterProxy(QSortFilterProxyModel):
    """Filter summary by network, final status and minimum Zss improvement."""

    def __init__(self, source: BatchSummaryTableModel) -> None:
        super().__init__()
        self._query = ""
        self._status: NetworkRunStatus | None = None
        self._minimum_improvement = 0
        self.setSourceModel(source)
        self.setSortRole(int(Qt.ItemDataRole.UserRole))
        self.setDynamicSortFilter(True)

    def set_query(self, query: str) -> None:
        self._query = query.strip().casefold()
        self._invalidate_rows()

    def set_status(self, status: NetworkRunStatus | None) -> None:
        self._status = status
        self._invalidate_rows()

    def set_minimum_improvement(self, value: int) -> None:
        self._minimum_improvement = value
        self._invalidate_rows()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        del source_parent
        source = cast(BatchSummaryTableModel, self.sourceModel())
        item = source.network_at(source_row)
        searchable = "\n".join(
            (item.network_name, item.display_name, item.source_file, item.network_id)
        ).casefold()
        if self._query and self._query not in searchable:
            return False
        if self._status is not None and item.status is not self._status:
            return False
        improvement = item.zss_improvement
        if improvement is None:
            return self._minimum_improvement == 0
        return improvement >= self._minimum_improvement

    def _invalidate_rows(self) -> None:
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # PySide6 6.7/6.8 compatibility.
            self.invalidateFilter()


class NetworkDetailsTableModel(QAbstractTableModel):
    """Read-only projection of the current WorkspaceInspection object."""

    HEADERS: Final[tuple[str, ...]] = (
        "序号",
        "网段显示名称",
        "network_id",
        "来源 DBC",
        "可优化",
        "报文数量",
        "警告或不可优化原因",
    )

    def __init__(self) -> None:
        super().__init__()
        self._inspection: WorkspaceInspection | None = None

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._inspection is None:
            return 0
        return len(self._inspection.networks)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if self._inspection is None or not index.isValid():
            return None
        network = self._inspection.networks[index.row()]
        if role == int(Qt.ItemDataRole.UserRole):
            return network.network_id
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return str(network.source_workspace_path)
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        reason = "；".join(network.warnings)
        if network.unoptimizable_reason:
            reason = "；".join(filter(None, (reason, network.unoptimizable_reason)))
        values = (
            str(index.row() + 1),
            network.display_name,
            network.network_id,
            network.source_file,
            "是" if network.is_optimizable else "否",
            str(network.message_count),
            reason or "—",
        )
        return values[index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if role == int(Qt.ItemDataRole.DisplayRole) and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def set_inspection(self, inspection: WorkspaceInspection | None) -> None:
        self.beginResetModel()
        self._inspection = inspection
        self.endResetModel()


class ImportDetailsTableModel(QAbstractTableModel):
    """Read-only projection of the current ImportSession object."""

    HEADERS: Final[tuple[str, ...]] = (
        "检测类型",
        "导入状态",
        "原始路径",
        "工作区副本路径",
        "文件 hash",
        "说明",
    )

    def __init__(self) -> None:
        super().__init__()
        self._session: ImportSession | None = None

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._session is None:
            return 0
        return len(self._session.records)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        record = self._record(index)
        if record is None:
            return None
        if role == int(Qt.ItemDataRole.UserRole):
            return str(record.original_path)
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return str(record.original_path)
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        values = (
            record.kind.value,
            record.status.value,
            str(record.original_path),
            record.workspace_relative_path.as_posix()
            if record.workspace_relative_path is not None
            else "—",
            record.sha256 or "—",
            record.note or "—",
        )
        return values[index.column()]

    def _record(self, index: QModelIndex | QPersistentModelIndex) -> ImportRecord | None:
        if self._session is None or not index.isValid():
            return None
        if not 0 <= index.row() < len(self._session.records):
            return None
        return self._session.records[index.row()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if role == int(Qt.ItemDataRole.DisplayRole) and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def set_session(self, session: ImportSession | None) -> None:
        self.beginResetModel()
        self._session = session
        self.endResetModel()


class AssignmentTableModel(QAbstractTableModel):
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
        display = (
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
        if role == int(Qt.ItemDataRole.DisplayRole) and orientation == Qt.Orientation.Horizontal:
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

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        del source_parent
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

    def _invalidate_rows(self) -> None:
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # PySide6 6.7/6.8 compatibility.
            self.invalidateFilter()
