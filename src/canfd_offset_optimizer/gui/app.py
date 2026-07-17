"""GUI application composition root."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .mock_backend import MockBackend


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the mock-backed MVP without importing core optimizer internals."""
    existing = QApplication.instance()
    owns_application = not isinstance(existing, QApplication)
    application = (
        QApplication(list(argv) if argv is not None else sys.argv) if owns_application else existing
    )
    assert isinstance(application, QApplication)
    application.setApplicationName("CAN FD Offset Optimizer")
    window = MainWindow(MockBackend())
    window.show()
    if owns_application:
        return application.exec()
    return 0
