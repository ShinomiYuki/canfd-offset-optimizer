"""GUI application composition root."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from .contracts import OptimizationBackend
from .main_window import MainWindow
from .unavailable_backend import UnavailableBackend


def create_backend() -> OptimizationBackend:
    """Construct the real adapter or an explicit unavailable gate, never Mock."""

    try:
        from .real_backend import RealBackend

        return RealBackend()
    except Exception as exc:  # composition failures must be visible, never mocked
        return UnavailableBackend(
            f"RealBackend 初始化失败：{type(exc).__name__}: {exc}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the production GUI with a fail-closed real backend."""
    existing = QApplication.instance()
    owns_application = not isinstance(existing, QApplication)
    application = (
        QApplication(list(argv) if argv is not None else sys.argv) if owns_application else existing
    )
    assert isinstance(application, QApplication)
    application.setApplicationName("CAN FD Offset Optimizer")
    backend = create_backend()
    window = MainWindow(backend)
    window.show()
    if owns_application:
        return application.exec()
    return 0
