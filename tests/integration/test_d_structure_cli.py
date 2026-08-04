"""CLI integration tests over the real production loader with tiny locked inputs."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml

from canfd_offset_optimizer.cli import main
from canfd_offset_optimizer.diagnostics.d_structure import (
    NETWORK_ORDER,
    eligible_set_hash,
    sha256_file,
)
from canfd_offset_optimizer.final_experiment import (
    FinalExperimentInput,
    load_final_experiment_project,
)
from canfd_offset_optimizer.optimization.joint import build_joint_domain

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _inline_cell(reference: str, value: object) -> str:
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _write_empty_routing_xlsx(path: Path) -> None:
    headers = (
        "目标网段报文名称",
        "目标网段报文CANID",
        "目标网段报文类型",
        "目标网段CAN通道",
    )
    cells = "".join(
        _inline_cell(f"{chr(ord('A') + index)}1", value) for index, value in enumerate(headers)
    )
    route_cells = "".join(
        _inline_cell(f"{chr(ord('A') + index)}2", value)
        for index, value in enumerate(("Other", "1", "STANDARD_FD_CAN", "ZZCAN"))
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="直接报文路由" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{cells}</row><row r="2">{route_cells}</row></sheetData>'
        "</worksheet>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def _write_manifest(tmp_path: Path) -> Path:
    routing = tmp_path / "routing.xlsx"
    _write_empty_routing_xlsx(routing)
    dbc = (FIXTURES / "dbc" / "minimal.dbc").resolve()
    arxml_dir = (FIXTURES / "arxml").resolve()
    config = (FIXTURES / "config" / "project.yaml").resolve()
    spec = FinalExperimentInput(
        network_id="CH",
        dbc_path=dbc,
        selected_sender="VCU",
        protocol="CAN_FD",
        routing_excel_path=routing,
        routing_target_network="CHCAN",
        arxml_dir=arxml_dir,
        config_path=config,
        channel="CAN1",
    )
    loaded = load_final_experiment_project(spec)
    domain = build_joint_domain(loaded.network.messages, loaded.config.optimization)
    eligible = eligible_set_hash(loaded)
    manifest = {
        "schema_version": 1,
        "paper_ready_preflight": True,
        "source_head_commit": "archive-source-commit",
        "source_worktree_status": "M historical-source",
        "shared_inputs": {
            "routing_excel_path": str(routing.resolve()),
            "routing_excel_sha256": sha256_file(routing),
            "arxml_dir": str(arxml_dir),
            "arxml_files": [
                {
                    "path": str(path.resolve()),
                    "sha256": sha256_file(path),
                }
                for path in sorted(arxml_dir.rglob("*.arxml"))
            ],
            "config_path": str(config),
            "config_sha256": sha256_file(config),
        },
        "optimization": {"joint": {"rho": "1/1"}},
        "networks": [
            {
                "network": network,
                "sender": "VCU",
                "protocol": "CAN_FD",
                "dbc_path": str(dbc),
                "dbc_sha256": sha256_file(dbc),
                "routing_target_network": f"{network}CAN",
                "channel": "CAN1",
                "eligible_set_sha256": eligible,
                "joint_decision": len(domain.decision_messages),
                "joint_fixed": len(domain.fixed_messages),
            }
            for network in NETWORK_ORDER
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _strip_runtime_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_runtime_fields(item)
            for key, item in value.items()
            if "elapsed" not in key and key != "command"
        }
    if isinstance(value, list):
        return [_strip_runtime_fields(item) for item in value]
    return value


def test_single_network_end_to_end_is_deterministic_except_elapsed(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    output = tmp_path / "output"
    arguments = (
        "analyze-d-structure",
        "--manifest",
        str(manifest),
        "--network",
        "CH",
        "--rho",
        "1/3",
        "--output-root",
        str(output),
    )
    assert main(arguments) == 0
    directory = output / "CH" / "d_structure"
    first_csv = {path.name: path.read_bytes() for path in directory.glob("*.csv")}
    first_summary = json.loads((directory / "d_structure_summary.json").read_text(encoding="utf-8"))
    assert main(arguments) == 0
    assert first_csv == {path.name: path.read_bytes() for path in directory.glob("*.csv")}
    second_summary = json.loads(
        (directory / "d_structure_summary.json").read_text(encoding="utf-8")
    )
    assert _strip_runtime_fields(first_summary) == _strip_runtime_fields(second_summary)
    assert second_summary["status"]["exactness_status"] == "exact"
    assert second_summary["archive"]["provenance_comparable"] is False


def test_batch_nine_network_summary_uses_fixed_order(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    output = tmp_path / "output"
    assert (
        main(
            (
                "analyze-d-structure",
                "--manifest",
                str(manifest),
                "--output-root",
                str(output),
                "--max-histogram-states",
                "10000",
                "--max-exact-pstar-evaluations",
                "10000",
                "--timeout-s",
                "30",
            )
        )
        == 0
    )
    summary = json.loads(
        (output / "d_structure_nine_network_summary.json").read_text(encoding="utf-8")
    )
    assert tuple(item["network"] for item in summary["networks"]) == NETWORK_ORDER
    assert all(item["exactness_status"] == "exact" for item in summary["networks"])
    assert (
        (output / "d_structure_nine_network_summary.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    )
    assert all(
        (output / network / "d_structure" / "d_structure_summary.json").is_file()
        for network in NETWORK_ORDER
    )


def test_cli_cap_is_reported_without_false_coverage(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    output = tmp_path / "output"
    assert (
        main(
            (
                "analyze-d-structure",
                "--manifest",
                str(manifest),
                "--network",
                "CH",
                "--output-root",
                str(output),
                "--max-histogram-states",
                "1",
            )
        )
        == 1
    )
    summary = json.loads(
        (output / "CH" / "d_structure" / "d_structure_summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"]["exactness_status"] == "capped"
    assert summary["status"]["structure_classification"] == "incomplete_due_to_cap"
    assert summary["archive"]["histogram_coverage"] is None
    assert summary["enumeration"]["reachable_histogram_count"] is None
