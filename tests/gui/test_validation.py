from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    InputInspectionRequest,
    InputSummary,
    NetworkSummary,
    OptimizationMode,
    RestartMode,
)
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.widgets.settings_panel import SettingsPanel


def test_settings_defaults_build_typed_request_with_3opt_disabled(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_input_summary(InputSummary((NetworkSummary("PT_CAN", 42, "frame_time_us"),)))

    request = panel.build_request(gui_inputs, tmp_path / "output")

    assert request.mode is OptimizationMode.BALANCED
    assert request.restart.mode is RestartMode.ADAPTIVE
    assert request.enable_triple_search is False
    assert panel.tolerance_spin.isEnabled()
    assert not panel.fixed_attempts_spin.isEnabled()

    panel.restart_combo.setCurrentIndex(1)
    assert panel.fixed_attempts_spin.isEnabled()
    assert not panel.adaptive_min_spin.isEnabled()


def test_incomplete_input_keeps_inspection_and_run_disabled(qtbot, tmp_path: Path) -> None:
    window = MainWindow(MockBackend(delay_seconds=0), dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)

    assert not window.input_panel.inspect_button.isEnabled()
    assert not window.progress_panel.run_button.isEnabled()
    assert not window.settings_panel.isEnabled()

    window.input_panel.dbc_row.set_path(tmp_path / "network.dbc")
    assert not window.input_panel.inspect_button.isEnabled()
    window.input_panel.config_row.set_path(tmp_path / "project.yaml")
    assert window.input_panel.inspect_button.isEnabled()
    assert not window.progress_panel.run_button.isEnabled()
