from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    InputInspectionRequest,
    InputSummary,
    NetworkSummary,
    OptimizationMode,
    RestartMode,
    WeightMode,
)
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.widgets.settings_panel import SettingsPanel


def test_settings_defaults_build_typed_request_with_3opt_disabled(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_input_summary(
        InputSummary(
            (
                NetworkSummary(
                    "PT",
                    42,
                    (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US),
                ),
            )
        )
    )

    request = panel.build_request(gui_inputs, tmp_path / "output")

    assert request.mode is OptimizationMode.BALANCED
    assert request.weight_mode is WeightMode.FRAME_TIME_US
    assert request.restart.mode is RestartMode.ADAPTIVE
    assert request.enable_triple_search is False
    assert panel.weight_combo.count() == 2
    assert panel.tolerance_spin.isEnabled()
    assert not panel.fixed_attempts_spin.isEnabled()

    panel.weight_combo.setCurrentIndex(0)
    payload_request = panel.build_request(gui_inputs, tmp_path / "payload-output")
    assert payload_request.weight_mode is WeightMode.PAYLOAD_BYTES
    assert payload_request.mode is OptimizationMode.PEAK
    assert not panel.mode_combo.isEnabled()

    panel.weight_combo.setCurrentIndex(1)
    physical_request = panel.build_request(gui_inputs, tmp_path / "physical-output")
    assert physical_request.weight_mode is WeightMode.FRAME_TIME_US
    assert physical_request.mode is OptimizationMode.BALANCED
    assert panel.mode_combo.isEnabled()

    panel.restart_combo.setCurrentIndex(1)
    assert panel.fixed_attempts_spin.isEnabled()
    assert not panel.adaptive_min_spin.isEnabled()


def test_without_arxml_only_payload_weight_is_available_and_peak_is_forced(
    qtbot, gui_inputs: InputInspectionRequest, tmp_path: Path
) -> None:
    inspection = InputInspectionRequest(gui_inputs.dbc_path, gui_inputs.config_path)
    summary = MockBackend(delay_seconds=0).inspect_input(
        inspection, lambda _update: None, CancellationToken()
    )
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_input_summary(summary)

    assert panel.weight_combo.count() == 1
    assert WeightMode(panel.weight_combo.currentData()) is WeightMode.PAYLOAD_BYTES
    assert not panel.weight_combo.isEnabled()
    assert panel.mode_combo.currentData() == OptimizationMode.PEAK.value
    assert not panel.mode_combo.isEnabled()
    assert not panel.tolerance_spin.isEnabled()

    request = panel.build_request(inspection, tmp_path / "output")
    assert request.weight_mode is WeightMode.PAYLOAD_BYTES
    assert request.mode is OptimizationMode.PEAK


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
