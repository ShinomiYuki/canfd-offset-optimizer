from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import canfd_offset_optimizer.gui.real_backend as real_backend_module
from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiBatchOptimizationRequest,
    InputKind,
    NetworkRunStatus,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    RouteExclusionStatus,
    RouteMatchStatus,
    RouteRecordIssue,
    WeightMode,
)
from canfd_offset_optimizer.gui.real_backend import RealBackend
from canfd_offset_optimizer.gui.routing_exclusion import (
    RouteMessageTableParser,
    RouteTableParseError,
    match_route_messages,
    parse_can_id,
)
from canfd_offset_optimizer.gui.widgets.input_panel import InputPanel


def _xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    workbook_sheets = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheets, start=1)
    )
    relationships = "".join(
        '<Relationship '
        f'Id="rId{index}" Target="worksheets/sheet{index}.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet"/>'
        for index in range(1, len(sheets) + 1)
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{workbook_sheets}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>",
        )
        for sheet_index, rows in enumerate(sheets.values(), start=1):
            row_xml: list[str] = []
            for row_index, row in enumerate(rows, start=1):
                cells: list[str] = []
                for column_index, value in enumerate(row):
                    column = chr(ord("A") + column_index)
                    if isinstance(value, (int, float)):
                        cells.append(
                            f'<c r="{column}{row_index}"><v>{value}</v></c>'
                        )
                    else:
                        cells.append(
                            f'<c r="{column}{row_index}" t="inlineStr"><is><t>'
                            f"{value}</t></is></c>"
                        )
                row_xml.append(
                    f'<row r="{row_index}">{"".join(cells)}</row>'
                )
            archive.writestr(
                f"xl/worksheets/sheet{sheet_index}.xml",
                '<?xml version="1.0"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
            )
    return path


def test_can_id_normalization_accepts_required_forms() -> None:
    assert parse_can_id("0x123") == 291
    assert parse_can_id("0X123") == 291
    assert parse_can_id("123h") == 291
    assert parse_can_id("291") == 291
    assert parse_can_id("291.0") == 291
    assert parse_can_id("") is None
    assert parse_can_id("not-an-id") is None
    assert parse_can_id("0x20000000") is None


def test_xlsx_parser_recognizes_explicit_chinese_and_english_aliases(
    tmp_path: Path,
) -> None:
    path = _xlsx(
        tmp_path / "routes.xlsx",
        {
            "中文": [["目标网段", "CAN ID", "报文名称"], ["IC", "0x460", "FLZCU_3"]],
            "English": [["target_network", "message_id", "message_name"], ["PT", 291, "PT_1"]],
        },
    )
    records = RouteMessageTableParser().parse(path)

    assert [(row.target_network_raw, row.can_id, row.message_name) for row in records] == [
        ("IC", 0x460, "FLZCU_3"),
        ("PT", 291, "PT_1"),
    ]
    assert records[0].source_file == "routes.xlsx"
    assert records[0].sheet_name == "中文"
    assert records[0].row_number == 2


def _company_routing_sheet(*data_rows: list[object]) -> list[list[object]]:
    return [
        [
            "Signal Name",
            "Routing Type",
            "Service Provider",
            "",
            "",
            "Service Subscriber Data",
            "",
            "",
            "Service Subscriber Subnet",
            "",
            "",
            "项目",
        ],
        ["", "", "服务提供者", "", "", "服务订阅数据", "", "", "网络服务订阅者网段"],
        [
            "",
            "",
            "Subnet",
            "Msg Name",
            "Msg ID",
            "Msg Name",
            "Msg FDF",
            "Msg ID",
            "FL_CANFD_IC",
            "FL_CAN_BD",
            "FL_LIN_RLHS",
            "项目",
        ],
        ["说明", "说明", "说明", "说明", "说明", "目标报文名称", "", "目标报文 ID"],
        *data_rows,
    ]


def _direct_routing_sheet(*data_rows: list[object]) -> list[list[object]]:
    return [
        [
            "源网段报文名称",
            "源网段报文CANID",
            "源网段报文Length",
            "源网段报文类型",
            "源网段CAN通道",
            "源网段RxIndicationUL",
            "源网段报文Checksum使能",
            "源网段报文Dlc Check使能",
            "目标网段报文名称",
            "目标网段报文CANID",
            "目标网段报文Length",
            "目标网段报文类型",
            "目标网段CAN通道",
            "目标网段报文Checksum使能",
            "目标网段报文PnFilter使能",
            "目标网段报文Truncation使能",
            "路由Length Strategy功能选择",
        ],
        *data_rows,
    ]


def _direct_route_row(
    source_name: str,
    source_id: str,
    source_channel: str,
    target_name: str,
    target_id: str,
    target_channel: str,
) -> list[object]:
    return [
        source_name,
        source_id,
        8,
        "STANDARD_CAN",
        source_channel,
        "PDUR",
        "",
        "Enable",
        target_name,
        target_id,
        8,
        "STANDARD_FD_CAN",
        target_channel,
        "",
        "",
        "Disable",
        "IGNORE",
    ]


def test_standard_gateway_table_uses_target_side_and_has_highest_priority(
    tmp_path: Path,
) -> None:
    direct_rows = (
        _direct_route_row("SourceA", "0x111", "BDCAN", "TargetIC", "0x460", "ICCAN"),
        _direct_route_row("SourceB", "0x222", "CHCAN", "TargetBD", "0x320", "BDCAN"),
        _direct_route_row("SourceC", "0x333", "DACAN", "TargetDK", "0x563", "DKCAN"),
        _direct_route_row("SourceOnly", "0x444", "PTCAN", "", "", ""),
    )
    old_row = [
        "SignalA",
        "Signal",
        "FL_CANFD_CH",
        "ACU_3",
        "0x021",
        "OldTarget",
        "StandardCAN_FD",
        "0x777",
        "√",
    ]
    path = _xlsx(
        tmp_path / "standard-gateway.xlsx",
        {
            "封面": [["网关路由配置表"]],
            "Routing(FLZCU)": _company_routing_sheet(old_row),
            "Fallback": [["目标网段", "CAN ID"], ["PT", "0x555"]],
            "直接报文路由 ": _direct_routing_sheet(*direct_rows),
            "诊断报文路由": [["目标网段报文名称", "目标网段报文CANID"]],
        },
    )

    records = RouteMessageTableParser().parse(path)

    assert [record.target_network_raw for record in records] == ["IC", "BD", "DK"]
    assert [record.can_id for record in records] == [0x460, 0x320, 0x563]
    assert [record.message_name for record in records] == [
        "TargetIC",
        "TargetBD",
        "TargetDK",
    ]
    assert all(record.sheet_name == "直接报文路由 " for record in records)
    assert [record.row_number for record in records] == [2, 3, 4]


def test_standard_gateway_partial_target_row_is_retained_for_audit(
    tmp_path: Path,
) -> None:
    partial = _direct_route_row(
        "SourceA", "0x111", "BDCAN", "TargetDA", "bad-id", "DACAN"
    )
    records = RouteMessageTableParser().parse(
        _xlsx(
            tmp_path / "partial-standard-gateway.xlsx",
            {"直接报文路由": _direct_routing_sheet(partial)},
        )
    )

    assert len(records) == 1
    assert records[0].target_network_raw == "DA"
    assert records[0].can_id_raw == "bad-id"
    assert records[0].can_id is None


def test_malformed_standard_gateway_sheet_does_not_fall_back(
    tmp_path: Path,
) -> None:
    path = _xlsx(
        tmp_path / "malformed-standard-gateway.xlsx",
        {
            "直接报文路由": [["目标网段报文名称", "目标网段报文CANID"]],
            "Routing(FLZCU)": _company_routing_sheet(),
            "Fallback": [["目标网段", "CAN ID"], ["IC", "0x460"]],
        },
    )

    with pytest.raises(RouteTableParseError, match="目标网段CAN通道"):
        RouteMessageTableParser().parse(path)


def test_company_workbook_reads_only_flzcu_and_expands_can_target_matrix(
    tmp_path: Path,
) -> None:
    flzcu_row = [
        "SignalA",
        "Signal",
        "FL_CANFD_CH",
        "ACU_3",
        "0x021",
        "FLZCU_3",
        "StandardCAN_FD",
        "0x460",
        "√",
        "√\nx",
        "√",
        "√",
    ]
    frzcu_row = [
        "SignalB",
        "Message",
        "FR_CANFD_CH",
        "FR_1",
        "0x100",
        "FRZCU_1",
        "StandardCAN_FD",
        "0x777",
        "√",
    ]
    path = _xlsx(
        tmp_path / "company-routes.xlsx",
        {
            "Cover": [["Communication Routing Table"]],
            "Routing(FRZCU)": _company_routing_sheet(frzcu_row),
            "Routing(FLZCU) ": _company_routing_sheet(flzcu_row),
            "信号转义": [["Signal Name", "Description"]],
        },
    )

    records = RouteMessageTableParser().parse(path)

    assert [record.target_network_raw for record in records] == ["IC", "BD"]
    assert [record.can_id for record in records] == [0x460, 0x460]
    assert all(record.message_name == "FLZCU_3" for record in records)
    assert all(record.sheet_name == "Routing(FLZCU) " for record in records)
    assert all(record.row_number == 5 for record in records)


def test_malformed_flzcu_template_does_not_fall_back_to_other_sheets(
    tmp_path: Path,
) -> None:
    path = _xlsx(
        tmp_path / "malformed-company-routes.xlsx",
        {
            "Routing(FLZCU)": [["Service Subscriber Data"]],
            "Fallback": [["目标网段", "CAN ID"], ["IC", "0x460"]],
        },
    )

    with pytest.raises(RouteTableParseError, match="Service Subscriber Subnet"):
        RouteMessageTableParser().parse(path)


@pytest.mark.parametrize("kind", ("missing_column", "corrupted"))
def test_invalid_workbook_is_not_silently_treated_as_empty(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "invalid.xlsx"
    if kind == "missing_column":
        _xlsx(path, {"Routes": [["目标网段", "报文名称"], ["IC", "Msg"]]})
    else:
        path.write_bytes(b"not an xlsx")
    with pytest.raises(RouteTableParseError):
        RouteMessageTableParser().parse(path)


def test_matcher_uses_network_and_can_id_and_audits_edge_cases(
    tmp_path: Path,
) -> None:
    records = RouteMessageTableParser().parse(
        _xlsx(
            tmp_path / "routes.xlsx",
            {
                "Routes": [
                    ["目标网段", "CAN ID", "报文名"],
                    ["IC", "0x460", "ExcelName"],
                    ["IC", "0x460", "ConflictingName"],
                    ["PT", "0x460", "PtMsg"],
                    ["UNKNOWN", "0x123", "Unknown"],
                    ["IC", "0x999", "Missing"],
                    ["IC", "bad", "Invalid"],
                    ["DA", "0x200", "Ambiguous"],
                ]
            },
        )
    )
    report = match_route_messages(
        records,
        {"net-ic": "IC", "net-pt": "PT", "net-da": "DA"},
        {
            "net-ic": ((0x460, "DbcName", True),),
            "net-pt": ((0x460, "PtMsg", False),),
            "net-da": ((0x200, "One", False), (0x200, "Two", True)),
        },
        table_count=1,
    )

    assert report.excluded_can_ids("net-ic") == frozenset({0x460})
    assert report.excluded_can_ids("net-pt") == frozenset({0x460})
    assert report.excluded_message_count == 2
    assert report.duplicate_count == 1
    first, duplicate = report.records[:2]
    assert first.route.target_network_id == "net-ic"
    assert first.dbc_is_extended is True
    assert first.match_status is RouteMatchStatus.MATCHED
    assert first.exclusion_status is RouteExclusionStatus.EXCLUDED
    assert RouteRecordIssue.NAME_MISMATCH_WARNING in first.issues
    assert RouteRecordIssue.DUPLICATE_CONFLICT_WARNING in first.issues
    assert duplicate.exclusion_status is RouteExclusionStatus.ALREADY_EXCLUDED
    assert RouteRecordIssue.DUPLICATE in duplicate.issues
    assert report.records[3].match_status is RouteMatchStatus.NOT_FOUND
    assert "TARGET_NETWORK_NOT_FOUND" in report.records[3].note
    assert report.records[4].match_status is RouteMatchStatus.NOT_FOUND
    assert "MESSAGE_NOT_FOUND" in report.records[4].note
    assert report.records[5].match_status is RouteMatchStatus.INVALID_CAN_ID
    assert report.records[6].match_status is RouteMatchStatus.AMBIGUOUS


def _project_with_offsets(root: Path, networks: tuple[str, ...]) -> Path:
    root.mkdir()
    dbc = Path("tests/fixtures/dbc/minimal.dbc").read_text(encoding="utf-8")
    dbc += '\nBA_ "GenMsgStartDelayTime" BO_ 2147484768 20;\n'
    for network in networks:
        (root / f"CAR_VCU_{network} Message.dbc").write_text(dbc, encoding="utf-8")
    (root / "project.yaml").write_bytes(
        Path("tests/fixtures/config/project.yaml").read_bytes()
    )
    return root


def _request(inspection, output_root: Path) -> GuiBatchOptimizationRequest:
    return GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.PEAK,
        balanced_tolerance=0.05,
        restart=RestartSettings(
            mode=RestartMode.FIXED,
            fixed_attempts=1,
            min_attempts=1,
            max_attempts=1,
        ),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=output_root,
    )


def test_real_backend_accepts_standard_gateway_table(tmp_path: Path) -> None:
    source = _project_with_offsets(tmp_path / "source", ("IC", "PT"))
    _xlsx(
        source / "gateway-routing.xlsx",
        {
            "直接报文路由": _direct_routing_sheet(
                _direct_route_row(
                    "SourceMessage",
                    "0x111",
                    "BDCAN",
                    "Msg460Ext",
                    "0x460",
                    "ICCAN",
                )
            )
        },
    )
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(session, lambda _update: None, token)

    by_name = {network.network_name: network for network in inspection.networks}
    assert inspection.can_optimize
    assert not inspection.errors
    assert inspection.routing_exclusion.record_count == 1
    assert inspection.routing_exclusion.excluded_message_count == 1
    assert by_name["IC"].routing_excluded_count == 1
    assert by_name["PT"].routing_excluded_count == 0


def test_real_backend_excludes_routes_before_gcls_and_keeps_same_id_other_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _project_with_offsets(tmp_path / "source", ("IC", "PT"))
    _xlsx(
        source / "routing.xlsx",
        {"Routes": [["目标网段", "CAN ID", "报文名"], ["IC", "0x460", "WrongName"]]},
    )
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(session, lambda _update: None, token)

    by_name = {network.network_name: network for network in inspection.networks}
    assert session.records_of_kind(InputKind.ROUTING_TABLE)
    assert by_name["IC"].base_eligible_message_count == 2
    assert by_name["IC"].routing_excluded_count == 1
    assert by_name["IC"].final_eligible_message_count == 1
    assert by_name["PT"].routing_excluded_count == 0
    assert inspection.routing_exclusion.records[0].match_status is RouteMatchStatus.MATCHED
    assert RouteRecordIssue.NAME_MISMATCH_WARNING in (
        inspection.routing_exclusion.records[0].issues
    )

    captured: list[tuple[str, ...]] = []
    dbc_replacements: dict[str, tuple[str, ...]] = {}
    original_run_gcls = real_backend_module.run_gcls
    original_write_dbc = real_backend_module.write_dbc_with_offsets

    def capture_run_gcls(messages, *args, **kwargs):
        captured.append(tuple(message.name for message in messages))
        return original_run_gcls(messages, *args, **kwargs)

    monkeypatch.setattr(real_backend_module, "run_gcls", capture_run_gcls)

    def capture_write_dbc(source, output, replacements):
        dbc_replacements[source.name] = tuple(item.message_name for item in replacements)
        return original_write_dbc(source, output, replacements)

    monkeypatch.setattr(
        real_backend_module, "write_dbc_with_offsets", capture_write_dbc
    )
    batch = backend.optimize_all_networks(
        _request(inspection, tmp_path / "workspace" / "user_output"),
        lambda _update: None,
        token,
    )
    results = {item.network_name: item for item in batch.network_results}
    assert results["IC"].status is NetworkRunStatus.SUCCEEDED
    assert results["PT"].status is NetworkRunStatus.SUCCEEDED
    assert {row.message_name for row in results["IC"].result.assignments} == {"Msg391"}  # type: ignore[union-attr]
    assert {row.message_name for row in results["PT"].result.assignments} == {  # type: ignore[union-attr]
        "Msg391",
        "Msg460Ext",
    }
    assert ("Msg391",) in captured
    assert dbc_replacements["CAR_VCU_IC Message.dbc"] == ("Msg391",)

    routing_csv = batch.output_directory / "results" / "routing_exclusion_summary.csv"
    with routing_csv.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["target_network"] == "IC"
    assert rows[0]["target_network_id"] == by_name["IC"].network_id
    assert rows[0]["can_id"] == "0x460"
    assert rows[0]["can_id_raw"] == "0x460"
    assert rows[0]["match_status"] == "matched"
    metadata = json.loads(
        (batch.output_directory / "results" / "run_config.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["routing_table_count"] == 1
    assert metadata["routing_excluded_message_count"] == 1
    assert metadata["final_optimized_message_count"] == 3


def test_all_routes_in_one_network_skip_only_that_network(tmp_path: Path) -> None:
    source = _project_with_offsets(tmp_path / "source", ("IC", "PT"))
    _xlsx(
        source / "routing.xlsx",
        {
            "Routes": [
                ["目标网段", "CAN ID"],
                ["IC", "0x391"],
                ["IC", "0x460"],
            ]
        },
    )
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(session, lambda _update: None, token)
    by_name = {network.network_name: network for network in inspection.networks}

    assert not by_name["IC"].is_optimizable
    assert by_name["IC"].unoptimizable_reason == (
        "跳过：所有可优化周期 TX 报文均为路由报文"
    )
    assert by_name["PT"].is_optimizable
    batch = backend.optimize_all_networks(
        _request(inspection, tmp_path / "workspace" / "user_output"),
        lambda _update: None,
        token,
    )
    statuses = {item.network_name: item.status for item in batch.network_results}
    assert statuses == {
        "IC": NetworkRunStatus.SKIPPED,
        "PT": NetworkRunStatus.SUCCEEDED,
    }


def test_invalid_routing_schema_blocks_inspection(tmp_path: Path) -> None:
    source = _project_with_offsets(tmp_path / "source", ("IC",))
    _xlsx(source / "routing.xlsx", {"Routes": [["目标网段"], ["IC"]]})
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(session, lambda _update: None, token)

    assert not inspection.can_optimize
    assert any("路由报文排除表解析失败" in error for error in inspection.errors)


def test_no_routing_table_preserves_existing_optimization(tmp_path: Path) -> None:
    source = _project_with_offsets(tmp_path / "source", ("IC",))
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    token = CancellationToken()
    session = backend.import_inputs((source,), lambda _update: None, token)
    inspection = backend.inspect_workspace(session, lambda _update: None, token)

    assert inspection.routing_exclusion.table_count == 0
    assert inspection.routing_excluded_message_count == 0
    assert inspection.final_eligible_message_count == 2
    batch = backend.optimize_all_networks(
        _request(inspection, tmp_path / "workspace" / "user_output"),
        lambda _update: None,
        token,
    )
    result = batch.network_results[0].result
    assert result is not None
    assert {row.message_name for row in result.assignments} == {"Msg391", "Msg460Ext"}


def test_gui_summary_and_details_trace_source_sheet_and_row(
    qapp, inspection, tmp_path: Path
) -> None:
    del qapp
    network = inspection.networks[0]
    source_records = RouteMessageTableParser().parse(
        _xlsx(
            tmp_path / "routes.xlsx",
            {"Audit": [["目标网段", "CAN ID"], [network.network_name, "0x123"]]},
        )
    )
    report = match_route_messages(
        source_records,
        {network.network_id: network.network_name},
        {network.network_id: ((0x123, "RouteMsg", False),)},
        table_count=1,
    )
    routed_network = replace(
        network,
        message_count=network.message_count - 1,
        base_eligible_message_count=network.message_count,
        routing_excluded_count=1,
        final_eligible_message_count=network.message_count - 1,
    )
    routed_inspection = replace(
        inspection,
        networks=(routed_network, *inspection.networks[1:]),
        routing_exclusion=report,
    )
    panel = InputPanel()
    panel.set_inspection(routed_inspection)

    assert "路由记录：1" in panel.routing_label.text()
    assert "已匹配：1" in panel.routing_label.text()
    model = panel.routing_details_model
    assert model.rowCount() == 1
    assert model.data(model.index(0, 6)) == "routes.xlsx"
    assert model.data(model.index(0, 7)) == "Audit"
    assert model.data(model.index(0, 8)) == "2"
    assert panel.details_dialog.tabs.tabText(2) == "路由报文排除"
    panel.details_dialog.routing_proxy.set_filter_name("excluded")
    assert panel.details_dialog.routing_proxy.rowCount() == 1
    panel.details_dialog.routing_proxy.set_filter_name("not_found")
    assert panel.details_dialog.routing_proxy.rowCount() == 0
