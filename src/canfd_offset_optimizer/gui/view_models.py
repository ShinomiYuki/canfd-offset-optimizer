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
    DbcSenderSelectionSummary,
    ImportRecord,
    ImportSession,
    InputKind,
    MessageEligibilityRecord,
    MessageEligibilityStatus,
    NetworkBatchResult,
    NetworkRunStatus,
    OffsetAssignmentRow,
    RouteExclusionStatus,
    RouteMatchRecord,
    RouteMatchStatus,
    RouteRecordIssue,
    SenderSelectionDbcStatus,
    WorkspaceInspection,
)
from .formatting import (
    format_can_id,
    format_integer,
    format_milliseconds,
    format_result_weight,
    format_weight_mode,
)


class BatchSummaryTableModel(QAbstractTableModel):
    """Read-only project summary with raw values available for sorting."""

    NETWORK_ID_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 1

    HEADERS: Final[tuple[str, ...]] = (
        "网段",
        "来源 DBC",
        "状态",
        "总线类型",
        "模式",
        "权重口径",
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
            result.frame_protocol.value if result else None,
            item.mode.value,
            item.weight_mode.value,
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
        if role == int(Qt.ItemDataRole.TextAlignmentRole) and index.column() >= 6:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        status_labels = {
            NetworkRunStatus.SUCCEEDED: "成功",
            NetworkRunStatus.FAILED: "失败",
            NetworkRunStatus.SKIPPED: "跳过",
            NetworkRunStatus.CANCELLED: "取消",
        }
        status_text = status_labels[item.status]
        if result is not None and result.dbc_write_error is not None:
            status_text = "成功（DBC写回失败）"
        display: tuple[str, ...] = (
            item.network_name,
            item.source_file,
            status_text,
            result.frame_protocol.value if result else "—",
            item.mode.value,
            format_result_weight(result) if result else format_weight_mode(item.weight_mode),
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
        "DBC 报文总数",
        "所选本机节点",
        "本机节点发送报文",
        "基础合资格报文",
        "其他 ECU 排除",
        "路由排除",
        "最终参与优化",
        "可优化",
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
            str(network.dbc_message_count),
            "、".join(network.selected_transmitters) or "—",
            str(network.selected_transmitter_message_count),
            str(
                network.message_count
                if network.base_eligible_message_count is None
                else network.base_eligible_message_count
            ),
            str(network.unselected_transmitter_excluded_count),
            str(network.routing_excluded_count),
            str(
                network.message_count
                if network.final_eligible_message_count is None
                else network.final_eligible_message_count
            ),
            "是" if network.is_optimizable else "否",
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
        kind_label = (
            "路由报文排除表"
            if record.kind is InputKind.ROUTING_TABLE
            else record.kind.value
        )
        values = (
            kind_label,
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


class RouteExclusionTableModel(QAbstractTableModel):
    """Every routing workbook row with its exact matching audit."""

    HEADERS: Final[tuple[str, ...]] = (
        "目标网段",
        "CAN ID",
        "Excel 报文名",
        "DBC 报文名",
        "匹配状态",
        "处理结果",
        "Excel 来源文件",
        "Sheet",
        "行号",
        "说明",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[RouteMatchRecord, ...] = ()

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
        record = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.UserRole):
            return record
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return record.note
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        status_labels = {
            RouteMatchStatus.MATCHED: "已匹配",
            RouteMatchStatus.NOT_FOUND: "未找到",
            RouteMatchStatus.AMBIGUOUS: "匹配歧义",
            RouteMatchStatus.INVALID_CAN_ID: "CAN ID 无效",
        }
        exclusion_labels = {
            RouteExclusionStatus.EXCLUDED: "已排除",
            RouteExclusionStatus.ALREADY_EXCLUDED: "重复记录，已排除",
            RouteExclusionStatus.NOT_EXCLUDED: "未排除",
        }
        issue_text = "、".join(issue.value for issue in record.issues)
        values = (
            record.route.target_network_raw or "—",
            record.route.can_id_raw or "—",
            record.route.message_name or "—",
            record.dbc_message_name or "—",
            status_labels[record.match_status],
            exclusion_labels[record.exclusion_status],
            record.route.source_file,
            record.route.sheet_name,
            str(record.route.row_number),
            "；".join(filter(None, (record.note, issue_text))) or "—",
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
        self._rows = (
            () if inspection is None else inspection.routing_exclusion.records
        )
        self.endResetModel()

    def record_at(self, row: int) -> RouteMatchRecord:
        return self._rows[row]


class RouteExclusionFilterProxy(QSortFilterProxyModel):
    """Named filters used by the routing details tab."""

    def __init__(self, source: RouteExclusionTableModel) -> None:
        super().__init__()
        self._filter_name = "all"
        self.setSourceModel(source)

    def set_filter_name(self, value: str) -> None:
        self._filter_name = value
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        del source_parent
        source = cast(RouteExclusionTableModel, self.sourceModel())
        record = source.record_at(source_row)
        if self._filter_name == "excluded":
            return record.match_status is RouteMatchStatus.MATCHED
        if self._filter_name == "not_found":
            return record.match_status in {
                RouteMatchStatus.NOT_FOUND,
                RouteMatchStatus.INVALID_CAN_ID,
            }
        if self._filter_name == "ambiguous":
            return record.match_status is RouteMatchStatus.AMBIGUOUS
        if self._filter_name == "name_mismatch":
            return RouteRecordIssue.NAME_MISMATCH_WARNING in record.issues
        if self._filter_name == "duplicate":
            return any(
                issue
                in {
                    RouteRecordIssue.DUPLICATE,
                    RouteRecordIssue.DUPLICATE_CONFLICT_WARNING,
                }
                for issue in record.issues
            )
        return True


class SenderSelectionSummaryTableModel(QAbstractTableModel):
    """Per-DBC local-transmitter selection and eligibility audit."""

    HEADERS: Final[tuple[str, ...]] = (
        "DBC 文件",
        "网段",
        "发送节点数",
        "所选本机节点",
        "用户排除",
        "DBC 报文总数",
        "本机节点发送",
        "基础合资格",
        "其他 ECU 排除",
        "路由排除",
        "最终参与优化",
        "状态",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[DbcSenderSelectionSummary, ...] = ()

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
        if role == int(Qt.ItemDataRole.UserRole):
            return item.dbc_id
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return f"dbc_id：{item.dbc_id}\nSHA-256：{item.sha256}\n{item.note}"
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        statuses = {
            SenderSelectionDbcStatus.UNPROCESSED: "未处理",
            SenderSelectionDbcStatus.SELECTED: "已选择节点",
            SenderSelectionDbcStatus.EXCLUDED_BY_USER: "明确不参与优化",
            SenderSelectionDbcStatus.NO_IDENTIFIABLE_TRANSMITTER: "无可识别发送节点",
            SenderSelectionDbcStatus.INPUT_ERROR: "输入异常",
        }
        values = (
            item.dbc_file,
            item.network_name,
            str(len(item.node_stats)),
            "、".join(item.selected_transmitters) or "—",
            "是" if item.excluded_by_user else "否",
            str(item.message_count),
            str(item.selected_sender_message_count),
            str(item.base_eligible_count),
            str(item.unselected_transmitter_count),
            str(item.routing_excluded_count),
            str(item.final_eligible_count),
            statuses[item.status],
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
        self._rows = () if inspection is None else inspection.sender_selection_summaries
        self.endResetModel()


class MessageEligibilityTableModel(QAbstractTableModel):
    """Every DBC message with the final reason it did or did not enter GCLS."""

    HEADERS: Final[tuple[str, ...]] = (
        "DBC",
        "网段",
        "CAN ID",
        "报文名",
        "DBC 发送节点",
        "命中所选节点",
        "周期(ms)",
        "总线类型",
        "命中路由表",
        "最终状态",
        "排除原因",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[MessageEligibilityRecord, ...] = ()

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
        if role == int(Qt.ItemDataRole.UserRole):
            return item
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return item.exclusion_reason
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None
        labels = {
            MessageEligibilityStatus.FINAL_ELIGIBLE: "参与优化",
            MessageEligibilityStatus.BASE_ELIGIBLE: "等待发送节点选择",
            MessageEligibilityStatus.EXCLUDED_UNSELECTED_TRANSMITTER: "排除：发送节点未选择",
            MessageEligibilityStatus.EXCLUDED_BY_USER: "排除：用户排除该 DBC",
            MessageEligibilityStatus.NON_PERIODIC: "排除：非周期报文",
            MessageEligibilityStatus.UNSUPPORTED_SEND_TYPE: "排除：不支持的发送类型/资格",
            MessageEligibilityStatus.ROUTING_EXCLUDED: "排除：路由报文",
            MessageEligibilityStatus.NO_VALID_TRANSMITTER: "排除：无有效发送节点",
            MessageEligibilityStatus.INPUT_ERROR: "排除：输入异常",
        }
        values = (
            item.dbc_file,
            item.network_name,
            format_can_id(item.can_id) if item.can_id is not None else "—",
            item.message_name,
            "、".join(item.transmitter_nodes) or "—",
            "是" if item.selected_transmitter_match else "否",
            format_milliseconds(item.cycle_time_us) if item.cycle_time_us is not None else "—",
            item.frame_protocol.value if item.frame_protocol is not None else "—",
            "是" if item.routing_match else "否",
            labels[item.final_status],
            item.exclusion_reason or "—",
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
        self._rows = (
            ()
            if inspection is None
            else tuple(
                message
                for summary in inspection.sender_selection_summaries
                for message in summary.messages
            )
        )
        self.endResetModel()

    def record_at(self, row: int) -> MessageEligibilityRecord:
        return self._rows[row]


class MessageEligibilityFilterProxy(QSortFilterProxyModel):
    """Named audit filters used by the sender-selection details tab."""

    def __init__(self, source: MessageEligibilityTableModel) -> None:
        super().__init__()
        self._filter_name = "all"
        self.setSourceModel(source)

    def set_filter_name(self, value: str) -> None:
        self._filter_name = value
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        del source_parent
        source = cast(MessageEligibilityTableModel, self.sourceModel())
        record = source.record_at(source_row)
        if self._filter_name == "final":
            return record.final_status is MessageEligibilityStatus.FINAL_ELIGIBLE
        if self._filter_name == "unselected":
            return record.final_status is MessageEligibilityStatus.EXCLUDED_UNSELECTED_TRANSMITTER
        if self._filter_name == "routing":
            return record.final_status is MessageEligibilityStatus.ROUTING_EXCLUDED
        if self._filter_name == "non_periodic":
            return record.final_status is MessageEligibilityStatus.NON_PERIODIC
        if self._filter_name == "error":
            return record.final_status in {
                MessageEligibilityStatus.INPUT_ERROR,
                MessageEligibilityStatus.NO_VALID_TRANSMITTER,
                MessageEligibilityStatus.UNSUPPORTED_SEND_TYPE,
            }
        return True


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
