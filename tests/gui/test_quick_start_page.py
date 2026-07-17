from __future__ import annotations

from PySide6.QtWidgets import QLabel

from canfd_offset_optimizer.gui.widgets.quick_start_page import QuickStartPage


def test_quick_start_explains_inputs_parameters_views_and_outputs(qtbot) -> None:
    page = QuickStartPage()
    qtbot.addWidget(page)
    labels = [label.text() for label in page.findChildren(QLabel)]
    content = " ".join(labels)
    assert "Payload" in content
    assert "Frame Time" in content
    assert "Balanced 容差" in content
    assert "候选池" in content
    assert "3-opt" in content
    assert "logs/" in content
    assert "plots/" in content
    assert "results/" in content
