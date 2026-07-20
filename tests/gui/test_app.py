from __future__ import annotations

import canfd_offset_optimizer.gui.app as app_module


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
