"""Per-DBC local transmitter selection dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..contracts import (
    DbcSenderSelectionSummary,
    SenderNodeSelectionConfig,
    SenderSelectionDbcStatus,
    WorkspaceInspection,
)
from ..sender_selection import (
    apply_selection_to_summary,
    validate_complete_selection,
)


_STATUS_LABELS = {
    SenderSelectionDbcStatus.UNPROCESSED: "未处理",
    SenderSelectionDbcStatus.SELECTED: "已选择节点",
    SenderSelectionDbcStatus.EXCLUDED_BY_USER: "明确不参与优化",
    SenderSelectionDbcStatus.NO_IDENTIFIABLE_TRANSMITTER: "无可识别发送节点",
    SenderSelectionDbcStatus.INPUT_ERROR: "输入异常",
}


class SenderSelectionDialog(QDialog):
    """Edit a draft selection and publish it only after explicit Apply."""

    def __init__(
        self,
        inspection: WorkspaceInspection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DBC 发送节点筛选")
        self.resize(1_180, 680)
        self._inspection = inspection
        self._summaries = inspection.sender_selection_summaries
        current = inspection.sender_selection
        self._selected: dict[str, set[str]] = {
            dbc_id: set(names)
            for dbc_id, names in current.selected_transmitters_by_dbc.items()
        }
        self._excluded = set(current.excluded_dbc_ids)
        self._selection_config: SenderNodeSelectionConfig | None = None
        self._updating = False

        self.dbc_table = QTableWidget(len(self._summaries), 7)
        self.dbc_table.setHorizontalHeaderLabels(
            (
                "DBC 文件",
                "网段",
                "状态",
                "已选节点",
                "所选节点报文",
                "有效周期候选",
                "说明",
            )
        )
        self.dbc_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.dbc_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.dbc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.node_table = QTableWidget(0, 8)
        self.node_table.setHorizontalHeaderLabels(
            (
                "选择",
                "发送节点",
                "报文总数",
                "有效周期",
                "Classic CAN",
                "CAN FD",
                "基础候选",
                "说明/警告",
            )
        )
        self.node_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.node_table.itemChanged.connect(self._on_node_item_changed)

        self.exclude_check = QCheckBox("该 DBC 不参与本次优化")
        self.exclude_check.toggled.connect(self._on_excluded_toggled)
        self.select_same_button = QPushButton("在其他 DBC 中选择同名节点")
        self.clear_current_button = QPushButton("清除当前 DBC 选择")
        self.clear_all_button = QPushButton("清除全部选择")
        self.select_same_button.clicked.connect(self._select_same_names)
        self.clear_current_button.clicked.connect(self._clear_current)
        self.clear_all_button.clicked.connect(self._clear_all)
        actions = QHBoxLayout()
        actions.addWidget(self.exclude_check)
        actions.addStretch(1)
        actions.addWidget(self.select_same_button)
        actions.addWidget(self.clear_current_button)
        actions.addWidget(self.clear_all_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("当前 DBC 中发现的发送节点"))
        right_layout.addWidget(self.node_table, 1)
        right_layout.addLayout(actions)
        splitter = QSplitter()
        splitter.addWidget(self.dbc_table)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b00020;")
        self.apply_button = QPushButton("应用选择")
        self.cancel_button = QPushButton("取消")
        self.apply_button.clicked.connect(self._apply)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "请为每个 DBC 明确选择一个或多个本机发送节点，或明确排除该 DBC。"
                "所有节点默认不选择。"
            )
        )
        layout.addWidget(splitter, 1)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.validation_label)
        layout.addLayout(buttons)

        self.dbc_table.itemSelectionChanged.connect(self._show_current_dbc)
        self._refresh_dbc_table()
        if self._summaries:
            self.dbc_table.selectRow(0)
        self._refresh_validation()

    @property
    def selection_config(self) -> SenderNodeSelectionConfig | None:
        return self._selection_config

    def _draft_config(self, *, confirmed: bool = False) -> SenderNodeSelectionConfig:
        return SenderNodeSelectionConfig(
            selected_transmitters_by_dbc={
                dbc_id: frozenset(names)
                for dbc_id, names in self._selected.items()
                if names and dbc_id not in self._excluded
            },
            excluded_dbc_ids=frozenset(self._excluded),
            confirmed=confirmed,
            dbc_revision=self._inspection.dbc_revision,
        )

    def _current_summary(self) -> DbcSenderSelectionSummary | None:
        row = self.dbc_table.currentRow()
        return self._summaries[row] if 0 <= row < len(self._summaries) else None

    def _refresh_dbc_table(self) -> None:
        config = self._draft_config()
        self._updating = True
        try:
            for row, raw_summary in enumerate(self._summaries):
                summary = apply_selection_to_summary(raw_summary, config)
                selected_count = len(summary.selected_transmitters)
                status = summary.status
                if not selected_count and not summary.excluded_by_user:
                    status = raw_summary.status
                values = (
                    summary.dbc_file,
                    summary.network_name,
                    _STATUS_LABELS[status],
                    str(selected_count),
                    str(summary.selected_sender_message_count),
                    str(summary.base_eligible_count),
                    summary.note or "—",
                )
                for column, value in enumerate(values):
                    self.dbc_table.setItem(row, column, QTableWidgetItem(value))
        finally:
            self._updating = False
        self.dbc_table.resizeColumnsToContents()

    def _show_current_dbc(self) -> None:
        summary = self._current_summary()
        if summary is None:
            return
        self._updating = True
        try:
            self.node_table.setRowCount(len(summary.node_stats))
            selected = self._selected.get(summary.dbc_id, set())
            excluded = summary.dbc_id in self._excluded
            for row, stats in enumerate(summary.node_stats):
                check = QTableWidgetItem()
                flags = Qt.ItemFlag.ItemIsSelectable
                if stats.selectable:
                    flags |= Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                check.setFlags(flags)
                if not stats.selectable:
                    check.setToolTip(stats.note)
                check.setCheckState(
                    Qt.CheckState.Checked
                    if stats.node_name in selected
                    else Qt.CheckState.Unchecked
                )
                check.setData(Qt.ItemDataRole.UserRole, stats.node_name)
                self.node_table.setItem(row, 0, check)
                values = (
                    stats.node_name,
                    str(stats.message_count),
                    str(stats.valid_periodic_count),
                    str(stats.classic_can_count),
                    str(stats.can_fd_count),
                    str(stats.base_candidate_count),
                    stats.note or "—",
                )
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(value)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.node_table.setItem(row, column, item)
            self.exclude_check.setChecked(excluded)
            self.node_table.setEnabled(not excluded)
        finally:
            self._updating = False
        self.node_table.resizeColumnsToContents()
        self._refresh_preview()

    def _on_node_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        summary = self._current_summary()
        if summary is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        selected = self._selected.setdefault(summary.dbc_id, set())
        if item.checkState() == Qt.CheckState.Checked:
            selected.add(name)
        else:
            selected.discard(name)
        if not selected:
            self._selected.pop(summary.dbc_id, None)
        self._refresh_after_edit()

    def _on_excluded_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        summary = self._current_summary()
        if summary is None:
            return
        if checked:
            self._excluded.add(summary.dbc_id)
            self._selected.pop(summary.dbc_id, None)
        else:
            self._excluded.discard(summary.dbc_id)
        self._refresh_after_edit(rebuild_nodes=True)

    def _select_same_names(self) -> None:
        summary = self._current_summary()
        if summary is None:
            return
        names = self._selected.get(summary.dbc_id, set())
        if not names:
            return
        for other in self._summaries:
            if other.dbc_id in self._excluded:
                continue
            available = {
                item.node_name for item in other.node_stats if item.selectable
            }
            exact = names.intersection(available)
            if exact:
                self._selected.setdefault(other.dbc_id, set()).update(exact)
        self._refresh_after_edit(rebuild_nodes=True)

    def _clear_current(self) -> None:
        summary = self._current_summary()
        if summary is None:
            return
        self._selected.pop(summary.dbc_id, None)
        self._excluded.discard(summary.dbc_id)
        self._refresh_after_edit(rebuild_nodes=True)

    def _clear_all(self) -> None:
        self._selected.clear()
        self._excluded.clear()
        self._refresh_after_edit(rebuild_nodes=True)

    def _refresh_after_edit(self, *, rebuild_nodes: bool = False) -> None:
        row = self.dbc_table.currentRow()
        self._refresh_dbc_table()
        if row >= 0:
            self.dbc_table.selectRow(row)
        if rebuild_nodes:
            self._show_current_dbc()
        else:
            self._refresh_preview()
        self._refresh_validation()

    def _refresh_preview(self) -> None:
        summary = self._current_summary()
        if summary is None:
            self.preview_label.clear()
            return
        preview = apply_selection_to_summary(summary, self._draft_config())
        self.preview_label.setText(
            f"DBC 报文总数：{preview.message_count}    "
            f"由所选发送节点发送：{preview.selected_sender_message_count}    "
            f"有效周期候选：{preview.base_eligible_count}    "
            f"其他发送节点排除：{preview.unselected_transmitter_count}    "
            f"路由报文排除：{preview.routing_excluded_count}    "
            f"最终参与优化：{preview.final_eligible_count}"
        )

    def _refresh_validation(self) -> None:
        try:
            validate_complete_selection(self._summaries, self._draft_config())
        except ValueError as exc:
            self.validation_label.setText(str(exc))
        else:
            self.validation_label.setText("所有 DBC 均已完成处理，可以应用选择。")

    def _apply(self) -> None:
        config = self._draft_config(confirmed=True)
        try:
            validate_complete_selection(self._summaries, config)
        except ValueError as exc:
            QMessageBox.warning(self, "无法应用发送节点选择", str(exc))
            return
        self._selection_config = config
        self.accept()
