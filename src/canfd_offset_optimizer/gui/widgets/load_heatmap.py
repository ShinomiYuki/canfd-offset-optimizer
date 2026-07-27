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

from ..contracts import (
    BatchOptimizationResult,
    GuiOptimizationResult,
    NetworkTimingConfig,
)
from ..formatting import format_load_unit, format_result_weight
from ..heatmap_view_model import (
    CongestionTableMode,
    CongestedMessageRow,
    HeatmapCellSelection,
    HeatmapCellView,
    HeatmapState,
    HeatmapViewModel,
    HeatmapWindowKind,
    build_heatmap_view_model,
    filter_congested_rows,
    message_rows_for_cell,
)
from ..load_presentation import CONGESTION_COLORS, CONGESTION_LABELS, congestion_level


CONFIGURED_MIN_CELL_WIDTH = 64
CELL_HORIZONTAL_PADDING = 18
ROW_LABEL_WIDTH = 76
RIGHT_MARGIN = 12
TOP_MARGIN = 10
ROW_HEIGHT = 88
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
    maximum_conservative_time: int = 0,
) -> int:
    """Measure readable three-line content; slot count never affects it."""

    representative_load = 56 if load_unit == "B" else 384
    samples = (
        f"{max(5, maximum_frame_count)} 帧",
        f"{max(representative_load, maximum_load)} {load_unit}",
        f"保守 ≥{max(812, maximum_conservative_time)} μs*",
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
    cell_clicked = Signal(str, int)

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

    def clear_selection(self) -> None:
        self._highlight = None
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
                self.cell_clicked.emit(cell.state.value, cell.slot_index)
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

    @property
    def highlighted_cell(self) -> tuple[HeatmapState, int] | None:
        return self._highlight


class LoadHeatmap(QWidget):
    export_requested = Signal()
    network_selected = Signal(str)
    open_directory_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.current_network_label = QLabel("当前网段：请选择一个网段")
        self.title_label = QLabel("可优化报文拥挤热力图：无结果")
        self.weight_basis_label = QLabel("权重口径：—")
        self.timing_basis_label = QLabel(
            "\u4fdd\u5b88\u5360\u7528\u65f6\u95f4\uff1a\u2014\uff08\u7f3a\u5c11 Nominal Bitrate\uff09"
        )
        self.timing_basis_label.setWordWrap(True)
        self.timing_basis_label.setToolTip(
            "\u8be5\u6307\u6807\u53ea\u7528\u4e8e\u4f18\u5316\u540e\u8bca\u65ad\u3002CAN FD \u6574\u5e27\u6309 nominal bitrate \u8ba1\u65f6\uff0c"
            "\u5047\u8bbe data-phase bitrate \u4e0d\u4f4e\u4e8e nominal bitrate\uff1b\u4e0d\u662f\u5b9e\u9645\u5e27\u65f6\u95f4\u3002"
        )
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
        self.detail_title_label = QLabel("拥挤时隙明细")
        self.detail_title_label.setStyleSheet("font-weight: bold;")
        self.detail_context_label = QLabel("当前：全部 4 帧及以上时隙")
        self.detail_context_label.setWordWrap(True)
        self.show_all_button = QPushButton("查看全部拥挤时隙")
        self.show_all_button.setVisible(False)
        self.congestion_filter_label = QLabel("筛选")
        detail_controls = QHBoxLayout()
        detail_controls.addWidget(self.detail_title_label)
        detail_controls.addWidget(self.detail_context_label, 1)
        detail_controls.addStretch(1)
        detail_controls.addWidget(self.show_all_button)
        detail_controls.addWidget(self.congestion_filter_label)
        detail_controls.addWidget(self.congestion_filter)

        self.details_empty_label = QLabel("当前窗口不存在同时释放 4 帧及以上的时隙。")
        self.details_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_table = QTableWidget(0, 10)
        self.details_table.setHorizontalHeaderLabels(
            (
                "状态",
                "时间窗口",
                "同时帧数",
                "时隙总负载",
                "报文名称",
                "CAN ID",
                "长度(Byte)",
                "周期",
                "Offset",
                "保守占用时间(μs)",
            )
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
        layout.addWidget(self.timing_basis_label)
        layout.addLayout(controls)
        layout.addWidget(self.splitter, 1)

        self._result: GuiOptimizationResult | None = None
        self._timing_config: NetworkTimingConfig | None = None
        self._view_model: HeatmapViewModel | None = None
        self._detail_rows: tuple[CongestedMessageRow, ...] = ()
        self._visible_detail_rows: tuple[CongestedMessageRow, ...] = ()
        self._table_mode = CongestionTableMode.ALL_CONGESTED
        self._selected_cell: HeatmapCellSelection | None = None
        self.network_combo.currentIndexChanged.connect(self._network_changed)
        self.window_combo.currentIndexChanged.connect(self._window_changed)
        self.congestion_filter.currentIndexChanged.connect(self._populate_details)
        self.canvas.cell_clicked.connect(self._select_cell_from_heatmap)
        self.details_table.cellClicked.connect(self._locate_cell_from_detail)
        self.show_all_button.clicked.connect(self.show_all_congested)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_batch(self, batch: BatchOptimizationResult) -> None:
        self._reset_table_state(populate=False)
        blocker = QSignalBlocker(self.network_combo)
        self.network_combo.clear()
        for item in batch.network_results:
            if item.result is not None:
                self.network_combo.addItem(item.display_name, item.network_id)
        self.network_combo.setCurrentIndex(-1)
        self.network_combo.setEnabled(self.network_combo.count() > 0)
        del blocker

    def clear_batch(self) -> None:
        self._reset_table_state(populate=False)
        blocker = QSignalBlocker(self.network_combo)
        self.network_combo.clear()
        self.network_combo.setEnabled(False)
        del blocker
        self.clear_result()

    def set_result(self, result: GuiOptimizationResult) -> None:
        # A newly bound DTO is a new result revision even when network_id is equal.
        self._reset_table_state(populate=False)
        self._result = result
        if (
            self._timing_config is None
            or self._timing_config.network_id != result.network_id
        ):
            self._timing_config = (
                result.network_timing_config
                or NetworkTimingConfig(result.network_id)
            )
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
        self._refresh_view_model()

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
        self.timing_basis_label.setText("\u4fdd\u5b88\u5360\u7528\u65f6\u95f4\uff1a\u2014\uff08\u7f3a\u5c11 Nominal Bitrate\uff09")
        self._result = None
        self._timing_config = None
        self._view_model = None
        self._detail_rows = ()
        self._visible_detail_rows = ()
        self._reset_table_state(populate=False)
        self.canvas.set_empty_message(message)
        self.canvas.set_view_model(None, CONFIGURED_MIN_CELL_WIDTH)
        self._populate_details()
        self.export_button.setEnabled(False)

    def set_timing_config(
        self, config: NetworkTimingConfig, *, refresh: bool = True
    ) -> None:
        """Refresh diagnostics only; this method never invokes an optimizer."""

        self._timing_config = config
        if (
            refresh
            and self._result is not None
            and self._result.network_id == config.network_id
        ):
            self._reset_table_state(populate=False)
            self._refresh_view_model()

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh_view_model(self) -> None:
        result = self._result
        if result is None:
            return
        data = self.window_combo.currentData()
        try:
            kind = data if isinstance(data, HeatmapWindowKind) else HeatmapWindowKind(str(data))
        except ValueError:
            kind = HeatmapWindowKind.STEADY
        view_model = build_heatmap_view_model(
            result, kind, self._timing_config
        )
        max_count = max(
            (cell.frame_count for cells in (view_model.original_cells, view_model.optimized_cells) for cell in cells),
            default=0,
        )
        max_load = max(
            (cell.total_load for cells in (view_model.original_cells, view_model.optimized_cells) for cell in cells),
            default=0,
        )
        max_conservative = max(
            (
                cell.conservative_total_time_us or 0
                for cells in (
                    view_model.original_cells,
                    view_model.optimized_cells,
                )
                for cell in cells
            ),
            default=0,
        )
        cell_width = calculate_heatmap_cell_width(
            self.fontMetrics(),
            maximum_frame_count=max_count,
            maximum_load=max_load,
            load_unit=view_model.load_unit,
            maximum_conservative_time=max_conservative,
        )
        self._view_model = view_model
        config = view_model.timing_config
        if config.nominal_bitrate_bps is None:
            self.timing_basis_label.setText(
                "\u4fdd\u5b88\u5360\u7528\u65f6\u95f4\uff1a\u2014\uff08\u7f3a\u5c11 Nominal Bitrate\uff1b\u4f18\u5316\u7ed3\u679c\u4ecd\u6709\u6548\uff09"
            )
        else:
            source = (
                "DBC"
                if config.source is not None and config.source.value == "dbc"
                else "\u624b\u52a8"
            )
            self.timing_basis_label.setText(
                "\u4fdd\u5b88\u5360\u7528\u65f6\u95f4\uff1a\u534f\u8bae\u7ea7\u4e0a\u754c\uff1bNominal Bitrate "
                f"{config.nominal_bitrate_bps / 1000:g} kbit/s\uff08{source}\uff09"
            )
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

    def _window_changed(self, _index: int) -> None:
        self._reset_table_state(populate=False)
        self._refresh_view_model()

    def _populate_details(self) -> None:
        selected_cell: HeatmapCellView | None = None
        data_error: str | None = None
        if (
            self._table_mode is CongestionTableMode.SELECTED_SLOT
            and self._selected_cell is not None
            and self._view_model is not None
        ):
            try:
                selected_cell = self._view_model.cell_for(self._selected_cell)
            except ValueError:
                # Network/window/result transitions must never retain a stale identity.
                self._reset_table_state(populate=False)
                self._populate_details()
                return
            try:
                rows = message_rows_for_cell(selected_cell)
            except ValueError as exc:
                rows = ()
                data_error = str(exc)
            self.detail_title_label.setText("时隙报文明细")
            self.detail_context_label.setText(
                "当前："
                f"{selected_cell.state.label} | {selected_cell.start_ms:g}～"
                f"{selected_cell.end_ms:g} ms | {selected_cell.frame_count} 帧 | "
                f"{selected_cell.total_load} {selected_cell.load_unit} | "
                f"{selected_cell.conservative_text}"
            )
            self.show_all_button.setVisible(True)
            self.show_all_button.setEnabled(True)
            self.congestion_filter_label.setEnabled(False)
            self.congestion_filter.setEnabled(False)
        else:
            mode = self.congestion_filter.currentData()
            if not isinstance(mode, str):
                mode = "all"
            rows = filter_congested_rows(self._detail_rows, mode)
            self.detail_title_label.setText("拥挤时隙明细")
            self.detail_context_label.setText("当前：全部 4 帧及以上时隙")
            self.show_all_button.setVisible(False)
            self.congestion_filter_label.setEnabled(True)
            self.congestion_filter.setEnabled(True)

        self._visible_detail_rows = rows
        table = self.details_table
        blocker = QSignalBlocker(table)
        table.setSortingEnabled(False)
        table.clearSelection()
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            view_model = self._view_model
            if view_model is None:
                raise RuntimeError("detail rows require a heatmap view model")
            selection = view_model.selection_for(row.state, row.slot_index)
            values: tuple[tuple[str, object], ...] = (
                (row.state.label, row.state.sort_order),
                (row.time_text, row.start_us),
                (str(row.frame_count), row.frame_count),
                (row.total_load_text, row.total_load),
                (row.message.message_name, row.message.message_name),
                (row.can_id_text, row.message.can_id),
                (
                    row.payload_text,
                    row.message.payload_bytes
                    if row.message.payload_bytes is not None
                    else -1,
                ),
                (row.period_text, row.message.cycle_time_us),
                (row.offset_text, row.message.offset_us),
                (
                    row.conservative_time_text,
                    row.message.conservative_service_time_us or -1,
                ),
            )
            for column, (text, sort_value) in enumerate(values):
                item = _SortableItem(text, sort_value)
                item.setData(Qt.ItemDataRole.UserRole + 1, row.state.value)
                item.setData(Qt.ItemDataRole.UserRole + 2, row.slot_index)
                item.setData(Qt.ItemDataRole.UserRole + 3, selection)
                if column == 5:
                    item.setToolTip(
                        f"{'Extended' if row.message.is_extended else 'Standard'} CAN ID：{row.can_id_text}"
                    )
                elif column == 6:
                    item.setToolTip("DBC Payload Length；不是 raw DLC code。")
                elif column == 9:
                    item.setToolTip(row.conservative_tooltip)
                table.setItem(index, column, item)
        table.setSortingEnabled(True)
        del blocker
        has_rows = bool(rows)
        table.setVisible(has_rows)
        self.details_empty_label.setVisible(not has_rows)
        if not has_rows:
            if data_error is not None:
                self.details_empty_label.setText(f"结果数据不一致：{data_error}")
            elif selected_cell is not None:
                self.details_empty_label.setText("当前时隙没有报文释放。")
            else:
                self.details_empty_label.setText(
                    "当前窗口不存在同时释放 4 帧及以上的时隙。"
                    if not self._detail_rows
                    else "当前筛选条件下没有拥挤时隙。"
                )

    def _select_cell_from_heatmap(self, state_value: str, slot_index: int) -> None:
        try:
            state = HeatmapState(state_value)
        except ValueError:
            return
        self._select_slot(state, slot_index, scroll=False)

    def _locate_cell_from_detail(self, row: int, column: int) -> None:
        del column
        item = self.details_table.item(row, 0)
        if item is None:
            return
        selection = item.data(Qt.ItemDataRole.UserRole + 3)
        if not isinstance(selection, HeatmapCellSelection):
            return
        if (
            self._table_mode is CongestionTableMode.SELECTED_SLOT
            and selection == self._selected_cell
        ):
            self.canvas.highlight_cell(selection.state, selection.slot_index)
            self.scroll_to_slot(selection.slot_index)
            return
        self._select_slot(selection.state, selection.slot_index, scroll=True)

    def _select_slot(
        self, state: HeatmapState, slot_index: int, *, scroll: bool
    ) -> None:
        view_model = self._view_model
        if view_model is None:
            return
        selection = view_model.selection_for(state, slot_index)
        self._selected_cell = selection
        self._table_mode = CongestionTableMode.SELECTED_SLOT
        self.canvas.highlight_cell(selection.state, selection.slot_index)
        if scroll:
            self.scroll_to_slot(selection.slot_index)
        self._populate_details()

    def show_all_congested(self) -> None:
        self._reset_table_state(populate=True)

    def _reset_table_state(self, *, populate: bool) -> None:
        self._selected_cell = None
        self._table_mode = CongestionTableMode.ALL_CONGESTED
        self.canvas.clear_selection()
        if populate:
            self._populate_details()

    def scroll_to_slot(self, slot_index: int) -> None:
        view_model = self._view_model
        if view_model is None or not 0 <= slot_index < view_model.slot_count:
            return
        target = (
            slot_index * self.canvas.cell_width + self.canvas.cell_width // 2
        )
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
            self._reset_table_state(populate=False)
            self.network_selected.emit(network_id)

    @property
    def timing_config(self) -> NetworkTimingConfig | None:
        return self._timing_config

    @property
    def view_model(self) -> HeatmapViewModel | None:
        return self._view_model

    @property
    def detail_rows(self) -> tuple[CongestedMessageRow, ...]:
        return self._detail_rows

    @property
    def visible_detail_rows(self) -> tuple[CongestedMessageRow, ...]:
        return self._visible_detail_rows

    @property
    def table_mode(self) -> CongestionTableMode:
        return self._table_mode

    @property
    def selected_cell(self) -> HeatmapCellSelection | None:
        return self._selected_cell
