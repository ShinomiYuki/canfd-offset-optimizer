"""Shared fixtures for the workspace-oriented GUI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    ImportSession,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def source_project(tmp_path: Path) -> Path:
    root = tmp_path / "original_project"
    (root / "networks" / "nested").mkdir(parents=True)
    (root / "timing").mkdir()
    (root / "project.yaml").write_text("project: demo\n", encoding="utf-8")
    (root / "networks" / "E0X_PT_Car FLZCU_VCU_BD Message list V1.2.dbc").write_text(
        "VERSION BD\n", encoding="utf-8"
    )
    (root / "networks" / "nested" / "E0X_PT_Car FLZCU_VCU_GL Message list V1.2.dbc").write_text(
        "VERSION GL\n", encoding="utf-8"
    )
    (root / "networks" / "nested" / "E0X_PT_Car FLZCU_VCU_SU Message list V1.2.dbc").write_text(
        "VERSION SU\n", encoding="utf-8"
    )
    (root / "timing" / "vehicle.arxml").write_text("<AUTOSAR/>\n", encoding="utf-8")
    (root / "README.txt").write_text("keep me\n", encoding="utf-8")
    return root


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "application_workspace"


@pytest.fixture
def backend(workspace_root: Path) -> FixtureBackend:
    return FixtureBackend(workspace_root=workspace_root, delay_seconds=0)


@pytest.fixture
def import_session(backend: FixtureBackend, source_project: Path) -> ImportSession:
    return backend.import_inputs(
        (source_project,), lambda _update: None, CancellationToken()
    )


@pytest.fixture
def inspection(backend: FixtureBackend, import_session: ImportSession) -> WorkspaceInspection:
    return backend.inspect_workspace(
        import_session, lambda _update: None, CancellationToken()
    )


@pytest.fixture
def batch_request(inspection: WorkspaceInspection) -> GuiBatchOptimizationRequest:
    return GuiBatchOptimizationRequest(
        inspection=inspection,
        weight_mode=WeightMode.FRAME_TIME_US,
        mode=OptimizationMode.BALANCED,
        balanced_tolerance=0.05,
        restart=RestartSettings(
            mode=RestartMode.FIXED,
            fixed_attempts=2,
            min_attempts=2,
            max_attempts=4,
        ),
        candidate_pool_size=4,
        enable_triple_search=False,
        output_root=inspection.session.workspace_root / "user_output",
    )


@pytest.fixture
def batch_result(
    backend: FixtureBackend, batch_request: GuiBatchOptimizationRequest
) -> BatchOptimizationResult:
    return backend.optimize_all_networks(
        batch_request, lambda _update: None, CancellationToken()
    )
