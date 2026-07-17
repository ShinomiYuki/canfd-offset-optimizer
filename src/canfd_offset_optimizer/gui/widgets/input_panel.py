"""Unified drag-and-drop project import panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from ..contracts import (
    ImportRecordStatus,
    ImportSession,
    InputKind,
    WorkspaceInspection,
)
from ..view_models import ImportDetailsTableModel, NetworkDetailsTableModel
from .project_details_dialog import ProjectDetailsDialog


class ImportDropArea(QFrame):
    """Accept any mix of local files and directories in one drop."""

    paths_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(72)
        label = QLabel("将多个文件、目录或两者混合拖到此处")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = tuple(Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile())
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class InputPanel(QGroupBox):
    """Present backend classification without parsing files in the GUI."""

    sources_selected = Signal(object)
    clear_requested = Signal()

    _KIND_LABELS = {
        InputKind.DBC: "DBC",
        InputKind.CONFIG: "项目配置",
        InputKind.ARXML: "ARXML",
        InputKind.OTHER_SUPPORTED: "其他支持输入",
        InputKind.UNRECOGNIZED: "无法识别",
        InputKind.INVALID: "无效/无法读取",
    }
    _STATUS_LABELS = {
        ImportRecordStatus.IMPORTED: "已导入",
        ImportRecordStatus.DUPLICATE: "重复（已去重）",
        ImportRecordStatus.CONFLICT_RENAMED: "冲突（已稳定重命名）",
        ImportRecordStatus.INVALID: "无效",
    }

    def __init__(self) -> None:
        super().__init__("统一工程导入")
        self._has_session = False
        self.network_details_model = NetworkDetailsTableModel()
        self.import_details_model = ImportDetailsTableModel()
        self.details_dialog = ProjectDetailsDialog(
            self.network_details_model, self.import_details_model, self
        )
        self.drop_area = ImportDropArea()
        self.add_button = QPushButton("添加文件或文件夹")
        self.clear_button = QPushButton("清空当前会话")
        self.clear_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)

        self.session_label = QLabel("尚未导入工程")
        self.session_label.setWordWrap(True)
        self.required_label = QLabel("缺少必需输入：DBC、项目配置")
        self.required_label.setWordWrap(True)
        self.optional_label = QLabel("可选输入：未发现 ARXML")
        self.networks_label = QLabel("已发现网段：0")
        self.networks_label.setWordWrap(True)
        self.count_labels: dict[InputKind, QLabel] = {}
        counts = QGridLayout()
        for index, kind in enumerate(InputKind):
            label = QLabel(f"{self._KIND_LABELS[kind]}：0")
            self.count_labels[kind] = label
            counts.addWidget(label, index // 3, index % 3)
        self.duplicate_label = QLabel("重复：0")
        self.conflict_label = QLabel("冲突：0")
        counts.addWidget(self.duplicate_label, 2, 0)
        counts.addWidget(self.conflict_label, 2, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.drop_area)
        layout.addLayout(buttons)
        layout.addWidget(self.session_label)
        layout.addLayout(counts)
        layout.addWidget(self.required_label)
        layout.addWidget(self.optional_label)
        layout.addWidget(self.networks_label)

        self.drop_area.paths_dropped.connect(self.add_sources)
        self.add_button.clicked.connect(self._show_add_menu)
        self.clear_button.clicked.connect(self.clear_requested.emit)

    def add_sources(self, paths: object) -> None:
        if isinstance(paths, (tuple, list)) and paths:
            self.sources_selected.emit(tuple(Path(path) for path in paths))

    def set_session(self, session: ImportSession) -> None:
        self._has_session = True
        self.import_details_model.set_session(session)
        self.session_label.setText(f"当前会话：{session.session_id}")
        self.session_label.setToolTip(str(session.session_directory))
        self.clear_button.setEnabled(True)
        for kind, label in self.count_labels.items():
            count = sum(record.kind is kind for record in session.records)
            label.setText(f"{self._KIND_LABELS[kind]}：{count}")
        duplicates = sum(
            record.status is ImportRecordStatus.DUPLICATE for record in session.records
        )
        conflicts = sum(
            record.status is ImportRecordStatus.CONFLICT_RENAMED for record in session.records
        )
        self.duplicate_label.setText(f"重复：{duplicates}")
        self.conflict_label.setText(f"冲突：{conflicts}")

    def set_inspection(self, inspection: WorkspaceInspection) -> None:
        self.set_session(inspection.session)
        self.network_details_model.set_inspection(inspection)
        missing = [self._KIND_LABELS[kind] for kind in inspection.missing_required]
        if missing:
            self.required_label.setText(f"缺少必需输入：{'、'.join(missing)}")
        elif inspection.errors:
            self.required_label.setText("工程冲突：" + "；".join(inspection.errors))
        else:
            self.required_label.setText("必需输入齐全")
        has_arxml = bool(inspection.session.records_of_kind(InputKind.ARXML))
        self.optional_label.setText("可选输入：已发现 ARXML" if has_arxml else "可选输入：未发现 ARXML")
        discovered = len(inspection.networks)
        optimizable = len(inspection.optimizable_networks)
        self.networks_label.setText(
            f"发现网段：{discovered} / 可优化：{optimizable} / 已跳过：{discovered - optimizable}"
        )

    def clear_display(self) -> None:
        self._has_session = False
        self.import_details_model.set_session(None)
        self.network_details_model.set_inspection(None)
        self.details_dialog.hide()
        self.session_label.setText("尚未导入工程")
        self.session_label.setToolTip("")
        self.required_label.setText("缺少必需输入：DBC、项目配置")
        self.optional_label.setText("可选输入：未发现 ARXML")
        self.networks_label.setText("已发现网段：0")
        for kind, label in self.count_labels.items():
            label.setText(f"{self._KIND_LABELS[kind]}：0")
        self.duplicate_label.setText("重复：0")
        self.conflict_label.setText("冲突：0")
        self.clear_button.setEnabled(False)

    def set_task_locked(self, locked: bool) -> None:
        self.drop_area.setEnabled(not locked)
        self.add_button.setEnabled(not locked)
        self.clear_button.setEnabled(not locked and self._has_session)

    def show_details(self) -> None:
        if self._has_session:
            self.details_dialog.show_details()

    @classmethod
    def kind_label(cls, kind: InputKind) -> str:
        return cls._KIND_LABELS[kind]

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        add_files = menu.addAction("添加一个或多个文件…")
        add_directory = menu.addAction("添加目录（递归扫描）…")
        selected = menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))
        if selected is add_files:
            paths, _ = QFileDialog.getOpenFileNames(self, "添加工程文件")
            if paths:
                self.add_sources(tuple(Path(path) for path in paths))
        elif selected is add_directory:
            path = QFileDialog.getExistingDirectory(self, "添加工程目录")
            if path:
                self.add_sources((Path(path),))
