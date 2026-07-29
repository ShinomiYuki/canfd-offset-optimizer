"""Shared GUI accent theme."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


ACCENT_COLOR = "#27C8D9"


def apply_application_theme(application: QApplication) -> None:
    """Apply one accent color to selections, progress, focus and checked states."""
    accent = QColor(ACCENT_COLOR)
    palette = application.palette()
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.Link, accent)
    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        palette.setColor(accent_role, accent)
    application.setPalette(palette)
    application.setStyleSheet(
        f"""
QProgressBar::chunk {{ background-color: {ACCENT_COLOR}; }}
QAbstractItemView::item:selected {{ background-color: {ACCENT_COLOR}; }}
"""
    )
