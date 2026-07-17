from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from canfd_offset_optimizer.gui.widgets.input_panel import ImportDropArea, InputPanel


@pytest.mark.parametrize("shape", ["files", "directories", "mixed"])
def test_one_drop_event_accepts_files_directories_or_mixed(
    qtbot, tmp_path: Path, shape: str
) -> None:
    directory = tmp_path / "project"
    directory.mkdir()
    first = tmp_path / "PT.dbc"
    second = tmp_path / "project.yaml"
    first.write_text("PT", encoding="utf-8")
    second.write_text("project: demo", encoding="utf-8")
    paths = {
        "files": (first, second),
        "directories": (directory,),
        "mixed": (directory, first, second),
    }[shape]
    area = ImportDropArea()
    qtbot.addWidget(area)
    received: list[tuple[Path, ...]] = []
    area.paths_dropped.connect(received.append)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    area.dropEvent(event)
    assert received == [paths]
    assert event.isAccepted()


def test_input_panel_forwards_all_sources_as_one_project_request(qtbot, tmp_path: Path) -> None:
    panel = InputPanel()
    qtbot.addWidget(panel)
    sources = (tmp_path / "a", tmp_path / "b.dbc")
    received: list[tuple[Path, ...]] = []
    panel.sources_selected.connect(received.append)
    panel.add_sources(sources)
    assert received == [sources]
