from __future__ import annotations

from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiOptimizationRequest,
    InputInspectionRequest,
    OptimizationCancelled,
    OptimizationMode,
    RestartMode,
    RestartSettings,
)


def test_request_validation_reports_missing_inputs(tmp_path: Path) -> None:
    inspection = InputInspectionRequest(
        tmp_path / "missing.dbc", tmp_path / "missing.yaml", tmp_path / "missing-arxml"
    )
    request = GuiOptimizationRequest(
        inspection,
        "PT_CAN",
        OptimizationMode.BALANCED,
        0.05,
        RestartSettings(),
        1,
        False,
        tmp_path / "output",
    )
    errors = request.validation_errors()
    assert len(errors) == 3
    assert any("DBC" in item for item in errors)
    assert any("配置" in item for item in errors)
    assert any("ARXML" in item for item in errors)


def test_restart_and_advanced_settings_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="restart mode"):
        RestartSettings("adaptive")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="min_attempts"):
        RestartSettings(RestartMode.ADAPTIVE, min_attempts=81, max_attempts=80)
    inspection = InputInspectionRequest(tmp_path / "a.dbc", tmp_path / "project.yaml")
    with pytest.raises(ValueError, match="candidate_pool_size"):
        GuiOptimizationRequest(
            inspection,
            "PT_CAN",
            OptimizationMode.PEAK,
            0.05,
            RestartSettings(),
            3,
            False,
            tmp_path / "out",
        )
    with pytest.raises(ValueError, match="optimization mode"):
        GuiOptimizationRequest(
            inspection,
            "PT_CAN",
            "balanced",  # type: ignore[arg-type]
            0.05,
            RestartSettings(),
            4,
            False,
            tmp_path / "out",
        )


def test_cancellation_token_is_thread_safe_and_explicit() -> None:
    token = CancellationToken()
    assert not token.is_cancelled
    token.cancel()
    assert token.is_cancelled
    with pytest.raises(OptimizationCancelled):
        token.raise_if_cancelled()
