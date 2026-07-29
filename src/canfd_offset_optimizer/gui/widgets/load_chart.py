"""System-theme-aware load curve widget using backend-provided arrays."""

from __future__ import annotations

from math import isfinite
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..contracts import GuiOptimizationResult
from ..formatting import format_load_unit, format_result_weight
from ..load_presentation import (
    DEFAULT_STEADY_REPEAT_COUNT,
    STEADY_REPEAT_COUNTS,
    repeat_for_display,
    time_coordinates,
    validate_steady_repeat_count,
)
from ..theme import ACCENT_COLOR


class _CurveCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 260)
        self._before: tuple[int, ...] = ()
        self._after: tuple[int, ...] = ()
        self._time_coordinates_ms: tuple[float, ...] = ()
        self._display_duration_ms = 0.0
        self._period_ms: float | None = None
        self._empty_message = "请选择一个网段"
        self.setToolTip("曲线数据由 backend 结果直接提供；GUI 不重新计算负载")

    def set_series(
        self,
        before: tuple[int, ...],
        after: tuple[int, ...],
        *,
        slot_width_ms: float = 5.0,
        display_duration_ms: float | None = None,
        period_ms: float | None = None,
    ) -> None:
        new_before = tuple(before)
        new_after = tuple(after)
        if len(new_before) != len(new_after):
            raise ValueError("load curve series must have equal lengths")
        if not isfinite(slot_width_ms) or slot_width_ms <= 0:
            raise ValueError("slot_width_ms must be positive")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or value < 0
            for values in (new_before, new_after)
            for value in values
        ):
            raise ValueError("load curve values must be finite and non-negative")
        new_time_coordinates_ms = time_coordinates(len(new_before), slot_width_ms)
        natural_duration = len(new_before) * slot_width_ms
        new_display_duration_ms = (
            natural_duration if display_duration_ms is None else display_duration_ms
        )
        if (
            not isfinite(new_display_duration_ms)
            or new_display_duration_ms < 0
            or (new_before and new_display_duration_ms <= 0)
        ):
            raise ValueError("display_duration_ms must be finite and positive")
        if new_display_duration_ms < natural_duration:
            raise ValueError("display duration cannot truncate load curve samples")
        if period_ms is not None and (not isfinite(period_ms) or period_ms <= 0):
            raise ValueError("period_ms must be finite and positive")

        self._before = new_before
        self._after = new_after
        self._time_coordinates_ms = new_time_coordinates_ms
        self._display_duration_ms = new_display_duration_ms
        self._period_ms = period_ms
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().brush(self.backgroundRole()))
        plot = QRectF(
            52.0,
            18.0,
            max(10.0, self.width() - 72.0),
            max(10.0, self.height() - 78.0),
        )
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(plot)
        if not self._before or not self._after:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._empty_message)
            painter.end()
            return
        maximum = max(max(self._before), max(self._after), 1)
        painter.drawText(4, int(plot.top()) + 8, str(maximum))
        painter.drawText(4, int(plot.bottom()), "0")
        self._draw_time_axis(painter, plot)
        original_pen = QPen(self.palette().mid().color(), 2, Qt.PenStyle.DashLine)
        optimized_pen = QPen(QColor(ACCENT_COLOR), 2, Qt.PenStyle.SolidLine)
        self._draw_series(
            painter,
            plot,
            self._before,
            self._time_coordinates_ms,
            self._display_duration_ms,
            original_pen,
            maximum,
        )
        self._draw_series(
            painter,
            plot,
            self._after,
            self._time_coordinates_ms,
            self._display_duration_ms,
            optimized_pen,
            maximum,
        )
        painter.setPen(self.palette().text().color())
        painter.drawText(int(plot.left()), self.height() - 12, "原始（虚线）")
        painter.setPen(QColor(ACCENT_COLOR))
        painter.drawText(int(plot.left()) + 92, self.height() - 12, "优化后（实线）")
        painter.end()

    def _draw_time_axis(self, painter: QPainter, plot: QRectF) -> None:
        if self._display_duration_ms <= 0:
            return
        painter.setPen(self.palette().text().color())
        painter.drawText(int(plot.left()), int(plot.bottom()) + 18, "0 ms")
        end_label = f"{self._display_duration_ms:g} ms"
        painter.drawText(
            int(plot.right()) - 72,
            int(plot.bottom()) + 18,
            72,
            16,
            Qt.AlignmentFlag.AlignRight,
            end_label,
        )
        if self._period_ms is None:
            return
        separator_pen = QPen(self.palette().mid().color(), 1, Qt.PenStyle.DotLine)
        painter.setPen(separator_pen)
        boundary_ms = self._period_ms
        while boundary_ms < self._display_duration_ms:
            x = plot.left() + plot.width() * boundary_ms / self._display_duration_ms
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            boundary_ms += self._period_ms

    @staticmethod
    def _draw_series(
        painter: QPainter,
        plot: QRectF,
        values: tuple[int, ...],
        time_coordinates_ms: tuple[float, ...],
        display_duration_ms: float,
        pen: QPen,
        maximum: int,
    ) -> None:
        path = QPainterPath()
        denominator = max(1, display_duration_ms)
        for index, (time_ms, value) in enumerate(zip(time_coordinates_ms, values)):
            x = plot.left() + plot.width() * time_ms / denominator
            y = plot.bottom() - plot.height() * value / maximum
            point = QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(pen)
        painter.drawPath(path)

    @property
    def before_series(self) -> tuple[int, ...]:
        return self._before

    @property
    def after_series(self) -> tuple[int, ...]:
        return self._after

    @property
    def time_coordinates_ms(self) -> tuple[float, ...]:
        return self._time_coordinates_ms

    @property
    def display_duration_ms(self) -> float:
        return self._display_duration_ms

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
            raise OSError(f"cannot save chart to {path}")
        return path


class LoadChart(QWidget):
    export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.current_network_label = QLabel("当前网段：请选择一个网段")
        self.chart_title_label = QLabel("可优化报文负载曲线：无结果")
        self.weight_basis_label = QLabel("权重口径：—")
        self.current_network_id: str | None = None
        self.window_combo = QComboBox()
        self.window_combo.addItems(("稳态窗口", "启动窗口"))
        self.display_range_label = QLabel("显示范围")
        self.display_range_combo = QComboBox()
        for repeat_count in STEADY_REPEAT_COUNTS:
            self.display_range_combo.addItem(
                f"{repeat_count} 个超周期", repeat_count
            )
        default_index = self.display_range_combo.findData(
            DEFAULT_STEADY_REPEAT_COUNT
        )
        self.display_range_combo.setCurrentIndex(default_index)
        self.display_range_label.setEnabled(False)
        self.display_range_combo.setEnabled(False)
        self.export_button = QPushButton("导出负载曲线 PNG")
        self.export_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(self.window_combo)
        controls.addWidget(self.display_range_label)
        controls.addWidget(self.display_range_combo)
        controls.addStretch(1)
        controls.addWidget(self.export_button)
        self.canvas = _CurveCanvas()
        layout = QVBoxLayout(self)
        layout.addWidget(self.current_network_label)
        layout.addWidget(self.chart_title_label)
        layout.addWidget(self.weight_basis_label)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self._result: GuiOptimizationResult | None = None
        self.window_combo.currentIndexChanged.connect(self._refresh)
        self.display_range_combo.currentIndexChanged.connect(self._refresh)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_result(self, result: GuiOptimizationResult) -> None:
        # Clear the previous network before binding the new immutable DTO.  This
        # prevents a repaint between selection signals from showing stale data.
        self._result = None
        self.canvas.set_series((), ())
        self.current_network_id = result.network_id
        self.current_network_label.setText(f"当前网段：{result.display_name}")
        self.current_network_label.setToolTip(
            f"network_id：{result.network_id}\n来源 DBC：{result.source_file}"
        )
        self._populate_repeat_options(result)
        self._result = result
        self.weight_basis_label.setText(
            f"权重口径：{format_result_weight(result)}；负载单位：{format_load_unit(result)}"
        )
        self.canvas.set_empty_message("运行结果未提供负载曲线")
        self._refresh()
        self.export_button.setEnabled(True)

    def set_error(self, result: GuiOptimizationResult, message: str) -> None:
        """Bind target identity while exposing a load-chart-only display failure."""

        self.clear_result(
            message,
            network_id=result.network_id,
            display_name=result.display_name,
        )
        self.chart_title_label.setText(f"{result.display_name} / {message}")

    def clear_result(
        self,
        message: str = "请选择一个网段",
        *,
        network_id: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.current_network_id = network_id
        title = display_name or message
        self.current_network_label.setText(f"当前网段：{title}")
        if display_name:
            self.current_network_label.setText(f"当前网段：{display_name}（{message}）")
        self.current_network_label.setToolTip("")
        self.chart_title_label.setText("可优化报文负载曲线：无成功结果")
        self.weight_basis_label.setText("权重口径：—")
        self._result = None
        self.canvas.set_empty_message(message)
        self.canvas.set_series((), ())
        self.export_button.setEnabled(False)
        self.display_range_label.setEnabled(False)
        self.display_range_combo.setEnabled(False)

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh(self) -> None:
        if self._result is None:
            self.display_range_label.setEnabled(False)
            self.display_range_combo.setEnabled(False)
            return
        if self.window_combo.currentIndex() == 0:
            self.display_range_label.setEnabled(True)
            self.display_range_combo.setEnabled(True)
            metadata = self._result.load_window_metadata
            repeat_count = self._selected_repeat_count()
            hyperperiod_ms = metadata.steady_hyperperiod_ms
            display_duration_ms = hyperperiod_ms * repeat_count
            self.chart_title_label.setText(
                f"{self._result.display_name} / 可优化报文稳态负载，"
                f"{hyperperiod_ms:g} ms 超周期重复展示 {repeat_count} 次，"
                f"显示范围 {display_duration_ms:g} ms / "
                f"{self._result.source_file}"
            )
            self.canvas.set_series(
                repeat_for_display(
                    self._result.original_steady_load, repeat_count
                ),
                repeat_for_display(
                    self._result.optimized_steady_load, repeat_count
                ),
                slot_width_ms=metadata.slot_width_ms,
                display_duration_ms=display_duration_ms,
                period_ms=hyperperiod_ms,
            )
        else:
            self.display_range_label.setEnabled(False)
            self.display_range_combo.setEnabled(False)
            metadata = self._result.load_window_metadata
            startup_duration_ms = metadata.startup_duration_ms
            self.chart_title_label.setText(
                f"{self._result.display_name} / 启动负载，核心真实范围 "
                f"{startup_duration_ms:g} ms / {self._result.source_file}"
            )
            self.canvas.set_series(
                self._result.original_startup_load,
                self._result.optimized_startup_load,
                slot_width_ms=metadata.slot_width_ms,
            )

    def _selected_repeat_count(self) -> int:
        value = self.display_range_combo.currentData()
        return validate_steady_repeat_count(int(value))

    def _populate_repeat_options(self, result: GuiOptimizationResult) -> None:
        selected = self.display_range_combo.currentData()
        repeat_count = (
            int(selected)
            if selected in STEADY_REPEAT_COUNTS
            else DEFAULT_STEADY_REPEAT_COUNT
        )
        hyperperiod_ms = result.load_window_metadata.steady_hyperperiod_ms
        blocker = QSignalBlocker(self.display_range_combo)
        self.display_range_combo.clear()
        for value in STEADY_REPEAT_COUNTS:
            duration_ms = hyperperiod_ms * value
            self.display_range_combo.addItem(
                f"{value} 个超周期（{duration_ms:g} ms）", value
            )
        self.display_range_combo.setCurrentIndex(
            self.display_range_combo.findData(repeat_count)
        )
        del blocker

    @staticmethod
    def _repeat_for_display(
        values: tuple[int, ...], repeat_count: int
    ) -> tuple[int, ...]:
        return repeat_for_display(values, repeat_count)
