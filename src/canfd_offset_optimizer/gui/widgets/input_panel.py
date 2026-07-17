"""Input and output path selection panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ..contracts import InputInspectionRequest


class _PathRow(QWidget):
    changed = Signal(str)

    def __init__(self, *, directory: bool = False, optional: bool = False) -> None:
        super().__init__()
        self._directory = directory
        self._optional = optional
        self.edit = QLineEdit()
        self.edit.setClearButtonEnabled(True)
        self.edit.setPlaceholderText("可选" if optional else "请选择路径")
        self.button = QPushButton("浏览…")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.edit.textChanged.connect(self._text_changed)
        self.button.clicked.connect(self._browse)

    @property
    def path_text(self) -> str:
        return self.edit.text().strip()

    def set_path(self, path: Path) -> None:
        self.edit.setText(str(path))

    def _text_changed(self, value: str) -> None:
        self.edit.setToolTip(value)
        self.changed.emit(value)

    def _browse(self) -> None:
        if self._directory:
            selected = QFileDialog.getExistingDirectory(self, "选择目录", self.path_text)
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "选择文件", self.path_text)
        if selected:
            self.edit.setText(selected)


class InputPanel(QGroupBox):
    """Collect source files without parsing them in the GUI."""

    source_changed = Signal()
    output_changed = Signal()
    inspect_requested = Signal()

    def __init__(self) -> None:
        super().__init__("输入与输出")
        self.dbc_row = _PathRow()
        self.config_row = _PathRow()
        self.arxml_row = _PathRow(directory=True, optional=True)
        self.output_row = _PathRow(directory=True)
        self.inspect_button = QPushButton("读取网段")
        form = QFormLayout(self)
        form.addRow("DBC：", self.dbc_row)
        form.addRow("项目配置：", self.config_row)
        form.addRow("ARXML 目录：", self.arxml_row)
        form.addRow("用户输出目录：", self.output_row)
        form.addRow("", self.inspect_button)
        for row in (self.dbc_row, self.config_row, self.arxml_row):
            row.changed.connect(self._source_changed)
        self.output_row.changed.connect(lambda _value: self.output_changed.emit())
        self.inspect_button.clicked.connect(self.inspect_requested.emit)
        self._update_inspect_enabled()

    def inspection_request(self) -> InputInspectionRequest:
        arxml = self.arxml_row.path_text
        return InputInspectionRequest(
            Path(self.dbc_row.path_text),
            Path(self.config_row.path_text),
            Path(arxml) if arxml else None,
        )

    def output_directory(self) -> Path:
        return Path(self.output_row.path_text)

    def set_task_locked(self, locked: bool) -> None:
        for row in (self.dbc_row, self.config_row, self.arxml_row, self.output_row):
            row.setEnabled(not locked)
        self.inspect_button.setEnabled(not locked and self._sources_complete())

    def _sources_complete(self) -> bool:
        return bool(self.dbc_row.path_text and self.config_row.path_text)

    def _source_changed(self, _value: str) -> None:
        self._update_inspect_enabled()
        self.source_changed.emit()

    def _update_inspect_enabled(self) -> None:
        self.inspect_button.setEnabled(self.isEnabled() and self._sources_complete())
