from __future__ import annotations

import csv
import builtins
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from canfd_offset_optimizer.config import OffsetSearchConfig

import canfd_offset_optimizer.gui.real_backend as real_backend_module
from canfd_offset_optimizer.gui.app import create_backend
from canfd_offset_optimizer.gui.contracts import (
    BackendError,
    BatchOptimizationResult,
    CancellationToken,
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    GuiBatchOptimizationRequest,
    GuiOptimizationResult,
    NetworkBatchResult,
    NetworkRunStatus,
    ObjectiveMetrics,
    OffsetAssignmentRow,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    WeightMode,
)
from canfd_offset_optimizer.gui.mock_backend import MockBackend
from canfd_offset_optimizer.gui.fixture_backend import FixtureBackend
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.real_backend import REQUIRED_ALLOWED_OFFSETS_US, RealBackend
from canfd_offset_optimizer.parsers.dbc_parser import parse_dbc
from canfd_offset_optimizer.parsers.project_loader import load_project


CSV_FIXTURE = Path("tests/fixtures/ALL_offsets_weight_mode_comparison.csv")
DBC_FIXTURE = Path("tests/fixtures/dbc/minimal.dbc")


def _csv_rows() -> list[dict[str, str]]:
    with CSV_FIXTURE.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_regression_dbc(path: Path, rows: list[dict[str, str]]) -> None:
    definitions = [
        'VERSION "GUI regression fixture"',
        "NS_ :",
        "    BA_DEF_",
        "    BA_",
        "    BA_DEF_DEF_",
        "BS_:",
        "BU_: VCU",
        "",
    ]
    attributes = [
        'BA_DEF_ BO_ "GenMsgCycleTime" INT 0 10000;',
        'BA_DEF_ BO_ "GenMsgStartDelayTime" INT 0 10000;',
        'BA_DEF_ BO_ "GenMsgSendType" STRING;',
        'BA_DEF_ BO_ "VFrameFormat" STRING;',
        'BA_DEF_DEF_ "GenMsgCycleTime" 0;',
        'BA_DEF_DEF_ "GenMsgStartDelayTime" 0;',
        'BA_DEF_DEF_ "GenMsgSendType" "Event";',
        'BA_DEF_DEF_ "VFrameFormat" "StandardCAN_FD";',
    ]
    for index, row in enumerate(rows):
        frame_id = int(row["CAN_ID"], 16)
        definitions.extend(
            (
                f'BO_ {frame_id} {row["报文名称"]}: {row["载荷长度(Byte)"]} VCU',
                f" SG_ Value_{index} : 0|8@1+ (1,0) [0|255] \"\" Vector__XXX",
                "",
            )
        )
        attributes.extend(
            (
                f'BA_ "GenMsgCycleTime" BO_ {frame_id} {row["周期(ms)"]};',
                f'BA_ "GenMsgStartDelayTime" BO_ {frame_id} {row["DBC原始Offset(ms)"]};',
                f'BA_ "GenMsgSendType" BO_ {frame_id} "Cyclic";',
                f'BA_ "VFrameFormat" BO_ {frame_id} "StandardCAN_FD";',
            )
        )
    path.write_text("\n".join((*definitions, *attributes, "")), encoding="utf-8")


def _write_current_project_regression_fixture(root: Path) -> None:
    root.mkdir()
    rows = _csv_rows()
    for network in sorted({row["网段"] for row in rows}):
        _write_regression_dbc(
            root / f"CAR_VCU_{network} Message.dbc",
            [row for row in rows if row["网段"] == network],
        )
    base = DBC_FIXTURE.read_text(encoding="utf-8")
    classic = base.replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    ).replace(
        "BO_ 2147484768 Msg460Ext: 16 VCU",
        "BO_ 2147484768 Msg460Ext: 16 Vector__XXX",
    )
    (root / "CAR_VCU_BD Message.dbc").write_text(classic, encoding="utf-8")
    (root / "CAR_VCU_DM Message.dbc").write_text(classic, encoding="utf-8")
    no_tx = base.replace("BO_ 913 Msg391: 8 VCU", "BO_ 913 Msg391: 8 Vector__XXX")
    no_tx = no_tx.replace(
        "BO_ 2147484768 Msg460Ext: 16 VCU",
        "BO_ 2147484768 Msg460Ext: 16 Vector__XXX",
    )
    (root / "CAR_VCU_DG Message.dbc").write_text(no_tx, encoding="utf-8")
    (root / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )


def _write_multichannel_arxml(path: Path, channel_names: tuple[str, ...]) -> None:
    controllers = "".join(
        f"""
<ECUC-CONTAINER-VALUE><SHORT-NAME>{channel}</SHORT-NAME>
<DEFINITION-REF>/Can/CanController</DEFINITION-REF><PARAMETER-VALUES>
<P><DEFINITION-REF>/Can/CanControllerBaudRate</DEFINITION-REF><VALUE>500</VALUE></P>
<P><DEFINITION-REF>/Can/CanControllerFdBaudRate</DEFINITION-REF><VALUE>2000</VALUE></P>
<P><DEFINITION-REF>/Can/CanControllerTxBitRateSwitch</DEFINITION-REF><VALUE>true</VALUE></P>
</PARAMETER-VALUES></ECUC-CONTAINER-VALUE>
"""
        for channel in channel_names
    )
    path.write_text(
        "<?xml version=\"1.0\"?>\n"
        "<AUTOSAR xmlns=\"urn:test\"><AR-PACKAGES><AR-PACKAGE>"
        "<SHORT-NAME>Pkg</SHORT-NAME><ELEMENTS>"
        f"{controllers}</ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>",
        encoding="utf-8",
    )


def test_regression_csv_has_expected_network_counts_and_132_rows() -> None:
    rows = _csv_rows()
    assert len(rows) == 132
    assert Counter(row["网段"] for row in rows) == {
        "CH": 9,
        "DA": 17,
        "DK": 25,
        "EP": 6,
        "GL": 25,
        "IC": 24,
        "LC": 8,
        "PT": 11,
        "SU": 7,
    }


def test_all_regression_offset_columns_are_in_canonical_domain() -> None:
    columns = (
        "DBC原始Offset(ms)",
        "payload_bytes_GCLS_Offset(ms)",
        "frame_time_us_peak_GCLS_Offset(ms)",
        "frame_time_us_balanced_GCLS_Offset(ms)",
        "frame_time_us_variance_GCLS_Offset(ms)",
    )
    for row in _csv_rows():
        assert all(int(row[column]) * 1_000 in REQUIRED_ALLOWED_OFFSETS_US for column in columns)


def test_current_project_fixture_adds_classic_bd_dm_and_skips_empty_dg(
    tmp_path: Path,
) -> None:
    source = tmp_path / "current_project"
    _write_current_project_regression_fixture(source)
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda update: None, token)
    inspection = backend.inspect_workspace(session, lambda update: None, token)

    assert len(inspection.networks) == 12
    assert {item.network_name for item in inspection.optimizable_networks} == {
        "BD", "CH", "DA", "DK", "DM", "EP", "GL", "IC", "LC", "PT", "SU"
    }
    assert sum(item.message_count for item in inspection.optimizable_networks) == 134
    classic = {
        item.network_name: item
        for item in inspection.optimizable_networks
        if item.network_name in {"BD", "DM"}
    }
    assert all(item.frame_protocol.value == "classic_can" for item in classic.values())
    assert all(
        item.available_weight_modes == (WeightMode.PAYLOAD_BYTES,)
        for item in classic.values()
    )
    skipped = {item.network_name: item for item in inspection.networks if not item.is_optimizable}
    assert set(skipped) == {"DG"}
    assert "没有符合资格的周期 TX" in skipped["DG"].unoptimizable_reason


def test_real_backend_maps_each_dbc_to_its_unique_arxml_controller(
    tmp_path: Path,
) -> None:
    source = tmp_path / "multi_channel_project"
    source.mkdir()
    # Msg460Ext intentionally inherits BA_DEF_DEF_ Offset=0. The backend must
    # accept that effective baseline and materialize an explicit value only in
    # the generated DBC copy.
    dbc_text = DBC_FIXTURE.read_text(encoding="utf-8")
    (source / "CAR_VCU_DA Message list.dbc").write_text(dbc_text, encoding="utf-8")
    (source / "CAR_VCU_SU Message list.dbc").write_text(dbc_text, encoding="utf-8")
    (source / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )
    channel_names = (
        "CT_CAR_VCU_DAMessagelis_da123456",
        "CT_CAR_VCU_SUMessagelis_su123456",
    )
    _write_multichannel_arxml(source / "controllers.arxml", channel_names)
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda update: None, token)
    inspection = backend.inspect_workspace(session, lambda update: None, token)

    assert inspection.errors == ()
    assert len(inspection.optimizable_networks) == 2
    assert all(
        network.available_weight_modes
        == (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US)
        for network in inspection.optimizable_networks
    )
    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.FRAME_TIME_US,
        mode=OptimizationMode.BALANCED,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=tmp_path / "user_output",
    )
    batch = backend.optimize_all_networks(request, lambda update: None, token)

    assert batch.succeeded_count == 2
    selected_channels = {
        log.removeprefix("arxml_channel=")
        for item in batch.network_results
        if item.result is not None
        for log in item.result.logs
        if log.startswith("arxml_channel=")
    }
    assert selected_channels == set(channel_names)
    for item in batch.network_results:
        assert item.result is not None
        assert "dbc_offset_replaced_count=1" in item.result.logs
        assert "dbc_offset_inserted_count=1" in item.result.logs
        output_dbc = next(
            path for path in item.result.exported_files if path.suffix.lower() == ".dbc"
        )
        assert (
            'BA_ "GenMsgStartDelayTime" BO_ 2147484768 '
            in output_dbc.read_text(encoding="utf-8")
        )
        assert parse_dbc(output_dbc).messages[1].original_offset_us in {
            row.optimized_offset_us for row in item.result.assignments
            if row.message_name == "Msg460Ext"
        }
    assert all(
        path.read_text(encoding="utf-8") == dbc_text
        for path in source.glob("*.dbc")
    )


def test_classic_backend_uses_payload_and_exports_no_fake_physical_claim(
    tmp_path: Path,
) -> None:
    source = tmp_path / "classic_project"
    source.mkdir()
    classic = DBC_FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    ).replace(
        "BO_ 2147484768 Msg460Ext: 16 VCU",
        "BO_ 2147484768 Msg460Ext: 16 Vector__XXX",
    )
    (source / "CAR_VCU_BD Message.dbc").write_text(classic, encoding="utf-8")
    (source / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda update: None, token)
    inspection = backend.inspect_workspace(session, lambda update: None, token)

    assert len(inspection.optimizable_networks) == 1
    network = inspection.optimizable_networks[0]
    assert network.frame_protocol is FrameProtocol.CLASSIC_CAN
    assert network.available_weight_modes == (WeightMode.PAYLOAD_BYTES,)
    assert network.classic_weight_model == CLASSIC_WEIGHT_MODEL

    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        # This selector applies to FD only; Classic must stay on payload.
        can_fd_weight=WeightMode.FRAME_TIME_US,
        mode=OptimizationMode.BALANCED,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=tmp_path / "user_output",
    )
    batch = backend.optimize_all_networks(request, lambda update: None, token)
    result = batch.network_results[0].result
    assert result is not None
    assert result.weight_mode is WeightMode.PAYLOAD_BYTES
    assert result.mode is OptimizationMode.BALANCED
    assert result.frame_protocol is FrameProtocol.CLASSIC_CAN
    assert result.classic_weight_model == CLASSIC_WEIGHT_MODEL
    assert result.original_metrics.nvio is None
    assert result.original_metrics.vvio is None
    assert all(value % 8 == 0 for value in result.original_steady_load)
    log = (batch.output_directory / "logs" / "BD.log").read_text(encoding="utf-8")
    assert 'classic_weight_model = "payload_bytes_approximation"' in log
    assert "bus_type=classic_can" in log
    assert "weight_mode=payload_bytes" in log
    assert "objective_mode=balanced" in log
    assert "load_unit=Byte/slot" in log
    assert "75%" not in log


def test_arxml_channel_resolution_fails_closed_on_ambiguous_source_match() -> None:
    channels = (
        "CT_CAR_VCU_DAMessagelis_first",
        "CT_CAR_VCU_DAMessagelis_second",
    )
    assert (
        RealBackend._resolve_frame_time_channel(
            "CAR_VCU_DA Message list.dbc", "CAN1", channels
        )
        is None
    )
    assert (
        RealBackend._resolve_frame_time_channel(
            "CAR_VCU_DA Message list.dbc", channels[1], channels
        )
        == channels[1]
    )


@pytest.mark.parametrize(
    ("name", "can_id", "cycle", "original", "balanced"),
    (
        ("FLZCU_3", "0x460", "100", "70", "35"),
        ("FLZCU_8", "0x413", "100", "45", "100"),
        ("FLZCU_58", "0x205", "20", "30", "85"),
        ("DCM_ICC_1", "0x2FA", "20", "20", "100"),
    ),
)
def test_ic_regression_records_are_exact(
    name: str, can_id: str, cycle: str, original: str, balanced: str
) -> None:
    rows = _csv_rows()
    row = next(item for item in rows if item["网段"] == "IC" and item["报文名称"] == name)
    assert row["CAN_ID"] == can_id
    assert row["周期(ms)"] == cycle
    assert row["DBC原始Offset(ms)"] == original
    assert row["frame_time_us_balanced_GCLS_Offset(ms)"] == balanced


def test_regression_contains_no_fabricated_ic_message_names() -> None:
    ic_names = {row["报文名称"] for row in _csv_rows() if row["网段"] == "IC"}
    assert not any(name.startswith("IC_Message_") for name in ic_names)


def test_real_adapter_offset_domain_is_exact_and_not_rounded() -> None:
    search = OffsetSearchConfig(15, 102, 10)
    assert REQUIRED_ALLOWED_OFFSETS_US == OffsetSearchConfig().candidate_offsets_us
    assert search.candidate_offsets_us == tuple(range(15_000, 96_000, 10_000))
    with pytest.raises(ValueError, match=r"MsgBad.*17 ms.*no rounding"):
        RealBackend._validate_offset_contract(
            "MsgBad", 17_000, "core fixture", search.candidate_offsets_us
        )


def test_original_offset_outside_candidates_is_preserved_in_baseline() -> None:
    fixtures = Path("tests/fixtures")
    loaded = load_project(
        fixtures / "dbc" / "four_messages.dbc",
        fixtures / "arxml",
        fixtures / "config" / "project.yaml",
        offset_search_override=OffsetSearchConfig(15, 25, 10),
    )
    messages = tuple(
        replace(message, original_offset_us=20_000)
        for message in loaded.network.messages
    )
    loaded = replace(loaded, network=replace(loaded.network, messages=messages))
    baseline = RealBackend._baseline_state(loaded)
    assert set(baseline.current_offsets.values()) == {20_000}

def test_real_inspection_uses_core_eligibility_and_keeps_skipped_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    base = DBC_FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "GenMsgCycleTime" BO_ 2147484768 100;',
        'BA_ "GenMsgCycleTime" BO_ 2147484768 100;\n'
        'BA_ "GenMsgStartDelayTime" BO_ 2147484768 20;',
    )
    (source / "CAR_VCU_OK Message.dbc").write_text(base, encoding="utf-8")
    (source / "CAR_VCU_CLASSIC Message.dbc").write_text(
        base.replace('BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
                     'BA_ "VFrameFormat" BO_ 913 "StandardCAN";'),
        encoding="utf-8",
    )
    no_tx = base.replace("BO_ 913 Msg391: 8 VCU", "BO_ 913 Msg391: 8 Vector__XXX")
    no_tx = no_tx.replace("BO_ 2147484768 Msg460Ext: 16 VCU",
                          "BO_ 2147484768 Msg460Ext: 16 Vector__XXX")
    (source / "CAR_VCU_EMPTY Message.dbc").write_text(no_tx, encoding="utf-8")
    (source / "project.yaml").write_text("network:\n  channel: CAN1\n", encoding="utf-8")

    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda update: None, token)
    inspection = backend.inspect_workspace(session, lambda update: None, token)

    assert len(inspection.networks) == 3
    assert len(inspection.optimizable_networks) == 1
    skipped = {item.network_name: item for item in inspection.networks if not item.is_optimizable}
    assert "混合了 Classic CAN 与 CAN FD" in skipped["CLASSIC"].unoptimizable_reason
    assert "没有符合资格的周期 TX" in skipped["EMPTY"].unoptimizable_reason
    assert all(item.message_count == 0 for item in skipped.values())

    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.BALANCED,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=tmp_path / "user_output",
    )
    batch = backend.optimize_all_networks(request, lambda update: None, token)
    assert batch.succeeded_count == 1
    assert batch.skipped_count == 2
    succeeded = next(
        item for item in batch.network_results if item.status is NetworkRunStatus.SUCCEEDED
    )
    assert succeeded.mode is OptimizationMode.BALANCED
    assert all(
        item.result is None
        for item in batch.network_results
        if item.status is NetworkRunStatus.SKIPPED
    )
    assert not (batch.output_directory / "CLASSIC").exists()
    assert not (batch.output_directory / "EMPTY").exists()


def test_real_import_uses_bundled_default_when_project_yaml_is_missing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source_without_config"
    source.mkdir()
    (source / "CAR_VCU_PT Message.dbc").write_bytes(DBC_FIXTURE.read_bytes())
    backend = RealBackend(workspace_root=tmp_path / "workspace")

    session = backend.import_inputs(
        (source,), lambda update: None, CancellationToken()
    )
    config_record = next(
        record for record in session.records if record.kind.value == "config"
    )
    copied = session.session_directory / "config" / "project.yaml"
    expected = Path("input/config/project.yaml")
    assert copied.read_text(encoding="utf-8") == expected.read_text(encoding="utf-8")
    assert "内置默认 project.yaml" in config_record.note

    inspection = backend.inspect_workspace(
        session, lambda update: None, CancellationToken()
    )
    assert inspection.missing_required == ()
    assert inspection.can_optimize
    assert any("内置默认 project.yaml" in warning for warning in inspection.warnings)


def test_default_mock_backend_fails_closed_and_writes_no_output(tmp_path: Path) -> None:
    backend = MockBackend(workspace_root=tmp_path)
    assert not backend.availability.can_optimize
    with pytest.raises(BackendError, match="不生成业务结果"):
        backend.optimize_all_networks(
            cast(Any, None), lambda update: None, CancellationToken()
        )
    assert not (tmp_path / "user_output").exists()


def test_real_backend_short_run_maps_only_core_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    dbc_text = DBC_FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "GenMsgCycleTime" BO_ 2147484768 100;',
        'BA_ "GenMsgCycleTime" BO_ 2147484768 100;\n'
        'BA_ "GenMsgStartDelayTime" BO_ 2147484768 20;',
    )
    (source / "CAR_VCU_PT Message.dbc").write_text(dbc_text, encoding="utf-8")
    (source / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    captured: dict[str, Any] = {}
    core_run_gcls = real_backend_module.run_gcls

    def capture_core_result(*args: Any, **kwargs: Any) -> Any:
        result = core_run_gcls(*args, **kwargs)
        captured["result"] = result
        return result

    monkeypatch.setattr(real_backend_module, "run_gcls", capture_core_result)
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda update: None, token)
    inspection = backend.inspect_workspace(session, lambda update: None, token)
    request = GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.PEAK,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=tmp_path / "user_output",
    )
    progress: list[Any] = []
    batch = backend.optimize_all_networks(request, progress.append, token)
    item = batch.network_results[0]
    assert item.status is NetworkRunStatus.SUCCEEDED
    assert item.result is not None
    assert {row.message_name for row in item.result.assignments} == {"Msg391", "Msg460Ext"}
    assert all(
        row.optimized_offset_us in REQUIRED_ALLOWED_OFFSETS_US
        for row in item.result.assignments
    )
    assert item.result.assignments[0].original_offset_us == 15_000
    assert item.result.logs[0] == "数据源：core load_project + run_gcls"
    core_result = captured["result"]
    assert item.result.optimized_metrics.zss == core_result.objective.steady_peak
    assert item.result.optimized_metrics.qss == core_result.objective.sum_square_load
    assert item.result.steady_loads_after == core_result.steady_slot_loads
    assert item.result.startup_loads_after == core_result.startup_slot_loads
    assert item.result.steady_counts_after == core_result.steady_slot_counts
    assert item.result.startup_counts_after == core_result.startup_slot_counts
    assert {row.message_name: row.optimized_offset_us for row in item.result.assignments} == {
        row.message_name: row.offset_us for row in core_result.assignments
    }
    assert item.result.actual_attempts == core_result.restart_execution.actual_attempts
    output_dbc = batch.output_directory / "dbc" / "CAR_VCU_PT Message.dbc"
    assert output_dbc.is_file()
    assert (batch.output_directory / "plots" / "PT_load_curve.png").is_file()
    assert (batch.output_directory / "plots" / "PT_heatmap.png").is_file()
    assert (batch.output_directory / "results" / "networks_summary.csv").is_file()
    assert (batch.output_directory / "logs" / "PT.log").is_file()
    assert (batch.output_directory / "logs" / "batch.log").is_file()
    assert any("正在生成负载图、热力图和 DBC 副本" in update.message for update in progress)
    assert (source / "CAR_VCU_PT Message.dbc").read_text(encoding="utf-8") == dbc_text
    exported_text = output_dbc.read_text(encoding="utf-8")
    for row in item.result.assignments:
        raw_id = row.can_id
        if raw_id == 0x460:
            raw_id |= 0x80000000
        assert (
            f'BA_ "GenMsgStartDelayTime" BO_ {raw_id} '
            f'{row.optimized_offset_us // 1_000};'
        ) in exported_text


def test_app_composition_mentions_real_backend_and_no_mock_fallback() -> None:
    source = Path("src/canfd_offset_optimizer/gui/app.py").read_text(encoding="utf-8")
    assert "RealBackend(workspace_root=root)" in source
    assert "MockBackend" not in source
    assert "UnavailableBackend" in source
    backend = create_backend()
    assert isinstance(backend, RealBackend)
    assert backend.availability.can_optimize


def test_real_backend_import_failure_uses_unavailable_gate_not_mock(
    monkeypatch: pytest.MonkeyPatch, qtbot: Any
) -> None:
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.endswith("real_backend"):
            raise ImportError("missing real adapter interface")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    backend = create_backend()
    assert not backend.availability.can_optimize
    assert not isinstance(backend, MockBackend)
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    assert not window.progress_panel.run_button.isEnabled()
    assert "仅预览 / 优化不可用" in window.backend_status_label.text()
    window.start_optimization()
    assert not window.task_active
    assert "优化不可用" in window.log_view.toPlainText()


def test_ic_and_su_selection_bind_fixed_assignments_curves_and_titles(
    tmp_path: Path, qtbot: Any
) -> None:
    def result_for(network: str, before: tuple[int, ...], after: tuple[int, ...]) -> GuiOptimizationResult:
        rows = [row for row in _csv_rows() if row["网段"] == network]
        assignments = tuple(
            OffsetAssignmentRow(
                row["报文名称"],
                int(row["CAN_ID"], 16),
                int(row["周期(ms)"]) * 1_000,
                int(row["DBC原始Offset(ms)"]) * 1_000,
                int(row["frame_time_us_balanced_GCLS_Offset(ms)"]) * 1_000,
            )
            for row in rows
        )
        return GuiOptimizationResult(
            network_id=f"fixture-{network.lower()}",
            network_name=network,
            display_name=network,
            source_file=f"{network}.dbc",
            weight_mode=WeightMode.FRAME_TIME_US,
            mode=OptimizationMode.BALANCED,
            original_metrics=ObjectiveMetrics(10, 100, 2.0, 12, 120, 0, 0),
            optimized_metrics=ObjectiveMetrics(8, 80, 1.0, 10, 100, 0, 0),
            assignments=assignments,
            actual_attempts=1,
            stop_reason="fixture_complete",
            elapsed_seconds=0.0,
            warnings=("fixture",),
            steady_loads_before=before,
            steady_loads_after=after,
            startup_loads_before=tuple(value + 1 for value in before),
            startup_loads_after=tuple(value + 1 for value in after),
            steady_counts_before=tuple(1 for _ in before),
            steady_counts_after=tuple(1 for _ in after),
            startup_counts_before=tuple(1 for _ in before),
            startup_counts_after=tuple(1 for _ in after),
        )

    ic = result_for("IC", (9, 4, 7), (5, 4, 3))
    su = result_for("SU", (2, 8, 6, 4), (3, 4, 4, 3))
    items = tuple(
        NetworkBatchResult(
            result.network_id,
            result.network_name,
            result.display_name,
            result.source_file,
            NetworkRunStatus.SUCCEEDED,
            result.weight_mode,
            result.mode,
            result=result,
        )
        for result in (ic, su)
    )
    batch = BatchOptimizationResult(
        "fixed-selection-fixture",
        tmp_path,
        tmp_path / "manifest.json",
        tmp_path / "output",
        items,
        0.0,
    )
    window = MainWindow(
        FixtureBackend(workspace_root=tmp_path, delay_seconds=0),
        dialog_handler=lambda *_args: None,
    )
    qtbot.addWidget(window)
    window._apply_batch_result(batch)

    assert window.summary_panel.select_network_id(ic.network_id)
    qtbot.waitUntil(lambda: window.selected_network_id == ic.network_id)
    assert window.assignment_table.model.index(0, 0).data() == "FLZCU_3"
    assert window.load_chart.canvas.before_series == ic.original_steady_load * 4
    assert window.load_chart.canvas.before_series is not ic.original_steady_load
    assert (
        "IC / 可优化报文稳态负载，500 ms 超周期重复展示 4 次 / IC.dbc"
        == window.load_chart.chart_title_label.text()
    )

    assert window.summary_panel.select_network_id(su.network_id)
    qtbot.waitUntil(lambda: window.selected_network_id == su.network_id)
    assert window.assignment_table.model.index(0, 0).data().startswith("FLZCU")
    assert window.load_chart.canvas.before_series == su.original_steady_load * 4
    assert window.load_chart.canvas.before_series is not su.original_steady_load
    assert window.load_chart.canvas.before_series is not ic.original_steady_load
    assert (
        "SU / 可优化报文稳态负载，500 ms 超周期重复展示 4 次 / SU.dbc"
        == window.load_chart.chart_title_label.text()
    )


def test_production_source_does_not_read_regression_csv_or_hardcode_network_set() -> None:
    # Reporting is allowed to *write* a comparison artifact with this historic
    # filename.  The production GUI adapter must never read the test fixture.
    source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/canfd_offset_optimizer/gui/app.py",
            "src/canfd_offset_optimizer/gui/real_backend.py",
            "src/canfd_offset_optimizer/gui/workspace_io.py",
        )
    )
    assert "ALL_offsets_weight_mode_comparison.csv" not in source
    assert '"CH", "DA", "DK", "EP", "GL", "IC", "LC", "PT", "SU"' not in source
