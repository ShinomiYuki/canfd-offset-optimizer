from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    NetworkRunStatus,
    RestartMode,
    RestartSettings,
)
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.state import WorkflowState
from canfd_offset_optimizer.gui.view_models import BatchSummaryTableModel

from test_main_window import import_until_ready


def _run_window(qtbot, window: MainWindow, source_project: Path) -> None:
    import_until_ready(qtbot, window, (source_project,))
    window.start_optimization()
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state in {WorkflowState.SUCCEEDED, WorkflowState.PARTIAL},
        timeout=7_000,
    )


def _item_by_name(batch: BatchOptimizationResult, name: str):
    return next(item for item in batch.network_results if item.network_name == name)


def _select_visible_id(qtbot, window: MainWindow, network_id: str) -> None:
    panel = window.summary_panel
    for row in range(panel.proxy.rowCount()):
        index = panel.proxy.index(row, 0)
        if index.data(BatchSummaryTableModel.NETWORK_ID_ROLE) == network_id:
            panel.table.setCurrentIndex(index)
            panel.table.selectRow(row)
            qtbot.waitUntil(lambda: window.selected_network_id == network_id)
            return
    raise AssertionError(f"network ID is not visible in proxy: {network_id}")


def test_main_window_uses_count_summary_and_shared_live_details_models(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))

    assert window.settings_panel.networks_label.text() == "发现网段：3 / 可优化：3 / 已跳过：0"
    assert window.input_panel.networks_label.text() == "发现网段：3 / 可优化：3 / 已跳过：0"
    assert not hasattr(window.input_panel, "tree")
    assert all(
        name not in window.settings_panel.networks_label.text()
        for name in ("BD", "GL", "SU")
    )
    window.settings_panel.details_button.click()
    dialog = window.input_panel.details_dialog
    qtbot.waitUntil(dialog.isVisible)
    assert dialog.weight_strategy_label.text() == (
        "权重策略：按物理网段独立应用\n"
        "Classic CAN：固定为 Payload 长度近似（payload_bytes）\n"
        "CAN FD：使用批量优化设置中的 CAN FD 权重"
    )
    assert dialog.tabs.count() == 4
    assert [dialog.tabs.tabText(index) for index in range(4)] == [
        "网段详情",
        "导入文件详情",
        "发送节点筛选",
        "路由报文排除",
    ]
    assert dialog.network_table.model() is window.input_panel.network_details_model
    assert dialog.import_table.model() is window.input_panel.import_details_model
    assert dialog.network_table.model().rowCount() == 3
    assert window.import_session is not None
    assert dialog.import_table.model().rowCount() == len(window.import_session.records)
    assert dialog.network_table.model().columnCount() == 13
    assert dialog.import_table.model().columnCount() == 6
    assert dialog.import_table.model().index(0, 4).data() != "—"
    dialog.hide()
    window.clear_current_session()
    assert dialog.network_table.model().rowCount() == 0
    assert dialog.import_table.model().rowCount() == 0


def test_network_identity_separates_short_name_from_long_source(
    inspection,
) -> None:
    assert [network.network_name for network in inspection.networks] == ["BD", "GL", "SU"]
    assert len({network.network_id for network in inspection.networks}) == 3
    for network in inspection.networks:
        assert network.display_name == network.network_name
        assert network.source_file.endswith(".dbc")
        assert "Message list" in network.source_file
        assert network.network_name not in {network.source_file, network.network_id}
        assert not network.source_workspace_path.is_absolute()


def test_fixture_results_are_independent_deterministic_and_mathematically_consistent(
    backend: FixtureBackend, batch_request: GuiBatchOptimizationRequest
) -> None:
    adaptive = RestartSettings(
        mode=RestartMode.ADAPTIVE,
        fixed_attempts=16,
        min_attempts=16,
        max_attempts=30,
    )
    request = GuiBatchOptimizationRequest(
        inspection=batch_request.inspection,
        can_fd_weight=batch_request.can_fd_weight,
        classic_can_weight=batch_request.classic_can_weight,
        mode=batch_request.mode,
        balanced_tolerance=batch_request.balanced_tolerance,
        restart=adaptive,
        candidate_pool_size=batch_request.candidate_pool_size,
        enable_triple_search=batch_request.enable_triple_search,
        output_root=batch_request.output_root,
    )
    first = backend.optimize_all_networks(request, lambda _u: None, CancellationToken())
    second = backend.optimize_all_networks(request, lambda _u: None, CancellationToken())

    first_results = [item.result for item in first.network_results]
    assert all(result is not None for result in first_results)
    concrete = [result for result in first_results if result is not None]
    assert len({id(result) for result in concrete}) == 3
    assert len({id(result.original_metrics) for result in concrete}) == 3
    assert len({id(result.optimized_metrics) for result in concrete}) == 3
    assert len({id(result.assignments) for result in concrete}) == 3
    assert len({id(result.original_steady_load) for result in concrete}) == 3
    assert len({id(result.optimized_steady_load) for result in concrete}) == 3
    assert len({id(result.original_startup_load) for result in concrete}) == 3
    assert len({id(result.optimized_startup_load) for result in concrete}) == 3
    assert len({result.optimized_metrics.standard_deviation for result in concrete}) == 3
    assert len({item.zss_improvement for item in first.network_results}) == 3
    assert len({result.actual_attempts for result in concrete}) >= 2

    for item in first.network_results:
        result = item.result
        assert result is not None
        assert result.optimized_metrics.zss <= result.original_metrics.zss
        assert item.zss_improvement == (
            result.original_metrics.zss - result.optimized_metrics.zss
        )
        again = second.results_by_network_id[item.network_id]
        assert (
            result.original_metrics,
            result.optimized_metrics,
            result.assignments,
            result.actual_attempts,
            result.stop_reason,
            result.elapsed_seconds,
            result.steady_loads_before,
            result.steady_loads_after,
            result.startup_loads_before,
            result.startup_loads_after,
        ) == (
            again.original_metrics,
            again.optimized_metrics,
            again.assignments,
            again.actual_attempts,
            again.stop_reason,
            again.elapsed_seconds,
            again.steady_loads_before,
            again.steady_loads_after,
            again.startup_loads_before,
            again.startup_loads_after,
        )
    with pytest.raises(TypeError):
        first.results_by_network_id["other"] = concrete[0]  # type: ignore[index]


def test_selection_after_sort_and_filter_drives_all_details_by_network_id(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    _run_window(qtbot, window, source_project)
    assert window.result is not None

    bd = _item_by_name(window.result, "BD")
    gl = _item_by_name(window.result, "GL")
    su = _item_by_name(window.result, "SU")
    assert window.selected_network_id == bd.network_id  # first successful result
    assert window.assignment_table.model.index(0, 0).data().startswith("BD_")
    assert "SU_" not in window.assignment_table.model.index(0, 0).data()

    window.summary_panel.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    qtbot.wait(10)
    _select_visible_id(qtbot, window, gl.network_id)
    assert gl.result is not None
    assert window.assignment_table.current_network_id == gl.network_id
    assert window.load_chart.current_network_id == gl.network_id
    assert window.load_chart.canvas.before_series == gl.result.original_steady_load * 4
    assert window.load_chart.canvas.after_series == gl.result.optimized_steady_load * 4
    assert window.load_chart.canvas.before_series is not gl.result.original_steady_load
    assert "GL / 可优化报文稳态负载，500 ms 超周期重复展示 4 次" in (
        window.load_chart.chart_title_label.text()
    )
    assert gl.network_id in window.log_view.toPlainText()

    window.summary_panel.network_filter.setText("SU")
    qtbot.waitUntil(lambda: window.summary_panel.proxy.rowCount() == 1)
    _select_visible_id(qtbot, window, su.network_id)
    assert window.assignment_table.current_network_id == su.network_id
    assert window.load_chart.current_network_id == su.network_id
    assert su.result is not None
    assert window.load_chart.canvas.before_series == su.result.original_steady_load * 4
    assert window.load_chart.canvas.after_series == su.result.optimized_steady_load * 4
    assert window.load_chart.canvas.before_series is not su.result.original_steady_load
    assert window.load_chart.canvas.before_series is not gl.result.original_steady_load
    assert "SU / 可优化报文稳态负载，500 ms 超周期重复展示 4 次" in (
        window.load_chart.chart_title_label.text()
    )
    assert su.network_id in window.log_view.toPlainText()
    assert window.summary_panel.proxy.index(0, 0).data() == "SU"
    assert "Message list" in window.summary_panel.proxy.index(0, 1).data()


def test_failed_selection_clears_success_data_and_no_selection_has_placeholder(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        FixtureBackend(
            workspace_root=workspace_root,
            delay_seconds=0,
            fail_networks={"BD", "SU"},
        ),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    _run_window(qtbot, window, source_project)
    assert window.result is not None
    gl = _item_by_name(window.result, "GL")
    su = _item_by_name(window.result, "SU")
    assert gl.status is NetworkRunStatus.SUCCEEDED
    assert su.status is NetworkRunStatus.FAILED
    assert gl.network_id in window.result.results_by_network_id
    assert su.network_id not in window.result.results_by_network_id
    assert su.network_id in window.result.network_items_by_id
    assert window.selected_network_id == gl.network_id  # skips failed BD, selects first success
    assert window.assignment_table.model.rowCount() == 12

    _select_visible_id(qtbot, window, su.network_id)
    assert window.assignment_table.model.rowCount() == 0
    assert window.load_chart.canvas.before_series == ()
    assert window.load_chart.canvas.after_series == ()
    assert window.load_chart.chart_title_label.text() == "可优化报文负载曲线：无成功结果"
    assert window.assignment_table.current_network_id == su.network_id
    assert window.load_chart.current_network_id == su.network_id
    assert "模拟网段 SU 优化失败" in window.log_view.toPlainText()

    window.summary_panel.table.clearSelection()
    window.summary_panel.table.setCurrentIndex(QModelIndex())
    qtbot.waitUntil(lambda: window.selected_network_id is None)
    assert window.assignment_table.current_network_id is None
    assert window.load_chart.current_network_id is None
    assert window.assignment_table.model.rowCount() == 0
    assert window.load_chart.canvas.before_series == ()
    assert window.details_network_label.text() == "当前网段：请选择一个网段"
    assert window.log_view.toPlainText() == "请选择一个网段"
