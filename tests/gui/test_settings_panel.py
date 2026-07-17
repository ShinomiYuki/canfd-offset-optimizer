from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    OptimizationMode,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.widgets.settings_panel import SettingsPanel


def test_arxml_project_can_choose_both_weight_modes(
    qtbot, inspection: WorkspaceInspection
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    assert panel.weight_combo.count() == 2
    assert WeightMode(panel.weight_combo.currentData()) is WeightMode.FRAME_TIME_US
    assert OptimizationMode(panel.mode_combo.currentData()) is OptimizationMode.BALANCED
    assert panel.mode_combo.isEnabled()


def test_dbc_only_project_forces_payload_and_peak(
    qtbot, workspace_root: Path, tmp_path: Path
) -> None:
    source = tmp_path / "dbc_only"
    source.mkdir()
    (source / "PT.dbc").write_text("PT", encoding="utf-8")
    (source / "project.yaml").write_text("project: demo", encoding="utf-8")
    backend = FixtureBackend(workspace_root=workspace_root, delay_seconds=0)
    session = backend.import_inputs((source,), lambda _u: None, CancellationToken())
    inspection = backend.inspect_workspace(session, lambda _u: None, CancellationToken())
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    assert panel.weight_combo.count() == 1
    assert WeightMode(panel.weight_combo.currentData()) is WeightMode.PAYLOAD_BYTES
    assert not panel.weight_combo.isEnabled()
    assert OptimizationMode(panel.mode_combo.currentData()) is OptimizationMode.PEAK
    assert not panel.mode_combo.isEnabled()
    request = panel.build_request()
    assert request.weight_mode is WeightMode.PAYLOAD_BYTES
    assert request.mode is OptimizationMode.PEAK
