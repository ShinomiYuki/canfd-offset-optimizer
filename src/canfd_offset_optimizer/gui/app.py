"""GUI application composition root."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryFile

from PySide6.QtWidgets import QApplication

from .contracts import OptimizationBackend
from .main_window import MainWindow
from .theme import apply_application_theme
from .unavailable_backend import UnavailableBackend


WORKSPACE_DIRECTORY_NAMES = ("user_input", "user_output")
PORTABLE_SMOKE_TEST_ARGUMENT = "--portable-smoke-test"


def application_workspace_root() -> Path:
    """Return the writable data root beside a frozen EXE or the source cwd."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def prepare_workspace_root(workspace_root: Path) -> Path:
    """Create and probe the two persistent portable workspace directories."""

    root = workspace_root.resolve()
    for name in WORKSPACE_DIRECTORY_NAMES:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        with TemporaryFile(dir=directory):
            pass
    return root


def create_backend(workspace_root: Path | None = None) -> OptimizationBackend:
    """Construct the real adapter or an explicit unavailable gate, never Mock."""

    root = (workspace_root or application_workspace_root()).resolve()
    try:
        root = prepare_workspace_root(root)
    except OSError as exc:
        return UnavailableBackend(
            "程序目录不可写，无法创建 user_input/user_output。"
            "请将整个程序文件夹解压到有写权限的目录后重新启动。"
            f"技术详情：{type(exc).__name__}: {exc}",
            workspace_root=root,
        )
    try:
        from .real_backend import RealBackend

        return RealBackend(workspace_root=root)
    except Exception as exc:  # composition failures must be visible, never mocked
        return UnavailableBackend(
            f"RealBackend 初始化失败：{type(exc).__name__}: {exc}",
            workspace_root=root,
        )


def run_portable_smoke_test(workspace_root: Path | None = None) -> int:
    """Validate the frozen runtime without opening a window."""

    backend = create_backend(workspace_root)
    if not backend.availability.can_optimize:
        return 2
    try:
        from ..config import load_project_config
        from .workspace_io import DEFAULT_PROJECT_CONFIG_PATH

        load_project_config(DEFAULT_PROJECT_CONFIG_PATH)
        importlib.import_module("lxml.etree")
        importlib.import_module("matplotlib.pyplot")
    except Exception:
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the production GUI with a fail-closed real backend."""
    arguments = list(argv) if argv is not None else sys.argv
    if PORTABLE_SMOKE_TEST_ARGUMENT in arguments:
        return run_portable_smoke_test()
    existing = QApplication.instance()
    owns_application = not isinstance(existing, QApplication)
    application = (
        QApplication(arguments) if owns_application else existing
    )
    assert isinstance(application, QApplication)
    application.setApplicationName("CAN FD Offset Optimizer")
    apply_application_theme(application)
    backend = create_backend()
    window = MainWindow(backend)
    window.showMaximized()
    if owns_application:
        return application.exec()
    return 0
