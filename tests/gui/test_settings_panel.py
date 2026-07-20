from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    OptimizationMode,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.artifact_outputs import write_run_config_json
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
    request = panel.build_request()
    assert request.offset_search.candidate_offsets_ms == tuple(range(15, 101, 5))


def test_offset_search_controls_build_non_divisible_request(
    qtbot, inspection: WorkspaceInspection
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    panel.offset_min_spin.setValue(15)
    panel.offset_max_spin.setValue(102)
    panel.offset_step_spin.setValue(10)
    request = panel.build_request()
    assert request.offset_search.candidate_offsets_ms == tuple(range(15, 96, 10))
    assert "9" in panel.offset_summary_label.text()


def test_invalid_offset_range_blocks_request(
    qtbot, inspection: WorkspaceInspection
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    panel.offset_min_spin.setValue(200)
    panel.offset_max_spin.setValue(100)
    assert "无效" in panel.offset_summary_label.text()
    with pytest.raises(ValueError, match="max_offset_ms"):
        panel.build_request()


def test_run_config_exports_effective_offset_search_metadata(
    qtbot, inspection: WorkspaceInspection, tmp_path: Path
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    panel.offset_min_spin.setValue(15)
    panel.offset_max_spin.setValue(102)
    panel.offset_step_spin.setValue(10)
    path = write_run_config_json(panel.build_request(), tmp_path / "run_config.json")
    assert json.loads(path.read_text(encoding="utf-8"))["offset_search"] == {
        "min_offset_ms": 15,
        "max_offset_ms": 102,
        "offset_step_ms": 10,
        "effective_max_offset_ms": 95,
        "candidate_count": 9,
    }


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


def test_skipped_networks_do_not_remove_weights_supported_by_optimizable_networks(
    qtbot, inspection: WorkspaceInspection
) -> None:
    skipped = replace(
        inspection.networks[0],
        is_optimizable=False,
        available_weight_modes=(),
        unoptimizable_reason="经典 CAN，不参与优化",
    )
    mixed_inspection = replace(
        inspection,
        networks=(skipped, *inspection.networks[1:]),
    )
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    panel.set_inspection(mixed_inspection)

    assert panel.weight_combo.count() == 2
    assert WeightMode(panel.weight_combo.currentData()) is WeightMode.FRAME_TIME_US
    request = panel.build_request()
    assert request.inspection is mixed_inspection
    assert request.weight_mode is WeightMode.FRAME_TIME_US


def test_classic_weight_is_fixed_while_fd_weight_remains_selectable(
    qtbot, inspection: WorkspaceInspection
) -> None:
    classic = replace(
        inspection.networks[0],
        frame_protocol=FrameProtocol.CLASSIC_CAN,
        available_weight_modes=(WeightMode.PAYLOAD_BYTES,),
        automatic_weight_mode=WeightMode.PAYLOAD_BYTES,
        classic_weight_model=CLASSIC_WEIGHT_MODEL,
    )
    mixed = replace(inspection, networks=(classic, *inspection.networks[1:]))
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(mixed)

    assert panel.weight_combo.count() == 2
    assert WeightMode(panel.weight_combo.currentData()) is WeightMode.FRAME_TIME_US
    assert "只应用于 CAN FD" in panel.weight_combo.toolTip()
    assert OptimizationMode(panel.mode_combo.currentData()) is OptimizationMode.PEAK
    assert not panel.mode_combo.isEnabled()
    request = panel.build_request()
    assert request.weight_mode is WeightMode.FRAME_TIME_US
