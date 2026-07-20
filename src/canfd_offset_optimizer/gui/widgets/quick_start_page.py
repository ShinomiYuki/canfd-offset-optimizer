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
                "<b>DBC</b>：提供报文、周期、帧格式和原始 Offset。<br>"
                "<b>ARXML</b>：为 CAN FD 提供 Frame Time（帧时间）参数；Classic CAN 不需要它来计算临时 Payload 权重。<br>"
                "<b>project.yaml</b>：提供超周期、时隙和优化器基础配置；可选。"
                "未提供时自动使用程序内置默认配置。<br>"
                "<b>路由报文排除表（.xlsx）</b>：可选。按“目标网段 + CAN ID”排除由网关路由、"
                "不能由当前 ECU Offset 调度的报文；直接与其他工程文件一起拖入即可。"
                "建议直接选择包含工程文件的总目录。",
            )
        )
        layout.addWidget(
            self._group(
                "2. 参数怎么选",
                "<b>权重</b>：此选项只作用于 CAN FD；Classic CAN 固定使用 Payload 长度近似权重。"
                "Classic 的 Byte/slot 结果只用于相对均衡，不代表真实负载百分比。"
                "不同物理网段独立计算，不会混合 Byte 与 μs。<br>"
                "<b>目标模式</b>：Peak 优先压低最高峰；Variance 优先让各时隙更均匀；"
                "Balanced 在控制峰值的同时兼顾整体均匀。模式不因工程同时包含 Classic CAN 和 CAN FD 而禁用。<br>"
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
                "路由表匹配并排除的报文不会进入 Offset 修改、GCLS 或 assignment；可在“查看详情 → 路由报文排除”追溯来源行。<br>"
                "<b>可优化报文负载曲线</b>：灰色是原始负载，青色是优化后负载；"
                "原始和优化后使用同一批非路由周期 TX 报文，稳态可重复显示 500 ms 超周期。<br>"
                "<b>热力图</b>：上排是原始方案，下排是优化后方案；白、绿、黄、橙、红、黑表示"
                "0、1、2、3、4、5 帧及以上，只显示核心真实窗口，不重复。<br>"
                "<b>显示范围</b>只改变画面，不会重新运行优化，也不会修改核心结果。",
            )
        )
        layout.addWidget(
            self._group(
                "4. 输出位置",
                "每次运行会在 user_output 下创建独立目录：<br>"
                "<b>logs/</b> 保存批次和各网段日志；<b>plots/</b> 保存每个成功网段的负载图与热力图；"
                "<b>results/</b> 保存全网段汇总 CSV 和各网段 Offset CSV；<br>"
                "其中 <b>routing_exclusion_summary.csv</b> 保存路由表逐行匹配与排除审计；"
                "<b>dbc/</b> 保存写入优化后 Offset 的 DBC 副本。原始用户 DBC 不会被修改。",
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
