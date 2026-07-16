"""! @file test_end_to_end.py
@brief 使用脱敏四报文夹具验证 CLI 全部稳定输出。

@author 篠見由紀
"""

import csv
import json
from pathlib import Path

import pytest

from canfd_offset_optimizer.cli import main


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_cli_generates_complete_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    exit_code = main(
        [
            "optimize",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(output),
            "--seed",
            "42",
            "--restarts",
            "1",
        ]
    )
    assert exit_code == 0
    expected = (
        output / "results" / "offsets.csv",
        output / "results" / "slot_loads.csv",
        output / "results" / "summary.json",
        output / "plots" / "steady_load.png",
        output / "plots" / "startup_load.png",
        output / "logs" / "run.log",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
    assert expected[0].read_bytes().startswith(b"\xef\xbb\xbf")
    with expected[0].open(encoding="utf-8-sig", newline="") as stream:
        offsets = list(csv.DictReader(stream))
    assert len(offsets) == 4
    assert all(int(row["recommended_offset_us"]) in range(15_000, 100_001, 5_000) for row in offsets)
    summary = json.loads(expected[2].read_text(encoding="utf-8"))
    assert summary["algorithm"]["name"] == "GCLS"
    assert [record["seed"] for record in summary["restarts"]] == [42, 43]
    assert tuple(summary["objective_after"]) <= tuple(summary["objective_first_greedy"])
    assert tuple(summary["objective_after"]) <= tuple(summary["objective_before"])


def test_cli_returns_nonzero_for_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(
        [
            "optimize",
            "--dbc",
            str(tmp_path / "missing.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(tmp_path / "output"),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_approximate_mode_reports_weight_units_without_physical_threshold(
    tmp_path: Path,
) -> None:
    config = tmp_path / "approximate.yaml"
    config.write_text(
        (FIXTURES / "config" / "project.yaml")
        .read_text(encoding="utf-8")
        .replace("frame_time_us", "unit")
        .replace("random_restarts: 2", "random_restarts: 0"),
        encoding="utf-8",
    )
    output = tmp_path / "approximate-output"
    assert main(
        [
            "optimize",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(config),
            "--output",
            str(output),
        ]
    ) == 0
    summary = json.loads(
        (output / "results" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["weight_mode"] == "unit"
    assert summary["average_load"] is None
    assert summary["average_load_limit"] is None
    assert summary["slot_load_threshold_us"] is None
    assert summary["objectives"]["after"]["violation_count"] == 0
    assert summary["objectives"]["after"]["violation_excess"] == 0
    assert summary["objectives"]["lexicographic_order"][1] == "violation_excess"
    with (output / "results" / "slot_loads.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        first = next(csv.DictReader(stream))
    assert first["weight_mode"] == "unit"
    assert first["weighted_load_us"] == ""
    assert first["load_ratio"] == ""
    assert first["threshold_violation"] == ""


def test_cli_reports_invalid_yaml_bitrate_as_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "invalid.yaml"
    config.write_text(
        "network:\n  channel: CAN1\n  nominal_bitrate: 0\n"
        "  data_bitrate: 2000000\n  brs: true\n",
        encoding="utf-8",
    )
    assert main(
        [
            "optimize",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(config),
            "--output",
            str(tmp_path / "output"),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "unexpected error" not in captured.err
    assert "nominal_bitrate" in captured.err


def test_compare_cli_generates_five_stage_approximate_reports(tmp_path: Path) -> None:
    output = tmp_path / "comparison"
    assert main(
        [
            "compare",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(output),
            "--weight-mode",
            "payload_bytes",
            "--seed",
            "42",
            "--restarts",
            "1",
        ]
    ) == 0
    expected = (
        output / "results" / "algorithm_comparison.csv",
        output / "results" / "offsets_comparison.csv",
        output / "results" / "slot_loads_comparison.csv",
        output / "results" / "comparison_summary.json",
        output / "plots" / "steady_load_comparison.png",
        output / "plots" / "startup_load_comparison.png",
        output / "plots" / "steady_congestion_heatmap.png",
        output / "plots" / "steady_message_timeline.png",
        output / "plots" / "startup_congestion_heatmap.png",
        output / "plots" / "startup_message_timeline.png",
        output / "logs" / "run.log",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
    assert all(path.read_bytes().startswith(b"\xef\xbb\xbf") for path in expected[:3])
    with expected[0].open(encoding="utf-8-sig", newline="") as stream:
        algorithms = list(csv.DictReader(stream))
    assert [row["stage"] for row in algorithms] == [
        "original",
        "minimum",
        "greedy",
        "greedy_1opt",
        "gcls",
    ]
    with expected[1].open(encoding="utf-8-sig", newline="") as stream:
        offsets_reader = csv.DictReader(stream)
        offsets = list(offsets_reader)
    assert len(offsets) == 4
    assert offsets_reader.fieldnames is not None
    assert len(offsets_reader.fieldnames) == len(set(offsets_reader.fieldnames))
    assert offsets_reader.fieldnames == [
        "报文名称",
        "CAN_ID",
        "帧格式",
        "发送节点",
        "周期(ms)",
        "载荷长度(Byte)",
        "DBC原始Offset(ms)",
        "原始方案Offset(ms)",
        "最小Offset方案(ms)",
        "Greedy推荐Offset(ms)",
        "Greedy+1-opt推荐Offset(ms)",
        "GCLS推荐Offset(ms)",
    ]
    assert offsets[0]["周期(ms)"] == "20"
    assert offsets[0]["帧格式"] == "标准帧"
    assert float(offsets[0]["GCLS推荐Offset(ms)"]) >= 15
    with expected[2].open(encoding="utf-8-sig", newline="") as stream:
        slot = next(csv.DictReader(stream))
    assert slot["weight_mode"] == "payload_bytes"
    assert slot["weighted_load_us"] == ""
    assert slot["load_ratio"] == ""
    assert slot["threshold_violation"] == ""
    summary = json.loads(expected[3].read_text(encoding="utf-8"))
    assert summary["weight_mode"] == "payload_bytes"
    assert summary["field_sources"]["weight_mode"] == "CLI --weight-mode override"
    assert summary["slot_load_threshold_us"] is None
    assert [item["seed"] for item in summary["restarts"]] == [42, 43]
    assert any("CLI overrides" in warning for warning in summary["warnings"])
    log = expected[-1].read_text(encoding="utf-8")
    assert "Comparison restart seed=42" in log
    assert "Comparison restart seed=43" in log
