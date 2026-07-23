"""Scrollable, auditable two-state congestion heatmap."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..contracts import BatchOptimizationResult, GuiOptimizationResult
from ..formatting import format_load_unit, format_result_weight
from ..heatmap_view_model import (
    CongestedMessageRow,
    HeatmapCellView,
    HeatmapState,
    HeatmapViewModel,
    HeatmapWindowKind,
    build_heatmap_view_model,
    filter_congested_rows,
)
from ..load_presentation import CONGESTION_COLORS, CONGESTION_LABELS, congestion_level


CONFIGURED_MIN_CELL_WIDTH = 64
CELL_HORIZONTAL_PADDING = 18
ROW_LABEL_WIDTH = 76
RIGHT_MARGIN = 12
TOP_MARGIN = 10
ROW_HEIGHT = 72
AXIS_HEIGHT = 42
CANVAS_HEIGHT = TOP_MARGIN + 2 * ROW_HEIGHT + AXIS_HEIGHT
MAX_EXPORT_WIDTH = 32_767
MAX_EXPORT_PIXELS = 100_000_000


def calculate_heatmap_cell_width(
    metrics: QFontMetrics,
    *,
    maximum_frame_count: int,
    maximum_load: int,
    load_unit: str,
) -> int:
    """Measure readable two-line content; slot count never affects the result."""

    representative_load = 56 if load_unit == "B" else 384
    samples = (
        f"{max(5, maximum_frame_count)} 帧",
        f"{max(representative_load, maximum_load)} {load_unit}",
    )
    measured = max(metrics.horizontalAdvance(text) for text in samples)
    return max(CONFIGURED_MIN_CELL_WIDTH, measured + CELL_HORIZONTAL_PADDING)


class _SortableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: object) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, sort_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if type(left) is type(right):
            return bool(left < right)
        return super().__lt__(other)


class _HeatmapCanvas(QWidget):
    congested_cell_clicked = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self._view_model: HeatmapViewModel | None = None
        self._cell_width = CONFIGURED_MIN_CELL_WIDTH
        self._highlight: tuple[HeatmapState, int] | None = None
        self._empty_message = "请选择一个网段"
        self.setMouseTracking(True)
        self.setFixedHeight(CANVAS_HEIGHT)
        self.setFixedWidth(480)

    def set_view_model(
        self, view_model: HeatmapViewModel | None, cell_width: int
    ) -> None:
        if cell_width < CONFIGURED_MIN_CELL_WIDTH:
            raise ValueError("heatmap cell width is below the readable minimum")
        self._view_model = view_model
        self._cell_width = cell_width
        self._highlight = None
        width = (
            view_model.slot_count * cell_width + RIGHT_MARGIN
            if view_model is not None
            else 480
        )
        self.setFixedSize(max(1, width), CANVAS_HEIGHT)
        self.update()

    def set_empty_message(self, message: str) -> None:
        self._empty_message = message
        self.update()

    def highlight_cell(self, state: HeatmapState, slot_index: int) -> None:
        if self._view_model is None or not 0 <= slot_index < self._view_model.slot_count:
            return
        self._highlight = (state, slot_index)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().brush(self.backgroundRole()))
        if self._view_model is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_message)
        else:
            self._draw_content(painter, 0)
        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        cell = self._cell_at(event.position())
        if cell is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPosition().toPoint(), cell.tooltip, self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position())
            if cell is not None:
                self.highlight_cell(cell.state, cell.slot_index)
                if cell.frame_count >= 4:
                    self.congested_cell_clicked.emit(cell.state.value, cell.slot_index)
        super().mousePressEvent(event)

    def _cell_at(self, point: QPointF) -> HeatmapCellView | None:
        view_model = self._view_model
        if view_model is None or point.x() < 0:
            return None
        slot_index = int(point.x()) // self._cell_width
        if not 0 <= slot_index < view_model.slot_count:
            return None
        relative_y = point.y() - TOP_MARGIN
        if not 0 <= relative_y < 2 * ROW_HEIGHT:
            return None
        state = HeatmapState.ORIGINAL if relative_y < ROW_HEIGHT else HeatmapState.OPTIMIZED
        return view_model.cells_for(state)[slot_index]

    def _draw_content(self, painter: QPainter, origin_x: int) -> None:
        view_model = self._view_model
        assert view_model is not None
        for row_index, (state, cells) in enumerate(
            (
                (HeatmapState.ORIGINAL, view_model.original_cells),
                (HeatmapState.OPTIMIZED, view_model.optimized_cells),
            )
        ):
            y = TOP_MARGIN + row_index * ROW_HEIGHT
            for cell in cells:
                x = origin_x + cell.slot_index * self._cell_width
                rect = QRectF(x, y, self._cell_width, ROW_HEIGHT)
                level = congestion_level(cell.frame_count)
                painter.fillRect(rect, QColor(CONGESTION_COLORS[level]))
                painter.setPen(QPen(QColor("#D0D0D0"), 1))
                painter.drawRect(rect)
                if cell.text:
                    painter.setPen(QColor("white") if level >= 4 else QColor("#202020"))
                    painter.drawText(
                        rect.adjusted(2, 2, -2, -2),
                        Qt.AlignmentFlag.AlignCenter,
                        cell.text,
                    )
                if self._highlight == (state, cell.slot_index):
                    painter.setPen(QPen(QColor("#27C8D9"), 3))
                    painter.drawRect(rect.adjusted(1.5, 1.5, -1.5, -1.5))
        axis_y = TOP_MARGIN + 2 * ROW_HEIGHT
        painter.setPen(QPen(self.palette().text().color(), 1))
        painter.drawLine(
            origin_x,
            axis_y,
            origin_x + view_model.slot_count * self._cell_width,
            axis_y,
        )
        label_step = max(1, (72 + self._cell_width - 1) // self._cell_width)
        for index in range(0, view_model.slot_count, label_step):
            x = origin_x + index * self._cell_width
            painter.drawLine(x, axis_y, x, axis_y + 5)
            start_ms = view_model.original_cells[index].start_ms
            painter.drawText(
                QRectF(x + 2, axis_y + 7, max(60, self._cell_width * label_step - 4), 22),
                Qt.AlignmentFlag.AlignLeft,
                f"{start_ms:g} ms",
            )
        end_x = origin_x + view_model.slot_count * self._cell_width
        painter.drawLine(end_x, axis_y, end_x, axis_y + 5)

    def export_png(self, path: Path) -> Path:
        view_model = self._view_model
        if view_model is None:
            raise ValueError("当前没有可导出的热力图")
        content_width = ROW_LABEL_WIDTH + self.width()
        export_width = max(content_width, 720)
        export_height = CANVAS_HEIGHT + 58
        if (
            export_width > MAX_EXPORT_WIDTH
            or export_height > MAX_EXPORT_WIDTH
            or export_width * export_height > MAX_EXPORT_PIXELS
        ):
            raise ValueError("当前热力图过宽，无法以单张 PNG 导出")
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(export_width, export_height, QImage.Format.Format_ARGB32)
        if image.isNull():
            raise OSError("无法为完整热力图分配图像内存")
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setPen(QColor("#202020"))
        painter.drawText(
            QRectF(0, TOP_MARGIN, ROW_LABEL_WIDTH - 8, ROW_HEIGHT),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "原始",
        )
        painter.drawText(
            QRectF(0, TOP_MARGIN + ROW_HEIGHT, ROW_LABEL_WIDTH - 8, ROW_HEIGHT),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "优化后",
        )
        self._draw_content(painter, ROW_LABEL_WIDTH)
        self._draw_export_legend(painter, CANVAS_HEIGHT + 16)
        painter.end()
        if not image.save(str(path)):
            raise OSError(f"cannot save heatmap to {path}")
        return path

    @staticmethod
    def _draw_export_legend(painter: QPainter, y: int) -> None:
        x = ROW_LABEL_WIDTH
        for color, label in zip(CONGESTION_COLORS, CONGESTION_LABELS, strict=True):
            painter.fillRect(QRectF(x, y, 14, 14), QColor(color))
            painter.setPen(QPen(QColor("#A0A0A0"), 1))
            painter.drawRect(QRectF(x, y, 14, 14))
            painter.setPen(QColor("#202020"))
            painter.drawText(QRectF(x + 19, y - 2, 74, 20), Qt.AlignmentFlag.AlignLeft, label)
            x += 96

    @property
    def cell_width(self) -> int:
        return self._cell_width

    @property
    def content_width(self) -> int:
        return ROW_LABEL_WIDTH + self.width()

    @property
    def before_series(self) -> tuple[int, ...]:
        if self._view_model is None:
            return ()
        return tuple(cell.total_load for cell in self._view_model.original_cells)

    @property
    def after_series(self) -> tuple[int, ...]:
        if self._view_model is None:
            return ()
        return tuple(cell.total_load for cell in self._view_model.optimized_cells)

    @property
    def counts_before(self) -> tuple[int, ...]:
        if self._view_model is None:
            return ()
        return tuple(cell.frame_count for cell in self._view_model.original_cells)

    @property
    def counts_after(self) -> tuple[int, ...]:
        if self._view_model is None:
            return ()
        return tuple(cell.frame_count for cell in self._view_model.optimized_cells)

    @property
    def display_duration_ms(self) -> int:
        return int(self._view_model.duration_ms) if self._view_model is not None else 0

    @property
    def time_coordinates_ms(self) -> tuple[int, ...]:
        if self._view_model is None:
            return ()
        return tuple(int(cell.start_ms) for cell in self._view_model.original_cells)


class LoadHeatmap(QWidget):
    export_requested = Signal()
    network_selected = Signal(str)
    open_directory_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.current_network_label = QLabel("当前网段：请选择一个网段")
        self.title_label = QLabel("可优化报文拥挤热力图：无结果")
        self.weight_basis_label = QLabel("权重口径：—")
        self.current_network_id: str | None = None
        self.network_combo = QComboBox()
        self.network_combo.setEnabled(False)
        self.window_combo = QComboBox()
        self.window_combo.addItem("稳态窗口", HeatmapWindowKind.STEADY)
        self.window_combo.addItem("启动窗口", HeatmapWindowKind.STARTUP)
        self.export_button = QPushButton("导出热力图 PNG")
        self.export_button.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("网段"))
        controls.addWidget(self.network_combo)
        controls.addWidget(self.window_combo)
        controls.addStretch(1)
        controls.addWidget(self.export_button)

        self.canvas = _HeatmapCanvas()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setFixedHeight(CANVAS_HEIGHT + 24)

        labels = QWidget()
        labels.setFixedWidth(ROW_LABEL_WIDTH)
        label_layout = QVBoxLayout(labels)
        label_layout.setContentsMargins(0, TOP_MARGIN, 6, AXIS_HEIGHT)
        label_layout.setSpacing(0)
        for text in ("原始", "优化后"):
            label = QLabel(text)
            label.setFixedHeight(ROW_HEIGHT)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label_layout.addWidget(label)

        heatmap_row = QWidget()
        heatmap_row.setFixedHeight(CANVAS_HEIGHT + 24)
        heatmap_row_layout = QHBoxLayout(heatmap_row)
        heatmap_row_layout.setContentsMargins(0, 0, 0, 0)
        heatmap_row_layout.setSpacing(0)
        heatmap_row_layout.addWidget(labels)
        heatmap_row_layout.addWidget(self.scroll_area, 1)

        legend = QWidget()
        legend.setFixedHeight(32)
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(ROW_LABEL_WIDTH, 2, 0, 2)
        legend_layout.setSpacing(12)
        for color, legend_label in zip(
            CONGESTION_COLORS, CONGESTION_LABELS, strict=True
        ):
            swatch = QFrame()
            swatch.setFixedSize(15, 15)
            swatch.setStyleSheet(f"background: {color}; border: 1px solid #A0A0A0;")
            legend_layout.addWidget(swatch)
            legend_layout.addWidget(QLabel(legend_label))
        legend_layout.addStretch(1)

        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.addWidget(heatmap_row)
        upper_layout.addWidget(legend)
        upper_layout.addStretch(1)
        upper.setMaximumHeight(CANVAS_HEIGHT + 64)

        self.congestion_filter = QComboBox()
        self.congestion_filter.addItem("4 帧及以上", "all")
        self.congestion_filter.addItem("仅 4 帧", "four")
        self.congestion_filter.addItem("5 帧及以上", "five_plus")
        detail_controls = QHBoxLayout()
        detail_controls.addWidget(QLabel("拥挤时隙明细"))
        detail_controls.addStretch(1)
        detail_controls.addWidget(QLabel("筛选"))
        detail_controls.addWidget(self.congestion_filter)

        self.details_empty_label = QLabel("当前窗口不存在同时释放 4 帧及以上的时隙。")
        self.details_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_table = QTableWidget(0, 8)
        self.details_table.setHorizontalHeaderLabels(
            ("状态", "时间窗口", "同时帧数", "时隙总负载", "报文名称", "CAN ID", "周期", "Offset")
        )
        self.details_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.details_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.details_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.details_table.setSortingEnabled(True)
        self.details_table.setMinimumHeight(180)
        self.details_table.setMaximumHeight(520)
        self.details_table.verticalHeader().setVisible(False)
        header = self.details_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addLayout(detail_controls)
        detail_layout.addWidget(self.details_empty_label, 1)
        detail_layout.addWidget(self.details_table, 1)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(upper)
        self.splitter.addWidget(detail_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes((310, 240))

        layout = QVBoxLayout(self)
        layout.addWidget(self.current_network_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.weight_basis_label)
        layout.addLayout(controls)
        layout.addWidget(self.splitter, 1)

        self._result: GuiOptimizationResult | None = None
        self._view_model: HeatmapViewModel | None = None
        self._detail_rows: tuple[CongestedMessageRow, ...] = ()
        self.network_combo.currentIndexChanged.connect(self._network_changed)
        self.window_combo.currentIndexChanged.connect(self._refresh)
        self.congestion_filter.currentIndexChanged.connect(self._populate_details)
        self.canvas.congested_cell_clicked.connect(self._locate_detail_from_cell)
        self.details_table.cellClicked.connect(self._locate_cell_from_detail)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_batch(self, batch: BatchOptimizationResult) -> None:
        blocker = QSignalBlocker(self.network_combo)
        self.network_combo.clear()
        for item in batch.network_results:
            if item.result is not None:
                self.network_combo.addItem(item.display_name, item.network_id)
        self.network_combo.setCurrentIndex(-1)
        self.network_combo.setEnabled(self.network_combo.count() > 0)
        del blocker

    def clear_batch(self) -> None:
        blocker = QSignalBlocker(self.network_combo)
        self.network_combo.clear()
        self.network_combo.setEnabled(False)
        del blocker
        self.clear_result()

    def set_result(self, result: GuiOptimizationResult) -> None:
        self._result = result
        self.current_network_id = result.network_id
        self.current_network_label.setText(f"当前网段：{result.display_name}")
        self.current_network_label.setToolTip(
            f"network_id：{result.network_id}\n来源 DBC：{result.source_file}"
        )
        self.weight_basis_label.setText(
            f"权重口径：{format_result_weight(result)}；数值单位：{format_load_unit(result)}"
        )
        self._sync_network_combo(result.network_id)
        self.canvas.set_empty_message("运行结果未提供拥挤快照")
        self._refresh()

    def clear_result(
        self,
        message: str = "请选择一个网段",
        *,
        network_id: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.current_network_id = network_id
        label = display_name or message
        if display_name:
            label = f"{display_name}（{message}）"
        self.current_network_label.setText(f"当前网段：{label}")
        self.current_network_label.setToolTip("")
        self._sync_network_combo(network_id)
        self.title_label.setText("可优化报文拥挤热力图：无成功结果")
        self.weight_basis_label.setText("权重口径：—")
        self._result = None
        self._view_model = None
        self._detail_rows = ()
        self.canvas.set_empty_message(message)
        self.canvas.set_view_model(None, CONFIGURED_MIN_CELL_WIDTH)
        self._populate_details()
        self.export_button.setEnabled(False)

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh(self) -> None:
        result = self._result
        if result is None:
            return
        data = self.window_combo.currentData()
        try:
            kind = data if isinstance(data, HeatmapWindowKind) else HeatmapWindowKind(str(data))
        except ValueError:
            kind = HeatmapWindowKind.STEADY
        view_model = build_heatmap_view_model(result, kind)
        max_count = max(
            (cell.frame_count for cells in (view_model.original_cells, view_model.optimized_cells) for cell in cells),
            default=0,
        )
        max_load = max(
            (cell.total_load for cells in (view_model.original_cells, view_model.optimized_cells) for cell in cells),
            default=0,
        )
        cell_width = calculate_heatmap_cell_width(
            self.fontMetrics(),
            maximum_frame_count=max_count,
            maximum_load=max_load,
            load_unit=view_model.load_unit,
        )
        self._view_model = view_model
        self._detail_rows = view_model.congested_rows
        self.title_label.setText(
            f"{result.display_name} / {kind.label}可优化报文拥挤热力图，"
            f"核心真实范围 {view_model.duration_ms:g} ms / {result.source_file}"
        )
        self.canvas.set_view_model(view_model, cell_width)
        self.scroll_area.horizontalScrollBar().setValue(0)
        self._populate_details()
        self.export_button.setEnabled(True)
        self.export_button.setToolTip("")

    def _populate_details(self) -> None:
        mode = self.congestion_filter.currentData()
        if not isinstance(mode, str):
            mode = "all"
        rows = filter_congested_rows(self._detail_rows, mode)
        table = self.details_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values: tuple[tuple[str, object], ...] = (
                (row.state.label, row.state.sort_order),
                (row.time_text, row.start_us),
                (str(row.frame_count), row.frame_count),
                (row.total_load_text, row.total_load),
                (row.message.message_name, row.message.message_name),
                (row.can_id_text, row.message.can_id),
                (row.period_text, row.message.cycle_time_us),
                (row.offset_text, row.message.offset_us),
            )
            for column, (text, sort_value) in enumerate(values):
                item = _SortableItem(text, sort_value)
                item.setData(Qt.ItemDataRole.UserRole + 1, row.state.value)
                item.setData(Qt.ItemDataRole.UserRole + 2, row.slot_index)
                if column == 5:
                    item.setToolTip(
                        f"{'Extended' if row.message.is_extended else 'Standard'} CAN ID：{row.can_id_text}"
                    )
                table.setItem(index, column, item)
        table.setSortingEnabled(True)
        has_rows = bool(rows)
        table.setVisible(has_rows)
        self.details_empty_label.setVisible(not has_rows)
        if not has_rows:
            self.details_empty_label.setText(
                "当前窗口不存在同时释放 4 帧及以上的时隙。"
                if not self._detail_rows
                else "当前筛选条件下没有拥挤时隙。"
            )

    def _locate_detail_from_cell(self, state_value: str, slot_index: int) -> None:
        if self.congestion_filter.currentData() != "all":
            self.congestion_filter.setCurrentIndex(0)
        for row in range(self.details_table.rowCount()):
            item = self.details_table.item(row, 0)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole + 1) == state_value
                and item.data(Qt.ItemDataRole.UserRole + 2) == slot_index
            ):
                self.details_table.selectRow(row)
                self.details_table.scrollToItem(
                    item, QAbstractItemView.ScrollHint.PositionAtCenter
                )
                return

    def _locate_cell_from_detail(self, row: int, column: int) -> None:
        del column
        item = self.details_table.item(row, 0)
        if item is None:
            return
        try:
            state = HeatmapState(str(item.data(Qt.ItemDataRole.UserRole + 1)))
            slot_index = int(item.data(Qt.ItemDataRole.UserRole + 2))
        except (TypeError, ValueError):
            return
        self.canvas.highlight_cell(state, slot_index)
        self.scroll_to_slot(slot_index)

    def scroll_to_slot(self, slot_index: int) -> None:
        view_model = self._view_model
        if view_model is None or not 0 <= slot_index < view_model.slot_count:
            return
        target = slot_index * self.canvas.cell_width
        bar = self.scroll_area.horizontalScrollBar()
        centered = target - self.scroll_area.viewport().width() // 2
        bar.setValue(max(0, min(bar.maximum(), centered)))

    def _sync_network_combo(self, network_id: str | None) -> None:
        blocker = QSignalBlocker(self.network_combo)
        index = self.network_combo.findData(network_id) if network_id is not None else -1
        self.network_combo.setCurrentIndex(index)
        del blocker

    def _network_changed(self, index: int) -> None:
        if index < 0:
            return
        network_id = self.network_combo.itemData(index)
        if isinstance(network_id, str):
            self.network_selected.emit(network_id)

    @property
    def view_model(self) -> HeatmapViewModel | None:
        return self._view_model

    @property
    def detail_rows(self) -> tuple[CongestedMessageRow, ...]:
        return self._detail_rows
