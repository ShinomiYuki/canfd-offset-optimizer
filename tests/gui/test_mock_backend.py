from __future__ import annotations

from pathlib import Path
from threading import Thread
from time import sleep

import pytest

from canfd_offset_optimizer.gui.contracts import (
    BackendError,
    CancellationToken,
    GuiOptimizationRequest,
    InputInspectionRequest,
    OptimizationCancelled,
    OptimizationMode,
    RestartSettings,
)
from canfd_offset_optimizer.gui.mock_backend import MockBackend


def _inputs(tmp_path: Path) -> InputInspectionRequest:
    dbc = tmp_path / "network.dbc"
    config = tmp_path / "project.yaml"
    arxml = tmp_path / "arxml"
    dbc.write_text("mock", encoding="utf-8")
    config.write_text("mock", encoding="utf-8")
    arxml.mkdir()
    return InputInspectionRequest(dbc, config, arxml)


def _request(tmp_path: Path) -> GuiOptimizationRequest:
    return GuiOptimizationRequest(
        _inputs(tmp_path),
        "PT_CAN",
        OptimizationMode.BALANCED,
        0.05,
        RestartSettings(),
        4,
        False,
        tmp_path / "user-output",
    )


def test_mock_backend_inspects_multiple_networks_and_emits_progress(tmp_path: Path) -> None:
    progress = []
    summary = MockBackend(delay_seconds=0).inspect_input(
        _inputs(tmp_path), progress.append, CancellationToken()
    )
    assert [item.name for item in summary.networks] == ["PT_CAN", "BODY_CAN", "ADAS_CAN"]
    assert len(progress) == 3
    assert summary.warnings


def test_mock_backend_returns_complete_immutable_result_without_writing(tmp_path: Path) -> None:
    request = _request(tmp_path)
    progress = []
    result = MockBackend(delay_seconds=0).optimize(
        request, progress.append, CancellationToken()
    )
    assert result.network_name == "PT_CAN"
    assert result.actual_attempts == request.restart.min_attempts
    assert result.optimized_metrics.qss < result.original_metrics.qss
    assert len(result.assignments) == 12
    assert len(result.steady_loads_before) == len(result.steady_loads_after)
    assert not request.output_directory.exists()
    assert any(item.phase.value == "balanced_search" for item in progress)


def test_mock_backend_can_fail_without_swallowing_error(tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="模拟优化失败"):
        MockBackend(fail_optimization=True).optimize(
            _request(tmp_path), lambda _update: None, CancellationToken()
        )


def test_mock_backend_honors_cooperative_cancellation(tmp_path: Path) -> None:
    token = CancellationToken()
    error: list[BaseException] = []

    def run() -> None:
        try:
            MockBackend(delay_seconds=0.02).optimize(
                _request(tmp_path), lambda _update: None, token
            )
        except BaseException as exc:  # test thread must preserve the observed exception
            error.append(exc)

    thread = Thread(target=run)
    thread.start()
    sleep(0.05)
    token.cancel()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(error) == 1
    assert isinstance(error[0], OptimizationCancelled)
