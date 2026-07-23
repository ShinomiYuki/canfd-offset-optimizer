from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    ImportSession,
    ProgressCallback,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.real_backend import RealBackend
from canfd_offset_optimizer.gui.state import WorkflowState


class CountingBackend:
    def __init__(self, backend: FixtureBackend) -> None:
        self.backend = backend
        self.import_calls = 0
        self.inspect_calls = 0
        self.optimize_calls = 0

    def import_inputs(
        self,
        sources: tuple[Path, ...],
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> ImportSession:
        self.import_calls += 1
        return self.backend.import_inputs(sources, progress_callback, cancellation_token)

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        self.inspect_calls += 1
        return self.backend.inspect_workspace(session, progress_callback, cancellation_token)

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        self.optimize_calls += 1
        return self.backend.optimize_all_networks(
            request, progress_callback, cancellation_token
        )


def import_until_ready(qtbot, window: MainWindow, sources: tuple[Path, ...]) -> None:
    window.import_sources(sources)
    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.READY,
        timeout=5_000,
    )


def _batch_with_real_hyperperiod_shapes(
    batch_result: BatchOptimizationResult, weight_mode: WeightMode
) -> tuple[BatchOptimizationResult, dict[str, int]]:
    base_item = batch_result.network_results[0]
    base = base_item.result
    assert base is not None
    slot_counts = {
        "BD": 100,
        "IC": 400,
        "GL": 200,
        "DK": 200,
        "PT": 20,
        "SU": 20,
    }
    items = []
    for name, slot_count in slot_counts.items():
        network_id = f"net-real-shape-{name.lower()}"
        detail = replace(
            base,
            network_id=network_id,
            network_name=name,
            display_name=name,
            source_file=f"{name}.dbc",
            weight_mode=weight_mode,
            steady_loads_before=tuple(range(slot_count)),
            steady_loads_after=tuple(
                1_000 + index for index in range(slot_count)
            ),
            steady_counts_before=(0,) * slot_count,
            steady_counts_after=(0,) * slot_count,
            steady_heatmap=None,
            slot_width_us=5_000,
        )
        items.append(
            replace(
                base_item,
                network_id=network_id,
                network_name=name,
                display_name=name,
                source_file=f"{name}.dbc",
                weight_mode=weight_mode,
                result=detail,
            )
        )
    return replace(batch_result, network_results=tuple(items)), slot_counts


def test_unified_import_automatically_inspects_and_enables_batch(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    backend = CountingBackend(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0)
    )
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "快速开始",
        "结果概览",
        "Offset 修改",
        "可优化报文负载曲线",
        "可优化报文负载热力图",
        "运行日志与详情",
    ]
    import_until_ready(qtbot, window, (source_project,))

    assert backend.import_calls == 1
    assert backend.inspect_calls == 1
    assert window.import_session is not None
    assert window.inspection is not None
    assert [network.network_name for network in window.inspection.networks] == ["BD", "GL", "SU"]
    assert window.input_panel.networks_label.text() == "发现网段：3 / 可优化：3 / 已跳过：0"
    assert window.settings_panel.networks_label.text() == "发现网段：3 / 可优化：3 / 已跳过：0"
    assert window.settings_panel.weight_combo.count() == 2
    assert window.progress_panel.run_button.isEnabled()


def test_batch_locks_controls_then_shows_summary_and_selected_details(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    backend = CountingBackend(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0.002)
    )
    opened: list[Path] = []
    window = MainWindow(
        backend,
        dialog_handler=lambda *_args: None,
        open_directory_handler=lambda path: opened.append(path) is None,
    )
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))

    window.start_optimization()
    assert window.workflow_state is WorkflowState.RUNNING
    assert window.task_active
    assert not window.input_panel.add_button.isEnabled()
    assert not window.settings_panel.isEnabled()
    assert window.progress_panel.cancel_button.isEnabled()
    window.start_optimization()  # duplicate start is ignored
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.SUCCEEDED,
        timeout=7_000,
    )

    assert backend.optimize_calls == 1
    assert window.result is not None
    assert window.summary_panel.model.rowCount() == 3
    assert window.summary_panel.count_label.text().startswith("成功 3")
    qtbot.waitUntil(lambda: window.selected_network is not None)
    assert window.assignment_table.model.rowCount() == 12
    assert window.load_chart.export_button.isEnabled()
    assert window.load_heatmap.export_button.isEnabled()
    assert window.load_heatmap.current_network_id == window.selected_network_id
    window.summary_panel.table.selectRow(1)
    qtbot.waitUntil(
        lambda: window.selected_network is not None
        and window.selected_network.network_name == "GL"
    )
    assert "网段：GL" in window.log_view.toPlainText()
    su = next(item for item in window.result.network_results if item.network_name == "SU")
    window.load_heatmap.network_combo.setCurrentIndex(
        window.load_heatmap.network_combo.findData(su.network_id)
    )
    qtbot.waitUntil(lambda: window.selected_network_id == su.network_id)
    assert window.load_heatmap.current_network_id == su.network_id
    assert window.load_heatmap.network_combo.currentData() == su.network_id
    window.open_output_directory()
    assert opened == [window.result.output_directory]
    heatmap_directory = window.result.output_directory / "plots"
    window.load_heatmap.open_directory_requested.emit(heatmap_directory)
    assert opened == [window.result.output_directory, heatmap_directory]


def test_partial_failure_remains_browsable_and_does_not_hide_successes(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(
            workspace_root=workspace_root,
            delay_seconds=0,
            fail_networks={"GL"},
        ),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))
    window.start_optimization()
    qtbot.waitUntil(
        lambda: not window.task_active and window.workflow_state is WorkflowState.PARTIAL,
        timeout=5_000,
    )
    assert window.result is not None
    assert window.result.succeeded_count == 2
    assert window.result.failed_count == 1
    window.summary_panel.table.selectRow(1)
    qtbot.waitUntil(
        lambda: window.selected_network is not None
        and window.selected_network.network_name == "GL"
    )
    assert window.assignment_table.model.rowCount() == 0
    assert "模拟网段 GL 优化失败" in window.log_view.toPlainText()


def test_dbc_write_warning_keeps_gui_result_browsable(
    qtbot, batch_result: BatchOptimizationResult, workspace_root: Path
) -> None:
    first = batch_result.network_results[0]
    assert first.result is not None
    detail = replace(first.result, dbc_write_error="FileNotFoundError: path too long")
    warned = replace(
        first,
        result=detail,
        warnings=first.warnings + ("DBC 写回失败；其他输出已保留",),
    )
    batch = replace(
        batch_result,
        network_results=(warned, *batch_result.network_results[1:]),
    )
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)

    window._apply_batch_result(batch)
    assert window.summary_panel.select_network_id(warned.network_id)
    qtbot.waitUntil(lambda: window.selected_network_id == warned.network_id)

    assert window.assignment_table.model.rowCount() > 0
    assert window.load_chart.export_button.isEnabled()
    assert "DBC输出：失败（优化结果及其他输出已保留）" in window.log_view.toPlainText()
    assert "FileNotFoundError: path too long" in window.log_view.toPlainText()
    assert "DBC写回失败 1" in window.summary_panel.count_label.text()


@pytest.mark.parametrize(
    "weight_mode",
    (WeightMode.FRAME_TIME_US, WeightMode.PAYLOAD_BYTES),
)
def test_real_hyperperiod_shapes_keep_every_result_page_on_one_network(
    qtbot,
    batch_result: BatchOptimizationResult,
    workspace_root: Path,
    weight_mode: WeightMode,
) -> None:
    batch, slot_counts = _batch_with_real_hyperperiod_shapes(
        batch_result, weight_mode
    )
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window._apply_batch_result(batch)

    sequence = ("BD", "IC", "GL", "DK", "PT", "SU", "IC", "BD")
    by_name = {item.network_name: item for item in batch.network_results}
    for heatmap_window in (0, 1):
        window.load_heatmap.window_combo.setCurrentIndex(heatmap_window)
        for _ in range(2):
            for name in sequence:
                item = by_name[name]
                assert item.result is not None
                combo_index = window.load_heatmap.network_combo.findData(
                    item.network_id
                )
                window.load_heatmap.network_combo.setCurrentIndex(combo_index)
                qtbot.waitUntil(
                    lambda network_id=item.network_id: (
                        window.selected_network_id == network_id
                    )
                )

                assert (
                    window.assignment_table.current_network_id
                    == item.network_id
                )
                assert window.load_chart.current_network_id == item.network_id
                assert window.load_heatmap.current_network_id == item.network_id
                assert window.load_heatmap.view_model is not None
                assert (
                    window.load_heatmap.view_model.network_id
                    == item.network_id
                )
                expected_heatmap_slots = (
                    slot_counts[name]
                    if heatmap_window == 0
                    else len(item.result.original_startup_load)
                )
                assert (
                    window.load_heatmap.view_model.slot_count
                    == expected_heatmap_slots
                )
                assert len(window.load_chart.canvas.before_series) == (
                    slot_counts[name] * 4
                )
                assert window.load_chart.canvas.display_duration_ms == (
                    slot_counts[name] * 5 * 4
                )
                assert item.network_id in window.log_view.toPlainText()
                assert (
                    window.details_network_label.text()
                    == f"当前网段：{name}"
                )

    window.load_chart.window_combo.setCurrentIndex(1)
    for name in sequence:
        item = by_name[name]
        assert item.result is not None
        window.load_heatmap.network_combo.setCurrentIndex(
            window.load_heatmap.network_combo.findData(item.network_id)
        )
        qtbot.waitUntil(
            lambda network_id=item.network_id: (
                window.selected_network_id == network_id
            )
        )
        assert (
            window.load_chart.canvas.before_series
            == item.result.original_startup_load
        )
        assert window.load_chart.canvas.display_duration_ms == (
            item.result.load_window_metadata.startup_duration_ms
        )


def test_one_panel_failure_does_not_abort_network_selection_or_leak_qt_exception(
    qtbot,
    batch_result: BatchOptimizationResult,
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window._apply_batch_result(batch_result)
    target = batch_result.network_results[1]
    assert target.result is not None
    leaked: list[tuple[type[BaseException], BaseException]] = []

    def exception_hook(
        exception_type: type[BaseException],
        value: BaseException,
        traceback_object: object,
    ) -> None:
        del traceback_object
        leaked.append((exception_type, value))

    def fail_chart(_result: object) -> None:
        raise ValueError("injected chart presentation failure")

    monkeypatch.setattr(sys, "excepthook", exception_hook)
    monkeypatch.setattr(window.load_chart, "set_result", fail_chart)

    index = window.load_heatmap.network_combo.findData(target.network_id)
    window.load_heatmap.network_combo.setCurrentIndex(index)
    qtbot.waitUntil(lambda: window.selected_network_id == target.network_id)

    assert leaked == []
    assert window.assignment_table.current_network_id == target.network_id
    assert window.load_chart.current_network_id == target.network_id
    assert window.load_heatmap.current_network_id == target.network_id
    assert window.load_heatmap.view_model is not None
    assert window.load_heatmap.view_model.network_id == target.network_id
    assert window.details_network_label.text() == (
        f"当前网段：{target.display_name}"
    )
    assert "负载曲线展示失败：ValueError" in (
        window.load_chart.chart_title_label.text()
    )
    log = window.log_view.toPlainText()
    assert target.network_id in log
    assert "injected chart presentation failure" in log
    assert "Traceback (most recent call last)" in log


def test_missing_dbc_is_explicit_while_default_config_is_automatic(
    qtbot, tmp_path: Path, workspace_root: Path
) -> None:
    project = tmp_path / "incomplete"
    project.mkdir()
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window.import_sources((project,))
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.INCOMPLETE,
        timeout=5_000,
    )
    assert "DBC" in window.input_panel.required_label.text()
    assert "项目配置" not in window.input_panel.required_label.text()
    assert window.import_session is not None
    assert (window.import_session.session_directory / "config/project.yaml").is_file()
    assert not window.progress_panel.run_button.isEnabled()
    assert not window.settings_panel.isEnabled()


def test_single_dbc_without_user_config_uses_default_and_is_ready(
    qtbot, tmp_path: Path, workspace_root: Path
) -> None:
    dbc = tmp_path / "PT.dbc"
    dbc.write_text("PT", encoding="utf-8")
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)

    import_until_ready(qtbot, window, (dbc,))

    assert window.inspection is not None
    assert window.inspection.missing_required == ()
    assert window.inspection.can_optimize
    assert window.progress_panel.status_label.text() == "全部网段已就绪"
    assert window.progress_panel.run_button.isEnabled()
    assert window.import_session is not None
    assert (window.import_session.session_directory / "config/project.yaml").is_file()


def test_single_unoptimizable_dbc_shows_precise_blocking_reason(
    qtbot, tmp_path: Path, workspace_root: Path
) -> None:
    dbc = tmp_path / "BD.dbc"
    classic = Path("tests/fixtures/dbc/minimal.dbc").read_text(encoding="utf-8").replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    )
    dbc.write_text(classic, encoding="utf-8")
    window = MainWindow(
        RealBackend(workspace_root=workspace_root),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window.import_sources((dbc,))
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.AWAITING_SENDER_SELECTION,
        timeout=5_000,
    )

    assert window.inspection is not None
    assert window.inspection.missing_required == ()
    assert not window.inspection.sender_selection_ready
    assert "待选择 DBC 本机发送节点" in window.input_panel.required_label.text()
    assert window.progress_panel.status_label.text() == "请先完成 DBC 本机发送节点选择。"
    assert not window.progress_panel.run_button.isEnabled()


def test_clear_only_resets_current_gui_session_and_keeps_import_history(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))
    assert window.import_session is not None
    session_directory = window.import_session.session_directory
    window.clear_current_session()
    assert window.workflow_state is WorkflowState.IDLE
    assert window.import_session is None
    assert session_directory.is_dir()
    assert "未删除" in window.log_view.toPlainText()
