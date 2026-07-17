from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest

from canfd_offset_optimizer.gui.contracts import (
    BackendError,
    BatchOptimizationCancelled,
    BatchRunStatus,
    CancellationToken,
    GuiBatchOptimizationRequest,
    InputKind,
    NetworkRunStatus,
    ProgressPhase,
    RestartMode,
    RestartSettings,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.mock_backend import MockBackend


def test_inspection_discovers_every_dbc_network_from_workspace(
    backend: MockBackend, inspection: WorkspaceInspection
) -> None:
    assert [network.network_name for network in inspection.networks] == ["BD", "GL", "SU"]
    assert all(network.message_count > 0 for network in inspection.networks)
    assert all(
        network.available_weight_modes
        == (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US)
        for network in inspection.networks
    )
    assert inspection.can_optimize
    assert all(
        record.used_by_parser
        for record in inspection.session.records
        if record.kind in {InputKind.DBC, InputKind.CONFIG, InputKind.ARXML}
    )


def test_dbc_without_arxml_only_offers_payload_weight(
    workspace_root: Path, tmp_path: Path
) -> None:
    root = tmp_path / "payload_project"
    root.mkdir()
    (root / "PT.dbc").write_text("PT", encoding="utf-8")
    (root / "project.yaml").write_text("project: payload", encoding="utf-8")
    backend = MockBackend(workspace_root=workspace_root, delay_seconds=0)
    session = backend.import_inputs((root,), lambda _u: None, CancellationToken())
    inspection = backend.inspect_workspace(session, lambda _u: None, CancellationToken())
    assert inspection.networks[0].available_weight_modes == (WeightMode.PAYLOAD_BYTES,)


def test_multiple_project_configs_are_an_explicit_blocking_conflict(
    backend: MockBackend, tmp_path: Path
) -> None:
    dbc = tmp_path / "PT.dbc"
    first = tmp_path / "a.yaml"
    second = tmp_path / "b.yml"
    dbc.write_text("PT", encoding="utf-8")
    first.write_text("a: 1", encoding="utf-8")
    second.write_text("b: 2", encoding="utf-8")
    session = backend.import_inputs(
        (dbc, first, second), lambda _u: None, CancellationToken()
    )
    inspection = backend.inspect_workspace(session, lambda _u: None, CancellationToken())
    assert not inspection.can_optimize
    assert inspection.errors and "多个项目配置" in inspection.errors[0]


def test_batch_runs_sequentially_and_writes_project_and_network_outputs(
    backend: MockBackend, batch_request: GuiBatchOptimizationRequest
) -> None:
    progress = []
    result = backend.optimize_all_networks(
        batch_request, progress.append, CancellationToken()
    )
    assert result.status is BatchRunStatus.SUCCEEDED
    assert result.succeeded_count == len(batch_request.inspection.networks)
    assert [item.network_name for item in result.network_results] == ["BD", "GL", "SU"]
    assert (result.output_directory / "summary.csv").is_file()
    assert (result.output_directory / "summary.json").is_file()
    for item in result.network_results:
        assert item.result is not None
        assert item.result.output_directory is not None
        assert {path.name for path in item.result.exported_files} == {
            "offsets.csv",
            "metrics.json",
            "load_curves.json",
            "run.log",
        }
    started = [
        update.network_name
        for update in progress
        if update.phase is ProgressPhase.NETWORK_RUNNING and update.attempt == 1
    ]
    assert started == ["BD", "GL", "SU"]
    assert progress[-1].phase is ProgressPhase.FINALIZING


def test_one_network_failure_and_skip_do_not_abort_remaining_networks(
    workspace_root: Path,
    inspection: WorkspaceInspection,
    batch_request: GuiBatchOptimizationRequest,
) -> None:
    backend = MockBackend(
        workspace_root=workspace_root,
        delay_seconds=0,
        fail_networks={"GL"},
        skip_networks={"BD"},
    )
    result = backend.optimize_all_networks(
        batch_request, lambda _u: None, CancellationToken()
    )
    assert result.status is BatchRunStatus.PARTIAL
    statuses = {item.network_name: item.status for item in result.network_results}
    assert statuses == {
        "BD": NetworkRunStatus.SKIPPED,
        "GL": NetworkRunStatus.FAILED,
        "SU": NetworkRunStatus.SUCCEEDED,
    }
    for item in result.network_results:
        suffix = item.network_id[-8:]
        directory = result.output_directory / f"{item.display_name}_{suffix}"
        if item.status is NetworkRunStatus.SUCCEEDED:
            assert (directory / "offsets.csv").is_file()
        else:
            assert (directory / "status.json").is_file()


def test_project_level_failure_is_not_silently_converted_to_results(
    workspace_root: Path, batch_request: GuiBatchOptimizationRequest
) -> None:
    backend = MockBackend(
        workspace_root=workspace_root, delay_seconds=0, fail_all_optimization=True
    )
    with pytest.raises(BackendError, match="工程级"):
        backend.optimize_all_networks(
            batch_request, lambda _u: None, CancellationToken()
        )


def test_cancellation_retains_completed_network_and_marks_remaining(
    workspace_root: Path, batch_request: GuiBatchOptimizationRequest
) -> None:
    slow_request = replace(
        batch_request,
        restart=RestartSettings(
            mode=RestartMode.FIXED,
            fixed_attempts=8,
            min_attempts=2,
            max_attempts=8,
        ),
    )
    backend = MockBackend(workspace_root=workspace_root, delay_seconds=0.005)
    token = CancellationToken()
    second_started = Event()
    failures: list[BaseException] = []

    def progress(update: object) -> None:
        if (
            getattr(update, "phase", None) is ProgressPhase.NETWORK_RUNNING
            and getattr(update, "network_index", None) == 2
            and getattr(update, "attempt", None) == 1
        ):
            second_started.set()

    def run() -> None:
        try:
            backend.optimize_all_networks(slow_request, progress, token)
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=run)
    thread.start()
    assert second_started.wait(timeout=2)
    token.cancel()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], BatchOptimizationCancelled)
    partial = failures[0].partial_result
    assert partial.cancelled
    assert [item.status for item in partial.network_results] == [
        NetworkRunStatus.SUCCEEDED,
        NetworkRunStatus.CANCELLED,
        NetworkRunStatus.SKIPPED,
    ]
    assert (partial.output_directory / "summary.json").is_file()
