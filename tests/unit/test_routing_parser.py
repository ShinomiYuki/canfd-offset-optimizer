"""Routing Excel normalization and final eligible-set exclusion tests."""

from __future__ import annotations

from dataclasses import replace
from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from canfd_offset_optimizer.models import WeightMode
from canfd_offset_optimizer.optimization.joint import build_joint_domain
from canfd_offset_optimizer.parsers.project_loader import load_project
from canfd_offset_optimizer.parsers.routing_parser import (
    RouteMessageKey,
    normalize_can_id,
    normalize_target_network,
    parse_routing_excel,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"


def _inline_cell(reference: str, value: object) -> str:
    return (
        f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    )


def _write_routing_xlsx(
    path: Path,
    rows: tuple[tuple[str, str, str, str], ...],
) -> None:
    headers = (
        "目标网段报文名称",
        "目标网段报文CANID",
        "目标网段报文类型",
        "目标网段CAN通道",
    )
    all_rows = (headers, *rows)
    row_xml = []
    for row_index, row in enumerate(all_rows, start=1):
        cells = "".join(
            _inline_cell(f"{chr(ord('A') + column_index)}{row_index}", value)
            for column_index, value in enumerate(row)
        )
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="直接报文路由" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(row_xml)}</sheetData></worksheet>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def test_network_and_can_id_normalization_is_deterministic() -> None:
    assert normalize_target_network(" CH-CAN ") == "CH"
    assert normalize_target_network("ch") == "CH"
    assert normalize_can_id("0x391") == 0x391
    assert normalize_can_id("391h") == 0x391
    assert normalize_can_id(913.0) == 913


def test_routing_excel_parses_target_network_can_id_and_extended_flag(
    tmp_path: Path,
) -> None:
    path = tmp_path / "routing.xlsx"
    _write_routing_xlsx(
        path,
        (
            ("Msg391", "0x391", "STANDARD_FD_CAN", "CHCAN"),
            ("MsgExt", "0x1ABCDE", "EXTENDED_FD_CAN", "CHCAN"),
            ("Other", "913", "STANDARD_FD_CAN", "DACAN"),
        ),
    )

    table = parse_routing_excel(path)

    assert table.keys_for_target("CH") == frozenset(
        {
            RouteMessageKey("CH", 0x391, False),
            RouteMessageKey("CH", 0x1ABCDE, True),
        }
    )
    assert table.keys_for_target("DA") == frozenset(
        {RouteMessageKey("DA", 913, False)}
    )


def test_loader_excludes_only_exact_target_network_and_can_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "routing.xlsx"
    _write_routing_xlsx(
        path,
        (
            ("Msg391", "0x391", "STANDARD_FD_CAN", "CHCAN"),
            ("WrongNetwork", "0x460", "EXTENDED_FD_CAN", "DACAN"),
            ("WrongId", "0x392", "STANDARD_FD_CAN", "CHCAN"),
        ),
    )

    loaded = load_project(
        FIXTURES / "dbc" / "minimal.dbc",
        FIXTURES / "arxml",
        FIXTURES / "config" / "project.yaml",
        selected_sender="VCU",
        routing_excel_path=path,
        routing_target_network="CH",
        weight_mode_override=WeightMode.FRAME_TIME_US,
        require_original_offsets=True,
    )

    assert {message.name for message in loaded.network.messages} == {"Msg460Ext"}
    assert [item.message_name for item in loaded.routing_exclusions] == ["Msg391"]
    assert loaded.eligible_start_delay_default_count == 1
    assert loaded.eligible_start_delay_unknown_count == 0


def test_route_excluded_messages_are_not_joint_fixed_messages(tmp_path: Path) -> None:
    path = tmp_path / "routing.xlsx"
    _write_routing_xlsx(
        path,
        (("Msg391", "0x391", "STANDARD_FD_CAN", "CHCAN"),),
    )
    loaded = load_project(
        FIXTURES / "dbc" / "minimal.dbc",
        FIXTURES / "arxml",
        FIXTURES / "config" / "project.yaml",
        selected_sender="VCU",
        routing_excel_path=path,
        routing_target_network="CH",
        require_original_offsets=True,
    )
    joint_config = replace(
        loaded.config.optimization,
        offset_max_us=50_000,
    )

    domain = build_joint_domain(loaded.network.messages, joint_config)

    assert {message.name for message in domain.fixed_messages} == {"Msg460Ext"}
    assert "Msg391" not in {
        message.name for message in domain.decision_messages + domain.fixed_messages
    }
