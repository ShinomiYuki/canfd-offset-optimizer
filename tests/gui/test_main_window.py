from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    ImportSession,
    ProgressCallback,
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
