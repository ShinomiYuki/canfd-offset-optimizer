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
