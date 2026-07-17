"""System-theme-aware load curve widget using backend-provided arrays."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPaintEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..contracts import GuiOptimizationResult


class _CurveCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 260)
        self._before: tuple[int, ...] = ()
        self._after: tuple[int, ...] = ()
        self._empty_message = "请选择一个网段"
        self.setToolTip("曲线数据由 backend 结果直接提供；GUI 不重新计算负载")

    def set_series(self, before: tuple[int, ...], after: tuple[int, ...]) -> None:
        self._before = before
        self._after = after
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().brush(self.backgroundRole()))
        plot = QRectF(52.0, 18.0, max(10.0, self.width() - 72.0), max(10.0, self.height() - 58.0))
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(plot)
        if not self._before or not self._after:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._empty_message)
            painter.end()
            return
        maximum = max(max(self._before), max(self._after), 1)
        painter.drawText(4, int(plot.top()) + 8, str(maximum))
        painter.drawText(4, int(plot.bottom()), "0")
        self._draw_series(
            painter,
            plot,
            self._before,
            QPen(self.palette().mid().color(), 2),
            maximum,
        )
        self._draw_series(
            painter,
            plot,
            self._after,
            QPen(self.palette().highlight().color(), 2),
            maximum,
        )
        painter.setPen(self.palette().text().color())
        painter.drawText(int(plot.left()), self.height() - 12, "原始")
        painter.setPen(self.palette().highlight().color())
        painter.drawText(int(plot.left()) + 52, self.height() - 12, "优化后")
        painter.end()

    @staticmethod
    def _draw_series(
        painter: QPainter,
        plot: QRectF,
        values: tuple[int, ...],
        pen: QPen,
        maximum: int,
    ) -> None:
        path = QPainterPath()
        denominator = max(1, len(values) - 1)
        for index, value in enumerate(values):
            x = plot.left() + plot.width() * index / denominator
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
        self.current_network_id: str | None = None
        self.window_combo = QComboBox()
        self.window_combo.addItems(("稳态窗口", "启动窗口"))
        self.export_button = QPushButton("导出负载曲线 PNG")
        self.export_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(self.window_combo)
        controls.addStretch(1)
        controls.addWidget(self.export_button)
        self.canvas = _CurveCanvas()
        layout = QVBoxLayout(self)
        layout.addWidget(self.current_network_label)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self._result: GuiOptimizationResult | None = None
        self.window_combo.currentIndexChanged.connect(self._refresh)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_result(self, result: GuiOptimizationResult) -> None:
        self.current_network_id = result.network_id
        self.current_network_label.setText(f"当前网段：{result.display_name}")
        self.current_network_label.setToolTip(
            f"network_id：{result.network_id}\n来源 DBC：{result.source_file}"
        )
        self._result = result
        self.canvas.set_empty_message("运行结果未提供负载曲线")
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
        title = display_name or message
        self.current_network_label.setText(f"当前网段：{title}")
        if display_name:
            self.current_network_label.setText(f"当前网段：{display_name}（{message}）")
        self.current_network_label.setToolTip("")
        self._result = None
        self.canvas.set_empty_message(message)
        self.canvas.set_series((), ())
        self.export_button.setEnabled(False)

    def export_png(self, path: Path) -> Path:
        return self.canvas.export_png(path)

    def _refresh(self) -> None:
        if self._result is None:
            return
        if self.window_combo.currentIndex() == 0:
            self.canvas.set_series(
                self._result.original_steady_load, self._result.optimized_steady_load
            )
        else:
            self.canvas.set_series(
                self._result.original_startup_load, self._result.optimized_startup_load
            )
