from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QDialogButtonBox

from canfd_offset_optimizer.gui.artifact_outputs import write_run_config_json
from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiBatchOptimizationRequest,
    JointOptimizationSettings,
    JointOptimizationView,
    JointParetoRow,
    JointRecommendationView,
    MainFunctionGroupRow,
    MainFunctionMessageRow,
    OptimizationMode,
    ParetoPrecision,
    RestartMode,
    RestartSettings,
    SenderNodeSelectionConfig,
    WeightMode,
)
from canfd_offset_optimizer.gui.joint_baseline import (
    VALIDATED_JOINT_ATTEMPTS,
    VALIDATED_JOINT_MAX_REFINEMENT_PASSES,
)
from canfd_offset_optimizer.gui.formatting import format_milliseconds_compact
from canfd_offset_optimizer.gui.widgets.joint_optimization_dialog import (
    JointOptimizationDialog,
    RHO_HELP_TEXT,
)
from canfd_offset_optimizer.gui.widgets.joint_result_page import (
    JointOptimizationResultPage,
)
from canfd_offset_optimizer.gui.widgets.settings_panel import SettingsPanel
from canfd_offset_optimizer.gui.real_backend import RealBackend
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.optimization.joint_analysis import (
    select_joint_recommendation,
)
import canfd_offset_optimizer.gui.real_backend as real_backend_module


def test_joint_settings_are_exact_immutable_and_map_precision() -> None:
    defaults = JointOptimizationSettings()
    assert defaults.peak_tolerance_relative == 0.05
    assert defaults.rho == Fraction(1)
    assert defaults.epsilon_points == 21
    fine = JointOptimizationSettings.from_values(
        0.125, "0.1", ParetoPrecision.FINE
    )
    assert fine.rho == Fraction(1, 10)
    assert fine.epsilon_points == 41
    with pytest.raises((FrozenInstanceError, AttributeError)):
        fine.rho = Fraction(3)  # type: ignore[misc]
    with pytest.raises(ValueError, match="positive"):
        JointOptimizationSettings.from_values(rho=0)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        JointOptimizationSettings.from_values(1.1)


def test_settings_panel_joint_toggle_preserves_ordinary_mode_and_expert_values(
    qtbot, inspection
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(OptimizationMode.PEAK)
    )
    panel.fixed_attempts_spin.setValue(77)
    assert not panel.joint_checkbox.isChecked()
    assert not panel.joint_config_button.isEnabled()
    assert panel.advanced_button.isEnabled()

    panel.joint_checkbox.setChecked(True)
    assert panel.joint_config_button.isEnabled()
    assert panel.mode_stack.currentWidget() is panel.mode_unavailable_label
    assert panel.mode_unavailable_label.text() == "联合优化中，不使用该参数"
    assert not panel.advanced_button.isEnabled()
    request = panel.build_request()
    assert request.joint_settings == JointOptimizationSettings()
    assert request.mode is OptimizationMode.PEAK

    panel.joint_checkbox.setChecked(False)
    assert panel.mode_stack.currentWidget() is panel.mode_combo
    assert panel.advanced_button.isEnabled()
    assert panel.fixed_attempts_spin.value() == 77
    assert OptimizationMode(panel.mode_combo.currentData()) is OptimizationMode.PEAK


def test_joint_dialog_is_transactional_and_help_is_complete(qtbot) -> None:
    original = JointOptimizationSettings()
    cancelled = JointOptimizationDialog(original)
    qtbot.addWidget(cancelled)
    cancelled.rho_spin.setValue(30)
    cancelled.reject()
    assert cancelled.settings is None
    assert original.rho == 1

    accepted = JointOptimizationDialog(original)
    qtbot.addWidget(accepted)
    accepted.rho_spin.setValue(30)
    accepted.peak_tolerance_spin.setValue(7.5)
    accepted.precision_combo.setCurrentIndex(
        accepted.precision_combo.findData(ParetoPrecision.FINE)
    )
    ok = accepted.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None
    qtbot.mouseClick(ok, Qt.MouseButton.LeftButton)

    # Calling the slot directly avoids platform-specific native dialog behavior.
    if accepted.settings is None:
        accepted._commit_and_accept()
    assert accepted.settings is not None
    assert accepted.settings.rho == 30
    assert accepted.settings.peak_tolerance_relative == 0.075
    assert accepted.settings.epsilon_points == 41
    for required in (
        "C(N)",
        "C0",
        "C1",
        "ρ = C0/C1",
        "CPU Cost Proxy",
        "实际 CPU 利用率",
        "3～5",
        "Com_MainFunctionTx",
    ):
        assert required in RHO_HELP_TEXT
    cancelled.close()
    accepted.close()
    QApplication.processEvents()


def _joint_view(*, recommendation: bool = True) -> JointOptimizationView:
    hash_a = "a" * 64
    hash_b = "b" * 64
    settings = JointOptimizationSettings()
    rows = (
        JointParetoRow(0, 100, Fraction(20), 10, 1, hash_a, "can"),
        JointParetoRow(
            1, 120, Fraction(10), 10, 1, hash_b, "cpu", recommendation
        ),
    )
    recommendation_view = JointRecommendationView(
        "geometric_knee" if recommendation else "no_interior_knee",
        hash_b if recommendation else None,
        "diagnosis",
        120 if recommendation else None,
        Fraction(10) if recommendation else None,
        10 if recommendation else None,
        1 if recommendation else None,
    )
    groups = (
        MainFunctionGroupRow(
            1,
            5_000,
            Fraction(10),
            (MainFunctionMessageRow("M", 20_000, 5_000, 5_000),),
        ),
    ) if recommendation else ()
    return JointOptimizationView(
        "ok",
        settings,
        rows,
        recommendation_view,
        hash_a,
        hash_b,
        hash_a,
        10,
        1,
        1,
        2,
        3,
        "refinement_limit_reached",
        groups,
    )


def test_joint_result_page_is_read_only_and_no_recommendation_fails_closed(
    qtbot,
) -> None:
    page = JointOptimizationResultPage()
    qtbot.addWidget(page)
    view = _joint_view()
    page.set_result(view)
    assert (
        page.pareto_table.selectionMode()
        is QAbstractItemView.SelectionMode.NoSelection
    )
    assert not hasattr(page.pareto_canvas, "point_selected")
    assert page._view is view

    no_recommendation = _joint_view(recommendation=False)
    page.set_result(no_recommendation)
    assert "不会默认采用端点" in page.diagnosis_label.text()
    assert page.group_table.rowCount() == 0
    page.close()
    QApplication.processEvents()


def test_joint_result_page_shows_exact_microseconds_and_readable_milliseconds(
    qtbot,
) -> None:
    assert format_milliseconds_compact(5_000) == "5"
    assert format_milliseconds_compact(20_000) == "20"
    assert format_milliseconds_compact(1_500) == "1.5"
    assert format_milliseconds_compact(1_250) == "1.25"
    assert format_milliseconds_compact(1) == "0.001"

    messages = (
        MainFunctionMessageRow("M5", 20_000, 5_000, 5_000),
        MainFunctionMessageRow("M1_5", 20_000, 1_500, 1_500),
        MainFunctionMessageRow("M0_001", 20_000, 1, 1),
    )
    view = replace(
        _joint_view(),
        main_function_groups=(
            MainFunctionGroupRow(1, 5_000, Fraction(10), messages),
        ),
    )
    page = JointOptimizationResultPage()
    qtbot.addWidget(page)
    page.set_result(view)

    headers = [
        page.group_table.horizontalHeaderItem(column).text()
        for column in range(page.group_table.columnCount())
    ]
    assert headers == [
        "组",
        "TimeBase (μs)",
        "TimeBase (ms)",
        "报文",
        "Cycle (ms)",
        "Offset (ms)",
        "D (μs)",
        "D (ms)",
    ]
    assert page.group_table.item(0, 1).text() == "5000"
    assert page.group_table.item(0, 2).text() == "5"
    assert page.group_table.item(0, 4).text() == "20"
    assert page.group_table.item(0, 5).text() == "5"
    assert page.group_table.item(0, 6).text() == "5000"
    assert page.group_table.item(0, 7).text() == "5"
    assert page.group_table.item(1, 7).text() == "1.5"
    assert page.group_table.item(2, 7).text() == "0.001"
    assert messages[0].d_us == 5_000
    assert messages[1].d_us == 1_500
    assert messages[2].d_us == 1
    page.close()
    QApplication.processEvents()


def test_main_window_shows_joint_tab_only_for_joint_batch(
    qtbot, batch_request
) -> None:
    backend = FixtureBackend(
        workspace_root=batch_request.inspection.session.workspace_root,
        delay_seconds=0,
    )
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    joint_batch = backend.optimize_all_networks(
        replace(batch_request, joint_settings=JointOptimizationSettings()),
        lambda _update: None,
        CancellationToken(),
    )
    window._apply_batch_result(joint_batch)
    joint_item = joint_batch.network_results[0]
    window._select_network(joint_item.network_id)
    assert window.tabs.isTabVisible(window._joint_tab_index)
    assert window.joint_result_page._view is joint_item.joint

    ordinary_batch = backend.optimize_all_networks(
        batch_request,
        lambda _update: None,
        CancellationToken(),
    )
    window._apply_batch_result(ordinary_batch)
    ordinary_item = ordinary_batch.network_results[0]
    window._select_network(ordinary_item.network_id)
    assert not window.tabs.isTabVisible(window._joint_tab_index)
    assert window.joint_result_page._view is None
    window.close()
    QApplication.processEvents()


def test_joint_run_config_records_visible_and_hidden_settings(
    qtbot, inspection, tmp_path: Path
) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspection)
    panel.joint_checkbox.setChecked(True)
    path = write_run_config_json(panel.build_request(), tmp_path / "run.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["joint_enabled"] is True
    assert payload["joint"] == {
        "peak_tolerance_relative": 0.05,
        "rho": "1",
        "rho_numerator": 1,
        "rho_denominator": 1,
        "epsilon_points": 21,
        "hidden_attempts": VALIDATED_JOINT_ATTEMPTS,
        "max_refinement_passes": VALIDATED_JOINT_MAX_REFINEMENT_PASSES,
        "seed": 0,
        "endpoint_only": False,
    }


def test_real_joint_workflow_uses_one_recommendation_and_keeps_long_period_zero(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    dbc = Path("tests/fixtures/dbc/minimal.dbc").read_text(encoding="utf-8")
    dbc = dbc.replace(
        'BA_ "GenMsgCycleTime" BO_ 2147484768 100;',
        'BA_ "GenMsgCycleTime" BO_ 2147484768 105;',
    )
    (source / "PT.dbc").write_text(dbc, encoding="utf-8")
    config = Path("tests/fixtures/config/project.yaml").read_text(encoding="utf-8")
    (source / "project.yaml").write_text(
        config.replace("hyperperiod_ms: 500", "hyperperiod_ms: auto"),
        encoding="utf-8",
    )
    backend = RealBackend(tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(
        session, lambda _update: None, token
    )
    selection = SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={
            summary.dbc_id: frozenset(
                node.node_name for node in summary.node_stats if node.selectable
            )
            for summary in inspection.sender_selection_summaries
        },
        dbc_revision=inspection.dbc_revision,
        confirmed=True,
    )
    inspection = backend.apply_sender_selection(inspection, selection)
    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.VARIANCE,
        balanced_tolerance=0.9,
        restart=RestartSettings(
            mode=RestartMode.FIXED, fixed_attempts=99
        ),
        candidate_pool_size=32,
        enable_triple_search=True,
        output_root=tmp_path / "output",
        sender_selection=inspection.sender_selection,
        joint_settings=JointOptimizationSettings(),
    )
    updates = []
    batch = backend.optimize_all_networks(request, updates.append, token)
    item = batch.network_results[0]
    assert item.result is not None
    assert item.joint is not None
    result = item.result
    assert item.joint.recommendation.solution_hash == result.assignment_hash
    assert result.joint == item.joint
    assert result.actual_attempts == VALIDATED_JOINT_ATTEMPTS
    fixed = next(row for row in result.assignments if row.message_name == "Msg460Ext")
    assert fixed.cycle_time_us == 105_000
    assert fixed.optimized_offset_us == 0
    assert item.joint.fixed_message_count == 1
    assert any(
        message.message_name == "Msg460Ext"
        for group in item.joint.main_function_groups
        for message in group.messages
    )
    assignment_offsets = {
        row.message_name: row.optimized_offset_us for row in result.assignments
    }
    heatmap_offsets = {
        message.message_name: message.offset_us
        for slot in result.steady_heatmap.optimized_slots
        for message in slot.messages
    }
    main_function_offsets = {
        message.message_name: message.offset_us
        for group in item.joint.main_function_groups
        for message in group.messages
    }
    assert heatmap_offsets == assignment_offsets
    assert main_function_offsets == assignment_offsets
    exported = {path.name: path for path in result.exported_files}
    assert {
        "joint_summary.json",
        "joint_pareto.csv",
        "main_function_recommendation.csv",
        "offsets.csv",
        "PT.dbc",
    }.issubset(exported)
    assert "Msg460Ext" in exported["main_function_recommendation.csv"].read_text(
        encoding="utf-8-sig"
    )
    written_dbc = exported["PT.dbc"].read_text(encoding="utf-8")
    assert 'BA_ "GenMsgStartDelayTime" BO_ 2147484768 0;' in written_dbc
    assert any("建立 Peak 参考" in update.message for update in updates)
    assert any("生成自动推荐" in update.message for update in updates)


def test_real_joint_no_recommendation_does_not_choose_endpoint_or_write_dbc(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "PT.dbc").write_bytes(
        Path("tests/fixtures/dbc/minimal.dbc").read_bytes()
    )
    (source / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )
    backend = RealBackend(tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(
        session, lambda _update: None, token
    )
    selection = SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={
            summary.dbc_id: frozenset(
                node.node_name for node in summary.node_stats if node.selectable
            )
            for summary in inspection.sender_selection_summaries
        },
        dbc_revision=inspection.dbc_revision,
        confirmed=True,
    )
    inspection = backend.apply_sender_selection(inspection, selection)
    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.BALANCED,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=tmp_path / "output",
        sender_selection=inspection.sender_selection,
        joint_settings=JointOptimizationSettings(),
    )
    original = real_backend_module.run_joint_optimization

    def force_two_point_front(*args, **kwargs):
        result = original(*args, **kwargs)
        distinct = []
        seen = set()
        for solution in result.archive_solutions:
            if solution.assignment_hash not in seen:
                seen.add(solution.assignment_hash)
                distinct.append(solution)
            if len(distinct) == 2:
                break
        assert len(distinct) == 2
        front = tuple(distinct)
        return replace(
            result,
            pareto_solutions=front,
            recommendation=select_joint_recommendation(front),
        )

    monkeypatch.setattr(
        real_backend_module, "run_joint_optimization", force_two_point_front
    )
    batch = backend.optimize_all_networks(request, lambda _update: None, token)
    item = batch.network_results[0]
    assert item.result is None
    assert item.joint is not None
    assert not item.joint.recommendation.has_recommendation
    assert item.status.value == "failed"
    exported = {path.name for path in item.joint.exported_files}
    assert exported == {"joint_summary.json", "joint_pareto.csv"}
    assert not tuple((batch.output_directory / "dbc").glob("*.dbc"))
