"""Plain-language quick-start and parameter reference page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget


class QuickStartPage(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel("快速开始")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        intro = QLabel(
            "三步完成：① 左侧导入工程目录；② 检查网段和参数；"
            "③ 点击“开始全部网段优化”，再从结果概览选择网段查看图表。"
        )
        intro.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(
            self._group(
                "1. 工程输入",
                "<b>DBC</b>：提供报文、周期和原始 Offset。只有 DBC 时只能使用 Payload 权重。<br>"
                "<b>ARXML</b>：提供帧在总线上的时间信息；配合 DBC 才能选择 Frame Time 权重。<br>"
                "<b>project.yaml</b>：提供超周期、时隙和优化器基础配置；可选。"
                "未提供时自动使用程序内置默认配置。建议直接选择包含工程文件的总目录。",
            )
        )
        layout.addWidget(
            self._group(
                "2. 参数怎么选",
                "<b>权重</b>：Payload 只比较有效载荷字节；Frame Time 更接近真实总线占用。<br>"
                "<b>目标模式</b>：Peak 优先压低最高峰；Variance 优先让各时隙更均匀；"
                "Balanced 在控制峰值的同时兼顾整体均匀。<br>"
                "<b>Balanced 容差</b>：允许峰值相对最优峰值略有增加，以换取更平滑的负载；"
                "数值越小越偏向压峰。仅 Balanced 使用。<br>"
                "<b>重启策略</b>：Fixed 固定尝试次数，耗时更可预测；Adaptive 在结果长期不再改善时提前停止。<br>"
                "<b>Attempts</b>：尝试次数越多，通常越有机会找到更好结果，但运行时间也更长。<br>"
                "<b>候选池</b>：每一步保留多少个有希望的候选；越大搜索更充分，也更耗时。<br>"
                "<b>3-opt</b>：同时调整三个报文的高质量搜索，适合离线优化；会明显增加耗时。",
            )
        )
        layout.addWidget(
            self._group(
                "3. 看懂结果",
                "<b>结果概览</b>：先看每个网段是否成功以及峰值改善。<br>"
                "<b>Offset 修改</b>：列出每条报文原始值和建议值。<br>"
                "<b>负载曲线</b>：灰色是原始负载，青色是优化后负载；稳态可重复显示 500 ms 超周期。<br>"
                "<b>热力图</b>：上排是原始方案，下排是优化后方案；白、绿、黄、橙、红表示"
                "每时隙从少到多的释放帧数，只显示核心真实窗口，不重复。<br>"
                "<b>显示范围</b>只改变画面，不会重新运行优化，也不会修改核心结果。",
            )
        )
        layout.addWidget(
            self._group(
                "4. 输出位置",
                "每次运行会在 user_output 下创建独立目录：<br>"
                "<b>logs/</b> 保存批次和各网段日志；<b>plots/</b> 保存每个成功网段的负载图与热力图；"
                "<b>results/</b> 保存全网段汇总 CSV 和各网段 Offset CSV。",
            )
        )
        note = QLabel("提示：首次使用建议保留默认参数，先确认所有网段都能成功，再逐项调整。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.setWidget(body)

    @staticmethod
    def _group(title: str, html: str) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        label = QLabel(html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        return group
