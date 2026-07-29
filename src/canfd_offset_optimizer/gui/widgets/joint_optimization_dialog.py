"""Compact transactional settings dialog for the optional Joint workflow."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..contracts import (
    JointOptimizationSettings,
    ParetoPrecision,
)


RHO_HELP_TEXT = """一次 Com_MainFunctionTx 执行时间可以近似理解为：

    C(N) = C0 + C1 × N

N 是该 MainFunction 管理的报文数量；C0 是每次调用都会产生的固定开销；
C1 是平均每增加一条报文的处理开销；ρ = C0/C1。

ρ 较大时，多开一个 MainFunction 的固定代价相对更高，优化器通常更倾向减少
MainFunction 数量；ρ 较小时，优化器更容易接受拆分为更多调度组。

ECU 实测步骤
1. 在同一 ECU、软件版本、编译优化和尽量一致的运行条件下，测量一次
   Com_MainFunctionTx 从进入到返回的执行时间。
2. 改变该 MainFunction 管理的报文数量，建议测试 3～5 个以上测量点，例如
   N = 10、20、30、40、50。
3. 记录报文数量 N 与一次调用执行时间 C(N)，确认是否大致呈线性增长。
4. 若近似线性，C1 ≈ 执行时间增加量 / 报文增加量；
   C0 ≈ 总执行时间 - C1 × 报文数量；最后计算 ρ = C0/C1。

数值例子
管理 10 条报文时执行时间为 8 μs，管理 30 条时报文执行时间为 12 μs：
    C1 = (12 - 8) / (30 - 10) = 0.2 μs / 条
    C0 = 8 - 10 × 0.2 = 6 μs
    ρ = 6 / 0.2 = 30
将 30 填入“固定调用成本比 ρ”。

实际工程不要只依赖两个点。若执行时间与报文数量明显不是近似线性，当前简化
CPU Cost Proxy 模型不能准确描述该 ECU；ρ 只能作为近似代理参数，不应解释为
实际 CPU 利用率。"""


class RhoHelpDialog(QDialog):
    """Readable, scrollable engineering guidance without measurement tooling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("如何估算固定调用成本比 ρ")
        self.resize(720, 620)
        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("jointRhoHelpText")
        self.text_browser.setPlainText(RHO_HELP_TEXT)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText("关闭")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_browser, 1)
        layout.addWidget(buttons)


class JointOptimizationDialog(QDialog):
    """Edit a temporary copy and commit only when the dialog is accepted."""

    def __init__(
        self,
        settings: JointOptimizationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CAN-CPU 联合优化配置")
        self.setModal(True)
        self.resize(560, 430)
        self._original = settings
        self._settings: JointOptimizationSettings | None = None

        peak_group = QGroupBox("CAN 峰值保护")
        peak_form = QFormLayout(peak_group)
        self.peak_tolerance_spin = QDoubleSpinBox()
        self.peak_tolerance_spin.setObjectName("jointPeakToleranceSpin")
        self.peak_tolerance_spin.setRange(0.0, 100.0)
        self.peak_tolerance_spin.setDecimals(1)
        self.peak_tolerance_spin.setSingleStep(0.5)
        self.peak_tolerance_spin.setSuffix(" %")
        self.peak_tolerance_spin.setValue(settings.peak_tolerance_relative * 100)
        peak_form.addRow("峰值允许增量：", self.peak_tolerance_spin)
        peak_note = QLabel(
            "联合优化会在内部 Peak 参考结果的峰值限制内，搜索 CAN 均衡度与"
            "软件调度成本之间的折中方案。"
        )
        peak_note.setWordWrap(True)
        peak_form.addRow(peak_note)

        cpu_group = QGroupBox("CPU 调度模型")
        cpu_form = QFormLayout(cpu_group)
        self.rho_spin = QDoubleSpinBox()
        self.rho_spin.setObjectName("jointRhoSpin")
        self.rho_spin.setRange(0.000001, 1_000_000_000.0)
        self.rho_spin.setDecimals(6)
        self.rho_spin.setValue(float(settings.rho))
        self.rho_spin.setSingleStep(0.1)
        self.rho_help_button = QPushButton("如何获取？")
        self.rho_help_button.setObjectName("jointRhoHelpButton")
        rho_row = QWidget()
        rho_layout = QHBoxLayout(rho_row)
        rho_layout.setContentsMargins(0, 0, 0, 0)
        rho_layout.addWidget(self.rho_spin, 1)
        rho_layout.addWidget(self.rho_help_button)
        cpu_form.addRow("固定调用成本比 ρ：", rho_row)
        cpu_note = QLabel(
            "未进行 ECU 实测标定时建议保持默认值 1.0。\n"
            "CPU Cost Proxy 不代表实际 CPU 利用率。"
        )
        cpu_note.setWordWrap(True)
        cpu_form.addRow(cpu_note)

        precision_group = QGroupBox("Pareto 搜索精度")
        precision_form = QFormLayout(precision_group)
        self.precision_combo = QComboBox()
        self.precision_combo.setObjectName("jointParetoPrecisionCombo")
        self.precision_combo.addItem(
            "标准（21 点，推荐）", ParetoPrecision.STANDARD
        )
        self.precision_combo.addItem(
            "精细（41 点，耗时更长）", ParetoPrecision.FINE
        )
        self.precision_combo.setCurrentIndex(
            self.precision_combo.findData(settings.pareto_precision)
        )
        precision_form.addRow("搜索精度：", self.precision_combo)
        self.precision_note = QLabel()
        self.precision_note.setWordWrap(True)
        precision_form.addRow(self.precision_note)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        layout = QVBoxLayout(self)
        layout.addWidget(peak_group)
        layout.addWidget(cpu_group)
        layout.addWidget(precision_group)
        layout.addWidget(self.buttons)

        self.rho_help_button.clicked.connect(self.show_rho_help)
        self.precision_combo.currentIndexChanged.connect(
            self._update_precision_note
        )
        self.buttons.accepted.connect(self._commit_and_accept)
        self.buttons.rejected.connect(self.reject)
        restore = self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        if restore is not None:
            restore.setText("恢复默认值")
            restore.clicked.connect(self._restore_defaults)
        self._update_precision_note()

    @property
    def settings(self) -> JointOptimizationSettings | None:
        return self._settings

    def show_rho_help(self) -> None:
        RhoHelpDialog(self).exec()

    def _restore_defaults(self) -> None:
        defaults = JointOptimizationSettings()
        self.peak_tolerance_spin.setValue(
            defaults.peak_tolerance_relative * 100
        )
        self.rho_spin.setValue(float(defaults.rho))
        self.precision_combo.setCurrentIndex(
            self.precision_combo.findData(defaults.pareto_precision)
        )

    def _commit_and_accept(self) -> None:
        precision = self.precision_combo.currentData()
        if not isinstance(precision, ParetoPrecision):
            precision = ParetoPrecision(precision)
        rho_text = f"{self.rho_spin.value():.6f}".rstrip("0").rstrip(".")
        self._settings = JointOptimizationSettings.from_values(
            self.peak_tolerance_spin.value() / 100.0,
            rho_text,
            precision,
        )
        self.accept()

    def _update_precision_note(self) -> None:
        precision = self.precision_combo.currentData()
        if precision == ParetoPrecision.FINE:
            text = (
                "使用更密的 41 个 CPU Cost Proxy 约束点搜索，可能发现更多"
                "中间折中方案，但会增加运行时间。41 点也可能改变启发式搜索"
                "路径，不保证最终推荐一定优于 21 点。"
            )
        else:
            text = (
                "在 CAN 优先方案与 CPU 优先方案之间使用 21 个 CPU Cost Proxy "
                "约束点进行搜索，适合日常工程使用。"
            )
        self.precision_note.setText(text)
