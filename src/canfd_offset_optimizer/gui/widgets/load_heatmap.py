"""Heatmap view of backend-provided original and optimized load arrays."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..contracts import GuiOptimizationResult
from ..load_presentation import (
    DEFAULT_DISPLAY_DURATION_MS,
    DISPLAY_DURATIONS_MS,
    SLOT_WIDTH_MS,
    STEADY_HYPERPERIOD_MS,
    repeat_for_display,
    steady_repeat_count,
    time_coordinates,
)
from ..theme import ACCENT_COLOR


class _HeatmapCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 250)
        self._before: tuple[int, ...] = ()
        self._after: tuple[int, ...] = ()
        self._display_duration_ms = 0
        self._time_coordinates_ms: tuple[int, ...] = ()
        self._period_ms: int | None = None
        self._empty_message = "请选择一个网段"
        self.setToolTip("每列对应一个真实 5 ms 时隙；颜色越深表示负载越高")

    def set_series(
        self,
        before: tuple[int, ...],
        after: tuple[int, ...],
        *,
        display_duration_ms: int | None = None,
        period_ms: int | None = None,
    ) -> None:
        if len(before) != len(after):
            raise ValueError("heatmap series must have equal lengths")
        self._before = before
        self._after = after
        self._time_coordinates_ms = time_coordinates(len(before))
        natural_duration = len(before) * SLOT_WIDTH_MS
        self._display_duration_ms = (
            natural_duration if display_duration_ms is None else display_duration_ms
        )
        if self._display_duration_ms < natural_duration:
            raise ValueError("display duration cannot truncate heatmap samples")
        self._period_ms = period_ms
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().brush(self.backgroundRole()))
        plot = QRectF(76.0, 24.0, max(10.0, self.width() - 96.0), 150.0)
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(plot)
        if not self._before or not self._after:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._empty_message)
            painter.end()
            return
        maximum = max(max(self._before), max(self._after), 1)
        row_height = plot.height() / 2
        column_width = plot.width() / max(1, len(self._before))
        painter.setPen(Qt.PenStyle.NoPen)
        for row, values in enumerate((self._before, self._after)):
            for column, value in enumerate(values):
                color = QColor(ACCENT_COLOR)
                color.setAlphaF(0.08 + 0.92 * value / maximum)
                painter.setBrush(color)
                painter.drawRect(
                    QRectF(
                        plot.left() + column * column_width,
                        plot.top() + row * row_height,
                        column_width + 0.5,
                        row_height,
                    )
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
        if self._period_ms is not None:
            painter.setPen(QPen(self.palette().mid().color(), 1, Qt.PenStyle.DotLine))
            for boundary_ms in range(
                self._period_ms, self._display_duration_ms, self._period_ms
            ):
                x = plot.left() + plot.width() * boundary_ms / self._display_duration_ms
                painter.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))
        painter.setPen(self.palette().text().color())
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 34, plot.width(), 28),
            Qt.AlignmentFlag.AlignCenter,
            f"颜色范围：0 ～ {maximum}；每列 {SLOT_WIDTH_MS} ms",
        )
        painter.end()

    @property
    def before_series(self) -> tuple[int, ...]:
        return self._before

    @property
    def after_series(self) -> tuple[int, ...]:
        return self._after

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

    def __init__(self) -> None:
        super().__init__()
        self.current_network_label = QLabel("当前网段：请选择一个网段")
        self.title_label = QLabel("负载热力图：无结果")
        self.current_network_id: str | None = None
        self.window_combo = QComboBox()
        self.window_combo.addItems(("稳态窗口", "启动窗口"))
        self.display_range_label = QLabel("显示范围")
        self.display_range_combo = QComboBox()
        for duration_ms in DISPLAY_DURATIONS_MS:
            self.display_range_combo.addItem(f"{duration_ms} ms", duration_ms)
        self.display_range_combo.setCurrentIndex(
            self.display_range_combo.findData(DEFAULT_DISPLAY_DURATION_MS)
        )
        self.export_button = QPushButton("导出热力图 PNG")
        self.export_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(self.window_combo)
        controls.addWidget(self.display_range_label)
        controls.addWidget(self.display_range_combo)
        controls.addStretch(1)
        controls.addWidget(self.export_button)
        self.canvas = _HeatmapCanvas()
        layout = QVBoxLayout(self)
        layout.addWidget(self.current_network_label)
        layout.addWidget(self.title_label)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self._result: GuiOptimizationResult | None = None
        self.window_combo.currentIndexChanged.connect(self._refresh)
        self.display_range_combo.currentIndexChanged.connect(self._refresh)
        self.export_button.clicked.connect(self.export_requested.emit)
        self._set_range_enabled(False)

    def set_result(self, result: GuiOptimizationResult) -> None:
        self._result = None
        self.canvas.set_series((), ())
        self.current_network_id = result.network_id
        self.current_network_label.setText(f"当前网段：{result.display_name}")
        self.current_network_label.setToolTip(
            f"network_id：{result.network_id}\n来源 DBC：{result.source_file}"
        )
        self._result = result
        self.canvas.set_empty_message("运行结果未提供负载数组")
        self._refresh()
        self.export_button.setEnabled(True)

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
        self.title_label.setText("负载热力图：无成功结果")
        self._result = None
        self.canvas.set_empty_message(message)
        self.canvas.set_series((), ())
        self.export_button.setEnabled(False)
        self._set_range_enabled(False)

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh(self) -> None:
        if self._result is None:
            self._set_range_enabled(False)
            return
        if self.window_combo.currentIndex() == 0:
            self._set_range_enabled(True)
            duration_ms = int(self.display_range_combo.currentData())
            repeat_count = steady_repeat_count(duration_ms)
            self.title_label.setText(
                f"{self._result.display_name} / 稳态负载热力图，"
                f"{STEADY_HYPERPERIOD_MS} ms 超周期重复展示 {repeat_count} 次 / "
                f"{self._result.source_file}"
            )
            self.canvas.set_series(
                repeat_for_display(self._result.original_steady_load, repeat_count),
                repeat_for_display(self._result.optimized_steady_load, repeat_count),
                display_duration_ms=duration_ms,
                period_ms=STEADY_HYPERPERIOD_MS,
            )
        else:
            self._set_range_enabled(False)
            duration_ms = len(self._result.original_startup_load) * SLOT_WIDTH_MS
            self.title_label.setText(
                f"{self._result.display_name} / 启动负载热力图，核心真实范围 "
                f"{duration_ms} ms / {self._result.source_file}"
            )
            self.canvas.set_series(
                self._result.original_startup_load,
                self._result.optimized_startup_load,
            )

    def _set_range_enabled(self, enabled: bool) -> None:
        self.display_range_label.setEnabled(enabled)
        self.display_range_combo.setEnabled(enabled)
