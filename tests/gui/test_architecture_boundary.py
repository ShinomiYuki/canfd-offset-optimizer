from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


def test_gui_sources_do_not_import_core_private_implementation() -> None:
    gui_root = Path("src/canfd_offset_optimizer/gui")
    forbidden = {
        "optimizer",
        "optimization",
        "search_state",
        "parser",
        "report",
        "viz",
        "restart",
    }
    violations: list[str] = []
    for path in gui_root.rglob("*.py"):
        # real_backend.py is the single audited core-to-GUI adapter.
        if path.name == "real_backend.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if module and any(part in forbidden for part in module.split(".")):
                violations.append(f"{path}:{node.lineno}:{module}")
    assert not violations


def test_cli_import_does_not_require_pyside6() -> None:
    script = """
import builtins
real_import = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'PySide6' or name.startswith('PySide6.'):
        raise AssertionError('CLI imported PySide6')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
import canfd_offset_optimizer.cli
"""
    subprocess.run([sys.executable, "-c", script], check=True, cwd=Path.cwd())


def test_joint_gui_core_boundaries_are_explicit() -> None:
    widgets = Path("src/canfd_offset_optimizer/gui/widgets")
    for path in widgets.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "optimization.joint" not in source
        assert "JointSolution" not in source
        assert "MainFunctionSolveResult" not in source

    main_window = Path(
        "src/canfd_offset_optimizer/gui/main_window.py"
    ).read_text(encoding="utf-8")
    assert "JointSolution" not in main_window
    assert "MainFunctionSolveResult" not in main_window

    real_backend = Path(
        "src/canfd_offset_optimizer/gui/real_backend.py"
    ).read_text(encoding="utf-8")
    assert "from ..joint_service import" in real_backend

    service = Path("src/canfd_offset_optimizer/joint_service.py").read_text(
        encoding="utf-8"
    )
    assert ".gui" not in service
    assert "PySide6" not in service

    core_roots = (
        Path("src/canfd_offset_optimizer/optimization"),
        Path("src/canfd_offset_optimizer/joint_service.py"),
    )
    core_paths = tuple(core_roots[0].rglob("*.py")) + (core_roots[1],)
    for path in core_paths:
        source = path.read_text(encoding="utf-8")
        assert "canfd_offset_optimizer.gui" not in source
        assert "PySide6" not in source
