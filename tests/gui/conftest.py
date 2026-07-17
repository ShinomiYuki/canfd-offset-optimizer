"""Shared GUI test configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiOptimizationRequest,
    GuiOptimizationResult,
    InputInspectionRequest,
    OptimizationMode,
    RestartSettings,
)
from canfd_offset_optimizer.gui.mock_backend import MockBackend

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def gui_inputs(tmp_path: Path) -> InputInspectionRequest:
    dbc = tmp_path / "network.dbc"
    config = tmp_path / "project.yaml"
    arxml = tmp_path / "arxml"
    dbc.write_text("mock", encoding="utf-8")
    config.write_text("mock", encoding="utf-8")
    arxml.mkdir()
    return InputInspectionRequest(dbc, config, arxml)


@pytest.fixture
def gui_request(tmp_path: Path, gui_inputs: InputInspectionRequest) -> GuiOptimizationRequest:
    return GuiOptimizationRequest(
        gui_inputs,
        "PT_CAN",
        OptimizationMode.BALANCED,
        0.05,
        RestartSettings(),
        4,
        False,
        tmp_path / "user-output",
    )


@pytest.fixture
def gui_result(gui_request: GuiOptimizationRequest) -> GuiOptimizationResult:
    return MockBackend(delay_seconds=0).optimize(
        gui_request, lambda _update: None, CancellationToken()
    )
