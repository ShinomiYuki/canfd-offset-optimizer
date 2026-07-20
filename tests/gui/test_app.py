from __future__ import annotations

from pathlib import Path

import canfd_offset_optimizer.gui.app as app_module
import canfd_offset_optimizer.gui.real_backend as real_backend_module


def test_source_workspace_root_uses_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delattr(app_module.sys, "frozen", raising=False)
    monkeypatch.chdir(tmp_path)

    assert app_module.application_workspace_root() == tmp_path.resolve()


def test_frozen_workspace_root_uses_executable_directory_not_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    executable_directory = tmp_path / "portable"
    executable_directory.mkdir()
    executable = executable_directory / "CANFDOffsetOptimizer.exe"
    other_directory = tmp_path / "launched-elsewhere"
    other_directory.mkdir()
    monkeypatch.setattr(app_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_module.sys, "executable", str(executable))
    monkeypatch.chdir(other_directory)

    assert app_module.application_workspace_root() == executable_directory.resolve()


def test_create_backend_prepares_portable_directories_and_passes_root(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeRealBackend:
        def __init__(self, workspace_root: Path) -> None:
            self.workspace_root = workspace_root

    monkeypatch.setattr(real_backend_module, "RealBackend", FakeRealBackend)

    backend = app_module.create_backend(tmp_path)

    assert isinstance(backend, FakeRealBackend)
    assert backend.workspace_root == tmp_path.resolve()
    assert (tmp_path / "user_input").is_dir()
    assert (tmp_path / "user_output").is_dir()


def test_create_backend_fails_closed_when_portable_directory_is_not_writable(
    tmp_path: Path,
) -> None:
    (tmp_path / "user_input").write_text("not a directory", encoding="utf-8")

    backend = app_module.create_backend(tmp_path)

    assert not backend.availability.can_optimize
    assert "程序目录不可写" in backend.availability.message
    assert "有写权限的目录" in backend.availability.message


def test_application_opens_main_window_maximized(qapp, monkeypatch) -> None:
    del qapp

    class FakeWindow:
        instance: "FakeWindow | None" = None

        def __init__(self, backend: object) -> None:
            self.backend = backend
            self.maximized = False
            FakeWindow.instance = self

        def showMaximized(self) -> None:  # noqa: N802
            self.maximized = True

    backend = object()
    monkeypatch.setattr(app_module, "create_backend", lambda: backend)
    monkeypatch.setattr(app_module, "MainWindow", FakeWindow)

    assert app_module.main([]) == 0
    assert FakeWindow.instance is not None
    assert FakeWindow.instance.backend is backend
    assert FakeWindow.instance.maximized


def test_portable_smoke_test_argument_skips_window(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "run_portable_smoke_test", lambda: 7)

    assert app_module.main(["CANFDOffsetOptimizer.exe", "--portable-smoke-test"]) == 7
