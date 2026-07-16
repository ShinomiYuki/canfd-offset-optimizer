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
        output / "results" / "output_offsets.csv",
        output / "results" / "output_slot_loads.csv",
        output / "results" / "summary.json",
        output / "plots" / "output_steady_load.png",
        output / "plots" / "output_startup_load.png",
        output / "logs" / "run.log",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
    assert expected[0].read_bytes().startswith(b"\xef\xbb\xbf")
    with expected[0].open(encoding="utf-8-sig", newline="") as stream:
        offsets = list(csv.DictReader(stream))
    assert len(offsets) == 4
    assert all(
        int(row["推荐Offset(μs)"]) in range(15_000, 100_001, 5_000)
        for row in offsets
    )
    summary = json.loads(expected[2].read_text(encoding="utf-8"))
    assert summary["algorithm"]["name"] == "GCLS"
    assert summary["algorithm"]["seed"] == 42
    assert summary["cli_overrides"]["random_restarts"] == "1"
    assert summary["field_sources"]["random_restarts"] == "CLI --restarts override"
    assert summary["effective_configuration"]["random_restarts"] == 1
    assert len(summary["input_hash"]) == 64
    assert [record["seed"] for record in summary["restarts"]] == [42]
    assert len(summary["selected_peak_candidates"]) == 1
    assert len(summary["balanced_candidate_searches"]) == 1
    assert summary["balanced_candidate_searches"][0]["triple_search"] is None
    assert summary["algorithm"]["restart_stop_reason"] == "peak_candidate_pool_exhausted"
    assert tuple(summary["objective_after"]) <= tuple(summary["objective_first_greedy"])
    assert tuple(summary["objective_after"]) <= tuple(summary["objective_before"])


def test_candidate_pool_diagnostic_cli_generates_audit_outputs(tmp_path: Path) -> None:
    output = tmp_path / "candidate_pool"
    assert main(
        [
            "analyze-candidate-pools",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(output),
            "--channel",
            "CAN1",
            "--restarts",
            "3",
            "--pool-sizes",
            "1,4",
        ]
    ) == 0
    summary = json.loads(
        (output / "results" / "candidate_pool_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["pool_sizes"] == [1, 4]
    assert (output / "results" / "candidate_pool_audit.jsonl").is_file()
    assert (output / "results" / "candidate_pool_comparison.csv").read_bytes().startswith(
        b"\xef\xbb\xbf"
    )


def test_triple_ablation_cli_generates_four_group_report(tmp_path: Path) -> None:
    output = tmp_path / "triple_ablation"
    assert main(
        [
            "analyze-triple-ablation",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(output),
            "--channel",
            "CAN1",
            "--restarts",
            "3",
        ]
    ) == 0
    summary = json.loads(
        (output / "results" / "triple_ablation_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert [variant["group"] for variant in summary["variants"]] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert (output / "results" / "triple_ablation_audit.jsonl").is_file()


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
    with (output / "results" / "approximate-output_slot_loads.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        first = next(csv.DictReader(stream))
    assert first["权重模式"] == "unit"
    assert first["加权负载(μs)"] == ""
    assert first["负载比例"] == ""
    assert first["是否超过阈值"] == ""


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
        output / "results" / "comparison_algorithm_comparison.csv",
        output / "results" / "comparison_offsets_comparison.csv",
        output / "results" / "comparison_slot_loads_comparison.csv",
        output / "results" / "comparison_summary.json",
        output / "plots" / "comparison_steady_load_comparison.png",
        output / "plots" / "comparison_startup_load_comparison.png",
        output / "plots" / "comparison_steady_congestion_heatmap.png",
        output / "plots" / "comparison_steady_message_timeline.png",
        output / "plots" / "comparison_startup_congestion_heatmap.png",
        output / "plots" / "comparison_startup_message_timeline.png",
        output / "logs" / "run.log",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
    assert all(path.read_bytes().startswith(b"\xef\xbb\xbf") for path in expected[:3])
    with expected[0].open(encoding="utf-8-sig", newline="") as stream:
        algorithms = list(csv.DictReader(stream))
    assert [row["阶段"] for row in algorithms] == [
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
    assert slot["权重模式"] == "payload_bytes"
    assert slot["加权负载(μs)"] == ""
    assert slot["负载比例"] == ""
    assert slot["是否超过阈值"] == ""
    summary = json.loads(expected[3].read_text(encoding="utf-8"))
    assert summary["weight_mode"] == "payload_bytes"
    assert summary["field_sources"]["weight_mode"] == "CLI --weight-mode override"
    assert summary["slot_load_threshold_us"] is None
    assert [item["seed"] for item in summary["restarts"]] == [42, 43]
    assert any("CLI overrides" in warning for warning in summary["warnings"])
    log = expected[-1].read_text(encoding="utf-8")
    assert "Comparison restart seed=42" in log
    assert "Comparison restart seed=43" in log


def test_objective_mode_cli_override_is_audited(tmp_path: Path) -> None:
    output = tmp_path / "variance"
    assert main(
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
            "--objective-mode",
            "variance",
            "--restarts",
            "0",
        ]
    ) == 0
    summary = json.loads(
        (output / "results" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["objectives"]["objective_mode"] == "variance"
    assert summary["field_sources"]["objective_mode"] == (
        "CLI --objective-mode override"
    )
    assert any("objective.mode" in warning for warning in summary["warnings"])


def test_compare_weights_cli_generates_both_complete_reports(tmp_path: Path) -> None:
    output = tmp_path / "dual"
    assert main(
        [
            "compare-weights",
            "--dbc",
            str(FIXTURES / "dbc" / "four_messages.dbc"),
            "--arxml",
            str(FIXTURES / "arxml"),
            "--config",
            str(FIXTURES / "config" / "project.yaml"),
            "--output",
            str(output),
            "--channel",
            "CAN1",
            "--seed",
            "42",
            "--restarts",
            "1",
        ]
    ) == 0
    relative_mode_files = (
        Path("results/dual_algorithm_comparison.csv"),
        Path("results/dual_offsets_comparison.csv"),
        Path("results/dual_slot_loads_comparison.csv"),
        Path("results/comparison_summary.json"),
        Path("plots/dual_steady_load_comparison.png"),
        Path("plots/dual_startup_load_comparison.png"),
        Path("plots/dual_steady_congestion_heatmap.png"),
        Path("plots/dual_startup_congestion_heatmap.png"),
        Path("plots/dual_steady_message_timeline.png"),
        Path("plots/dual_startup_message_timeline.png"),
        Path("logs/run.log"),
    )
    for mode in ("payload_bytes", "frame_time_us"):
        assert all(
            (output / mode / relative).is_file()
            and (output / mode / relative).stat().st_size > 0
            for relative in relative_mode_files
        )
        summary = json.loads(
            (output / mode / "results/comparison_summary.json").read_text(
                encoding="utf-8"
            )
        )
        assert summary["weight_mode"] == mode
        assert summary["network"]["nominal_bitrate_bit_s"] == 500_000
        assert summary["network"]["data_bitrate_bit_s"] == 2_000_000
        assert summary["network"]["brs"] is True
        assert summary["field_sources"]["channel"] == "CLI --channel override"
        expected_seeds = [42, 43] if mode == "payload_bytes" else [42]
        assert [record["seed"] for record in summary["restarts"]] == expected_seeds
    for mode in ("peak", "variance"):
        assert all(
            (output / "objective_modes" / mode / relative).is_file()
            and (output / "objective_modes" / mode / relative).stat().st_size > 0
            for relative in relative_mode_files
        )
    combined = (
        output / "results/dual_weight_mode_comparison.csv",
        output / "results/dual_offsets_weight_mode_comparison.csv",
        output / "results/weight_mode_summary.json",
        output / "results/dual_objective_mode_comparison.csv",
        output / "results/dual_offsets_objective_mode_comparison.csv",
        output / "results/objective_mode_summary.json",
        output / "plots/dual_steady_objective_mode_comparison.png",
        output / "logs/run.log",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in combined)
    assert combined[0].read_bytes().startswith(b"\xef\xbb\xbf")
    assert combined[1].read_bytes().startswith(b"\xef\xbb\xbf")
    with combined[0].open(encoding="utf-8-sig", newline="") as stream:
        mode_rows = list(csv.DictReader(stream))
    assert [row["权重模式"] for row in mode_rows] == [
        "payload_bytes",
        "frame_time_us",
    ]
    with combined[1].open(encoding="utf-8-sig", newline="") as stream:
        offset_rows = list(csv.DictReader(stream))
    assert len(offset_rows) == 4
    for row in offset_rows:
        assert int(row["保守帧占用时间(μs)"]) > 0
        for column in (
            "payload_bytes_GCLS_Offset(ms)",
            "frame_time_us_peak_GCLS_Offset(ms)",
            "frame_time_us_balanced_GCLS_Offset(ms)",
            "frame_time_us_variance_GCLS_Offset(ms)",
        ):
            assert float(row[column]) in range(15, 101, 5)
    combined_summary = json.loads(combined[2].read_text(encoding="utf-8"))
    assert combined_summary["recommended_production_mode"] == "frame_time_us"
    assert set(combined_summary["modes"]) == {"payload_bytes", "frame_time_us"}
    objective_summary = json.loads(combined[5].read_text(encoding="utf-8"))
    assert objective_summary["recommended_mode"] == "balanced"
    assert set(objective_summary["modes"]) == {"peak", "balanced", "variance"}
    balanced_summary = objective_summary["modes"]["balanced"]
    assert balanced_summary["comparison"]["peak_budget_us"] > 0
    assert [
        record["seed"]
        for record in balanced_summary["comparison"]["peak_reference_restarts"]
    ] == [42, 43]
    assert balanced_summary["load_statistics"]["steady"][
        "standard_deviation_us"
    ] >= 0
    peak_objective = objective_summary["modes"]["peak"]["stages"][-1]["objective"]
    variance_objective = objective_summary["modes"]["variance"]["stages"][-1][
        "objective"
    ]
    assert variance_objective["violation_count"] <= peak_objective["violation_count"]
    if variance_objective["violation_count"] == peak_objective["violation_count"]:
        assert variance_objective["violation_excess"] <= peak_objective[
            "violation_excess"
        ]
        if variance_objective["violation_excess"] == peak_objective["violation_excess"]:
            assert variance_objective["sum_square_load"] <= peak_objective[
                "sum_square_load"
            ]
    aggregate = tmp_path / "ALL_offsets_weight_mode_comparison.csv"
    with aggregate.open(encoding="utf-8-sig", newline="") as stream:
        aggregate_rows = list(csv.DictReader(stream))
    assert len(aggregate_rows) == 4
    assert {row["网段"] for row in aggregate_rows} == {"dual"}
    objective_aggregate = tmp_path / "ALL_network_objective_mode_summary.csv"
    assert objective_aggregate.read_bytes().startswith(b"\xef\xbb\xbf")
    with objective_aggregate.open(encoding="utf-8-sig", newline="") as stream:
        objective_rows = list(csv.DictReader(stream))
    assert len(objective_rows) == 1
    assert objective_rows[0]["网段"] == "dual"
