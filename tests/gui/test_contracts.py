from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    GuiBatchOptimizationRequest,
    ImportRecord,
    ImportRecordStatus,
    InputKind,
    NetworkSummary,
    OptimizationCancelled,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    WeightMode,
    WorkspaceInspection,
)


def test_import_record_requires_absolute_origin_and_workspace_for_valid_record(
    tmp_path: Path,
) -> None:
    kwargs = dict(
        original_path=(tmp_path / "a.dbc").resolve(),
        workspace_relative_path=Path("dbc/a.dbc"),
        kind=InputKind.DBC,
        status=ImportRecordStatus.IMPORTED,
        size_bytes=1,
        sha256="0" * 64,
        imported_at="2026-07-17T00:00:00+00:00",
    )
    assert ImportRecord(**kwargs).workspace_relative_path == Path("dbc/a.dbc")
    with pytest.raises(ValueError, match="absolute"):
        ImportRecord(**(kwargs | {"original_path": Path("a.dbc")}))
    with pytest.raises(ValueError, match="workspace"):
        ImportRecord(**(kwargs | {"workspace_relative_path": None}))


def test_network_contract_supports_selectable_fd_and_fixed_classic_weight() -> None:
    kwargs = dict(
        network_id="net-pt",
        network_name="PT",
        display_name="PT",
        source_file="PT.dbc",
        source_workspace_path=Path("dbc/PT.dbc"),
        is_optimizable=True,
        message_count=1,
    )
    fd_network = NetworkSummary(
        **kwargs,
        available_weight_modes=(WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US),
    )
    assert fd_network.effective_weight_mode is WeightMode.FRAME_TIME_US
    classic = NetworkSummary(
        **(
            kwargs
            | {
                "network_id": "net-bd",
                "network_name": "BD",
                "display_name": "BD",
            }
        ),
        available_weight_modes=(WeightMode.PAYLOAD_BYTES,),
        frame_protocol=FrameProtocol.CLASSIC_CAN,
        automatic_weight_mode=WeightMode.PAYLOAD_BYTES,
        classic_weight_model=CLASSIC_WEIGHT_MODEL,
    )
    assert classic.effective_weight_mode is WeightMode.PAYLOAD_BYTES


def test_batch_request_rejects_weight_not_common_to_all_networks(
    inspection: WorkspaceInspection,
) -> None:
    payload_only = replace(
        inspection,
        networks=tuple(
            replace(network, available_weight_modes=(WeightMode.PAYLOAD_BYTES,))
            for network in inspection.networks
        ),
    )
    with pytest.raises(ValueError, match="every CAN FD network"):
        GuiBatchOptimizationRequest(
            inspection=payload_only,
            weight_mode=WeightMode.FRAME_TIME_US,
            mode=OptimizationMode.PEAK,
            balanced_tolerance=0.05,
            restart=RestartSettings(),
            candidate_pool_size=4,
            enable_triple_search=False,
            output_root=inspection.session.workspace_root / "user_output",
        )


def test_payload_weight_forces_peak_mode(inspection: WorkspaceInspection) -> None:
    with pytest.raises(ValueError, match="peak"):
        GuiBatchOptimizationRequest(
            inspection=inspection,
            weight_mode=WeightMode.PAYLOAD_BYTES,
            mode=OptimizationMode.BALANCED,
            balanced_tolerance=0.05,
            restart=RestartSettings(),
            candidate_pool_size=4,
            enable_triple_search=False,
            output_root=inspection.session.workspace_root / "user_output",
        )


def test_restart_settings_and_cancellation_are_explicit() -> None:
    with pytest.raises(ValueError, match="min_attempts"):
        RestartSettings(RestartMode.ADAPTIVE, min_attempts=81, max_attempts=80)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OptimizationCancelled):
        token.raise_if_cancelled()
