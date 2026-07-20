"""Single-window congestion heatmap following main-branch plot semantics."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..contracts import BatchOptimizationResult, GuiOptimizationResult
from ..formatting import format_load_unit, format_result_weight
from ..load_presentation import (
    CONGESTION_COLORS,
    CONGESTION_LABELS,
    SLOT_WIDTH_MS,
    congestion_level,
)


# A fixed-width inline canvas stops being useful beyond one 500 ms/100-slot
# window.  The backend still exports the complete heatmap PNG for external use.
MAX_INLINE_HEATMAP_SLOTS = 100


class _HeatmapCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 270)
        self._before: tuple[int, ...] = ()
        self._after: tuple[int, ...] = ()
        self._counts_before: tuple[int, ...] = ()
        self._counts_after: tuple[int, ...] = ()
        self._display_duration_ms = 0
        self._time_coordinates_ms: tuple[int, ...] = ()
        self._empty_message = "请选择一个网段"
        self.setToolTip(
            "每列是一个真实 5 ms 时隙；颜色表示同一时隙释放帧数，"
            "分级与主分支拥挤热力图一致"
        )

    def set_series(
        self,
        before: tuple[int, ...],
        after: tuple[int, ...],
        counts_before: tuple[int, ...] = (),
        counts_after: tuple[int, ...] = (),
    ) -> None:
        lengths = {len(before), len(after), len(counts_before), len(counts_after)}
        if before or after or counts_before or counts_after:
            if len(lengths) != 1 or 0 in lengths:
                raise ValueError("heatmap load and count arrays must have equal lengths")
        self._before = before
        self._after = after
        self._counts_before = counts_before
        self._counts_after = counts_after
        self._time_coordinates_ms = tuple(
            index * SLOT_WIDTH_MS for index in range(len(before))
        )
        self._display_duration_ms = len(before) * SLOT_WIDTH_MS
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().brush(self.backgroundRole()))
        plot = QRectF(76.0, 24.0, max(10.0, self.width() - 96.0), 150.0)
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(plot)
        if not self._before:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._empty_message)
            painter.end()
            return
        row_height = plot.height() / 2
        column_width = plot.width() / len(self._before)
        for row, (counts, loads) in enumerate(
            (
                (self._counts_before, self._before),
                (self._counts_after, self._after),
            )
        ):
            for column, (count, load) in enumerate(zip(counts, loads, strict=True)):
                cell = QRectF(
                    plot.left() + column * column_width,
                    plot.top() + row * row_height,
                    column_width + 0.5,
                    row_height,
                )
                painter.fillRect(cell, QColor(CONGESTION_COLORS[congestion_level(count)]))
                painter.setPen(QPen(QColor("#D0D0D0"), 1))
                painter.drawRect(cell)
                if column_width >= 32 and count:
                    painter.setPen(
                        QColor("white")
                        if congestion_level(count) >= 4
                        else QColor("#202020")
                    )
                    painter.drawText(
                        cell,
                        Qt.AlignmentFlag.AlignCenter,
                        f"{count}帧\n{load}",
                    )
        painter.setPen(self.palette().text().color())
        painter.drawText(6, int(plot.top() + row_height / 2 + 5), "原始")
        painter.drawText(6, int(plot.top() + row_height * 1.5 + 5), "优化后")
        painter.drawText(int(plot.left()), int(plot.bottom()) + 22, "0 ms")
        painter.drawText(
            int(plot.right()) - 82,
            int(plot.bottom()) + 7,
            82,
            18,
            Qt.AlignmentFlag.AlignRight,
            f"{self._display_duration_ms} ms",
        )
        self._draw_legend(painter, plot)
        painter.end()

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        item_width = plot.width() / len(CONGESTION_LABELS)
        top = plot.bottom() + 38
        for index, (color, label) in enumerate(
            zip(CONGESTION_COLORS, CONGESTION_LABELS, strict=True)
        ):
            left = plot.left() + index * item_width
            swatch = QRectF(left, top, 15, 15)
            painter.fillRect(swatch, QColor(color))
            painter.setPen(QPen(QColor("#B0B0B0"), 1))
            painter.drawRect(swatch)
            painter.setPen(self.palette().text().color())
            painter.drawText(
                QRectF(left + 19, top - 1, max(10.0, item_width - 19), 18),
                Qt.AlignmentFlag.AlignLeft,
                label,
            )

    @property
    def before_series(self) -> tuple[int, ...]:
        return self._before

    @property
    def after_series(self) -> tuple[int, ...]:
        return self._after

    @property
    def counts_before(self) -> tuple[int, ...]:
        return self._counts_before

    @property
    def counts_after(self) -> tuple[int, ...]:
        return self._counts_after

    @property
    def display_duration_ms(self) -> int:
        return self._display_duration_ms

    @property
    def time_coordinates_ms(self) -> tuple[int, ...]:
        return self._time_coordinates_ms

    def set_empty_message(self, message: str) -> None:
        self._empty_message = message
        self.update()

    def export_png(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(self.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.render(painter, QPoint(0, 0))
        painter.end()
        if not image.save(str(path)):
            raise OSError(f"cannot save heatmap to {path}")
        return path


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
        self.window_combo.addItems(("稳态窗口", "启动窗口"))
        self.open_directory_button = QPushButton("打开热力图文件所在目录")
        self.open_directory_button.setEnabled(False)
        self.open_directory_button.setVisible(False)
        self.export_button = QPushButton("导出热力图 PNG")
        self.export_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("网段"))
        controls.addWidget(self.network_combo)
        controls.addWidget(self.window_combo)
        controls.addStretch(1)
        controls.addWidget(self.open_directory_button)
        controls.addWidget(self.export_button)
        self.canvas = _HeatmapCanvas()
        layout = QVBoxLayout(self)
        layout.addWidget(self.current_network_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.weight_basis_label)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self._result: GuiOptimizationResult | None = None
        self._external_heatmap_path: Path | None = None
        self.network_combo.currentIndexChanged.connect(self._network_changed)
        self.window_combo.currentIndexChanged.connect(self._refresh)
        self.open_directory_button.clicked.connect(self._open_external_directory)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_batch(self, batch: BatchOptimizationResult) -> None:
        """Populate successful networks without emitting a stale selection."""

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
        self._result = None
        self.canvas.set_series((), ())
        self.current_network_id = result.network_id
        self.current_network_label.setText(f"当前网段：{result.display_name}")
        self.current_network_label.setToolTip(
            f"network_id：{result.network_id}\n来源 DBC：{result.source_file}"
        )
        self._result = result
        self.weight_basis_label.setText(
            f"权重口径：{format_result_weight(result)}；数值单位：{format_load_unit(result)}"
        )
        self._external_heatmap_path = next(
            (
                path
                for path in result.exported_files
                if path.name.casefold().endswith("_heatmap.png")
            ),
            None,
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
        self._external_heatmap_path = None
        self.canvas.set_empty_message(message)
        self.canvas.set_series((), ())
        self.open_directory_button.setEnabled(False)
        self.open_directory_button.setVisible(False)
        self.export_button.setEnabled(False)

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh(self) -> None:
        if self._result is None:
            return
        if self.window_combo.currentIndex() == 0:
            duration_ms = len(self._result.original_steady_load) * SLOT_WIDTH_MS
            self.title_label.setText(
                f"{self._result.display_name} / 稳态窗口可优化报文拥挤热力图，"
                f"核心真实范围 {duration_ms} ms / {self._result.source_file}"
            )
            if len(self._result.original_steady_load) > MAX_INLINE_HEATMAP_SLOTS:
                self._show_external_fallback(len(self._result.original_steady_load))
            else:
                self._show_inline(
                    self._result.original_steady_load,
                    self._result.optimized_steady_load,
                    self._result.original_steady_count,
                    self._result.optimized_steady_count,
                )
        else:
            duration_ms = len(self._result.original_startup_load) * SLOT_WIDTH_MS
            self.title_label.setText(
                f"{self._result.display_name} / 启动窗口可优化报文拥挤热力图，"
                f"核心真实范围 {duration_ms} ms / {self._result.source_file}"
            )
            self._show_inline(
                self._result.original_startup_load,
                self._result.optimized_startup_load,
                self._result.original_startup_count,
                self._result.optimized_startup_count,
            )

    def _show_inline(
        self,
        before: tuple[int, ...],
        after: tuple[int, ...],
        counts_before: tuple[int, ...],
        counts_after: tuple[int, ...],
    ) -> None:
        self.open_directory_button.setEnabled(False)
        self.open_directory_button.setVisible(False)
        self.export_button.setEnabled(True)
        self.export_button.setToolTip("")
        self.canvas.set_series(before, after, counts_before, counts_after)

    def _show_external_fallback(self, slot_count: int) -> None:
        self.canvas.set_empty_message(
            "图片过大，请使用外部工具查看。\n"
            f"当前稳态窗口包含 {slot_count} 个 5 ms 时隙。"
        )
        self.canvas.set_series((), ())
        path = self._external_heatmap_path
        available = path is not None and path.is_file()
        self.open_directory_button.setVisible(True)
        self.open_directory_button.setEnabled(available)
        self.open_directory_button.setToolTip(
            str(path) if available else "完整热力图文件尚未生成或不存在"
        )
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("请使用后端自动生成的完整热力图 PNG")

    def _open_external_directory(self) -> None:
        path = self._external_heatmap_path
        if path is not None and path.is_file():
            self.open_directory_requested.emit(path.parent)

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
