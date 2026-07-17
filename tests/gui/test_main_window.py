from __future__ import annotations

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
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.state import WorkflowState


class CountingBackend:
    def __init__(self, backend: MockBackend) -> None:
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
        MockBackend(workspace_root=workspace_root, delay_seconds=0)
    )
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    import_until_ready(qtbot, window, (source_project,))

    assert backend.import_calls == 1
    assert backend.inspect_calls == 1
    assert window.import_session is not None
    assert window.inspection is not None
    assert [network.network_name for network in window.inspection.networks] == ["BD", "GL", "SU"]
    assert window.input_panel.networks_label.text() == "已发现网段：3 个"
    assert window.settings_panel.networks_label.text() == "已发现网段：3 个"
    assert window.settings_panel.weight_combo.count() == 2
    assert window.progress_panel.run_button.isEnabled()


def test_batch_locks_controls_then_shows_summary_and_selected_details(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    backend = CountingBackend(
        MockBackend(workspace_root=workspace_root, delay_seconds=0.002)
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
    window.summary_panel.table.selectRow(1)
    qtbot.waitUntil(
        lambda: window.selected_network is not None
        and window.selected_network.network_name == "GL"
    )
    assert "网段：GL" in window.log_view.toPlainText()
    window.open_output_directory()
    assert opened == [window.result.output_directory]


def test_partial_failure_remains_browsable_and_does_not_hide_successes(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        MockBackend(
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


def test_missing_required_input_is_explicit_and_batch_stays_disabled(
    qtbot, tmp_path: Path, workspace_root: Path
) -> None:
    project = tmp_path / "incomplete"
    project.mkdir()
    (project / "DA.dbc").write_text("DA", encoding="utf-8")
    window = MainWindow(
        MockBackend(workspace_root=workspace_root, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window.import_sources((project,))
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.INCOMPLETE,
        timeout=5_000,
    )
    assert "项目配置" in window.input_panel.required_label.text()
    assert not window.progress_panel.run_button.isEnabled()
    assert not window.settings_panel.isEnabled()


def test_clear_only_resets_current_gui_session_and_keeps_import_history(
    qtbot, source_project: Path, workspace_root: Path
) -> None:
    window = MainWindow(
        MockBackend(workspace_root=workspace_root, delay_seconds=0),
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
