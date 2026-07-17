from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from canfd_offset_optimizer.gui.theme import ACCENT_COLOR, apply_application_theme


def test_previous_blue_accent_roles_use_cyan_without_overriding_text(qapp) -> None:
    assert isinstance(qapp, QApplication)

    apply_application_theme(qapp)

    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == ACCENT_COLOR.lower()
    stylesheet = qapp.styleSheet()
    assert f"QProgressBar::chunk {{ background-color: {ACCENT_COLOR}; }}" in stylesheet
    assert f"QAbstractItemView::item:selected {{ background-color: {ACCENT_COLOR}; }}" in stylesheet
    assert "color: #000000" not in stylesheet
