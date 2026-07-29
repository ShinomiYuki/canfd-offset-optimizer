"""Read-only Joint Pareto and MainFunction recommendation presentation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..contracts import JointOptimizationView


def _recommendation_method_text(method: str) -> str:
    return {
        "geometric_knee": "几何折中点",
        "ideal_point_fallback": "理想点折中方案",
        "unique_solution": "唯一非支配方案",
        "no_interior_knee": "未形成内部折中点",
        "invalid_empty_front": "没有可用候选方案",
        "invalid_missing_recommendation": "没有自动推荐",
    }.get(method, method)


def _recommendation_note_text(method: str, note: str) -> str:
    return {
        "geometric_knee": "在当前 observed Pareto front 上选择几何折中最明显的内部方案。",
        "ideal_point_fallback": "没有正向几何折中点，采用最接近理想点的内部折中方案。",
        "unique_solution": "当前只有一个非支配方案，因此直接采用；它不是内部折中点。",
        "no_interior_knee": "当前只有两个端点，没有可供自动推荐的内部折中方案。",
        "invalid_empty_front": "当前搜索没有产生可用的非支配候选方案。",
    }.get(method, note)


class JointParetoCanvas(QWidget):
    """A display-only canvas; it intentionally exposes no selection signal."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(230)
        self._view: JointOptimizationView | None = None

    def set_view(self, view: JointOptimizationView | None) -> None:
        self._view = view
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        view = self._view
        if view is None or not view.pareto_rows:
            painter.setPen(self.palette().text().color())
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "暂无 Joint Pareto 结果",
            )
            return
        plot = QRectF(58, 16, max(20, self.width() - 82), max(20, self.height() - 58))
        painter.setPen(QPen(QColor("#9aa0a6"), 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        painter.drawLine(plot.bottomLeft(), plot.topLeft())
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 6, plot.width(), 24),
            Qt.AlignmentFlag.AlignCenter,
            "Qss（越低越好）",
        )
        painter.save()
        painter.translate(18, plot.center().y())
        painter.rotate(-90)
        painter.drawText(
            QRectF(-plot.height() / 2, -12, plot.height(), 24),
            Qt.AlignmentFlag.AlignCenter,
            "CPU Cost Proxy（越低越好）",
        )
        painter.restore()
        q_values = tuple(row.qss for row in view.pareto_rows)
        p_values = tuple(float(row.cpu_proxy) for row in view.pareto_rows)
        q_min, q_max = min(q_values), max(q_values)
        p_min, p_max = min(p_values), max(p_values)

        def point(qss: int, cpu: float) -> QPointF:
            x = 0.5 if q_min == q_max else (qss - q_min) / (q_max - q_min)
            y = 0.5 if p_min == p_max else (cpu - p_min) / (p_max - p_min)
            return QPointF(
                plot.left() + x * plot.width(),
                plot.bottom() - y * plot.height(),
            )

        points = tuple(
            point(row.qss, float(row.cpu_proxy)) for row in view.pareto_rows
        )
        painter.setPen(QPen(QColor("#607d8b"), 1.5))
        for first, second in zip(points, points[1:]):
            painter.drawLine(first, second)
        for row, location in zip(view.pareto_rows, points, strict=True):
            color = QColor("#d97706") if row.is_recommended else QColor("#2563eb")
            painter.setPen(QPen(color, 2))
            painter.setBrush(color)
            radius = 6 if row.is_recommended else 4
            painter.drawEllipse(location, radius, radius)


class JointOptimizationResultPage(QWidget):
    """Explain the observed front while keeping the formal assignment read-only."""

    def __init__(self) -> None:
        super().__init__()
        self._view: JointOptimizationView | None = None
        self.summary_label = QLabel("暂无联合优化结果")
        self.summary_label.setWordWrap(True)
        self.diagnosis_label = QLabel()
        self.diagnosis_label.setWordWrap(True)
        self.pareto_canvas = JointParetoCanvas()
        self.pareto_table = QTableWidget(0, 6)
        self.pareto_table.setHorizontalHeaderLabels(
            ("方案", "Qss", "CPU Cost Proxy", "Peak", "MainFunctionTx", "来源")
        )
        self.pareto_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.pareto_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.pareto_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.pareto_table.horizontalHeader().setStretchLastSection(True)

        self.group_table = QTableWidget(0, 5)
        self.group_table.setHorizontalHeaderLabels(
            ("组", "TimeBase (μs)", "报文", "周期 (μs)", "Offset / D (μs)")
        )
        self.group_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.group_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.group_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.group_table.horizontalHeader().setStretchLastSection(True)

        top_group = QGroupBox("Pareto 权衡（只读）")
        top_layout = QVBoxLayout(top_group)
        top_layout.addWidget(self.summary_label)
        top_layout.addWidget(self.pareto_canvas)
        top_layout.addWidget(self.pareto_table)
        bottom_group = QGroupBox("自动推荐折中方案与 MainFunctionTx 建议")
        bottom_layout = QVBoxLayout(bottom_group)
        bottom_layout.addWidget(self.diagnosis_label)
        bottom_layout.addWidget(self.group_table)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_group)
        splitter.addWidget(bottom_group)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.addWidget(splitter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

    def clear_result(self) -> None:
        self._view = None
        self.summary_label.setText("暂无联合优化结果")
        self.diagnosis_label.clear()
        self.pareto_table.setRowCount(0)
        self.group_table.setRowCount(0)
        self.pareto_canvas.set_view(None)

    def set_result(self, view: JointOptimizationView) -> None:
        self._view = view
        self.summary_label.setText(
            f"当前搜索得到的非支配候选解集：{len(view.pareto_rows)} 个；"
            f"Peak guardrail：{view.peak_budget}；"
            f"decision / fixed：{view.decision_message_count} / "
            f"{view.fixed_message_count}；细化：{view.refinement_passes}/"
            f"{view.refinement_limit}（{view.refinement_status}）。\n"
            f"CAN 优先端：{view.can_endpoint_hash[:12]}…；"
            f"CPU 优先端：{view.cpu_endpoint_hash[:12]}…。"
        )
        self.pareto_table.setRowCount(len(view.pareto_rows))
        for row_index, row in enumerate(view.pareto_rows):
            pareto_values = (
                "自动推荐" if row.is_recommended else str(row.index + 1),
                f"{row.qss:,}",
                f"{float(row.cpu_proxy):,.6g}",
                f"{row.peak:,}",
                str(row.main_function_count),
                row.source,
            )
            for column, value in enumerate(pareto_values):
                self.pareto_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )
        self.pareto_canvas.set_view(view)
        recommendation = view.recommendation
        method_text = _recommendation_method_text(recommendation.method)
        note_text = _recommendation_note_text(
            recommendation.method, recommendation.note
        )
        if not recommendation.has_recommendation:
            self.diagnosis_label.setText(
                "未形成可自动推荐的内部折中点。本次结果不会默认采用端点，"
                "不会生成优化 assignment，也不会写回 DBC。\n"
                f"诊断：{method_text}；{note_text}"
            )
            self.group_table.setRowCount(0)
            return
        assert recommendation.qss is not None
        assert recommendation.cpu_proxy is not None
        assert recommendation.peak is not None
        assert recommendation.main_function_count is not None
        assert recommendation.solution_hash is not None
        self.diagnosis_label.setText(
            f"推荐方法：{method_text}；Qss={recommendation.qss:,}；"
            f"CPU Cost Proxy={float(recommendation.cpu_proxy):,.6g}；"
            f"Peak={recommendation.peak:,}；MainFunctionTx="
            f"{recommendation.main_function_count}。\n"
            f"assignment：{recommendation.solution_hash}\n"
            f"诊断：{note_text}"
        )
        messages = tuple(
            (group, message)
            for group in view.main_function_groups
            for message in group.messages
        )
        self.group_table.setRowCount(len(messages))
        for row_index, (group, message) in enumerate(messages):
            group_values = (
                str(group.group_index),
                str(group.timebase_us),
                message.message_name,
                str(message.period_us),
                f"{message.offset_us} / {message.d_us}",
            )
            for column, value in enumerate(group_values):
                self.group_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )
