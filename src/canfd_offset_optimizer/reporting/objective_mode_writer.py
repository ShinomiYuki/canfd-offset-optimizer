"""Write unified physical cross-evaluation reports for objective modes."""

from __future__ import annotations

import csv
import json
from math import sqrt
from pathlib import Path
from typing import Any

from ..config import ProjectConfig
from ..models import (
    AlgorithmComparisonResult,
    ComparisonStageResult,
    NetworkModel,
    ObjectiveMode,
    WeightMode,
)
from .comparison_writer import build_comparison_summary
from .filenames import prefixed_report_name
from .summary_writer import combined_input_hash


def load_statistics(loads: tuple[int, ...]) -> tuple[float, float, float]:
    """Return population mean, variance and standard deviation of slot loads."""
    if not loads:
        return 0.0, 0.0, 0.0
    mean = sum(loads) / len(loads)
    variance = sum((load - mean) ** 2 for load in loads) / len(loads)
    return mean, variance, sqrt(variance)


def _rate(baseline: float, candidate: float) -> float | None:
    return None if baseline == 0 else (baseline - candidate) / baseline


def _stage_metrics(
    label: str,
    result: AlgorithmComparisonResult,
    stage: ComparisonStageResult,
    reference_peak_us: int,
    budget_us: int,
    input_hash: str,
) -> dict[str, object]:
    steady_mean, steady_variance, steady_stddev = load_statistics(
        stage.steady_slot_loads
    )
    startup_mean, startup_variance, startup_stddev = load_statistics(
        stage.startup_slot_loads
    )
    value = stage.objective
    return {
        "result": label,
        "comparison_policy": (
            value.mode.value if label != "original" else "physical_cross_evaluation"
        ),
        "weight_mode": WeightMode.FRAME_TIME_US.value,
        "Nvio": value.violation_count,
        "Vvio_us": value.violation_excess,
        "Zss_us": value.steady_peak,
        "Qss_us2": value.sum_square_load,
        "steady_mean_us": steady_mean,
        "steady_variance_us2": steady_variance,
        "steady_standard_deviation_us": steady_stddev,
        "Zst_us": value.startup_peak,
        "Qst_us2": value.startup_sum_square_load,
        "startup_mean_us": startup_mean,
        "startup_variance_us2": startup_variance,
        "startup_standard_deviation_us": startup_stddev,
        "Kmax": value.max_release_count,
        "strict_peak_gcls_reference_us": reference_peak_us,
        "peak_budget_us": budget_us,
        "peak_budget_excess_us": max(0, value.steady_peak - budget_us),
        "runtime_seconds": stage.elapsed_seconds,
        "seed": result.seed,
        "input_hash": input_hash,
        "balanced_fallback_reason": result.balanced_fallback_reason,
    }


def write_objective_mode_reports(
    output_root: Path,
    network: NetworkModel,
    configs: dict[ObjectiveMode, ProjectConfig],
    results: dict[ObjectiveMode, AlgorithmComparisonResult],
    report_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """Write Original/peak/balanced/variance using one frame-time metric system."""
    expected = (ObjectiveMode.PEAK, ObjectiveMode.BALANCED, ObjectiveMode.VARIANCE)
    if tuple(results) != expected or set(configs) != set(expected):
        raise ValueError("objective mode reports require ordered peak/balanced/variance results")
    if network.weight_mode is not WeightMode.FRAME_TIME_US:
        raise ValueError("objective mode cross-evaluation requires frame_time_us")

    originals = tuple(results[mode].stage("original") for mode in expected)
    if len({stage.objective.metrics_tuple() for stage in originals}) != 1:
        raise ValueError("objective modes do not share one physical Original evaluation")
    balanced = results[ObjectiveMode.BALANCED]
    if balanced.peak_reference_objective is None or balanced.peak_budget_us is None:
        raise ValueError("balanced result lacks strict-peak reference metadata")

    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = results_dir / prefixed_report_name(
        "objective_mode_comparison.csv", report_prefix
    )
    offsets_path = results_dir / prefixed_report_name(
        "offsets_objective_mode_comparison.csv", report_prefix
    )
    summary_path = results_dir / "objective_mode_summary.json"

    input_hash = combined_input_hash(network.input_files)
    reference_peak = balanced.peak_reference_objective.steady_peak
    budget = balanced.peak_budget_us
    evaluated: tuple[
        tuple[str, AlgorithmComparisonResult, ComparisonStageResult], ...
    ] = (
        ("original", results[ObjectiveMode.PEAK], originals[0]),
        *tuple(
            (mode.value, results[mode], results[mode].stage("gcls"))
            for mode in expected
        ),
    )
    rows = [
        _stage_metrics(label, result, stage, reference_peak, budget, input_hash)
        for label, result, stage in evaluated
    ]
    with comparison_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    offsets = {
        mode: results[mode].stage("gcls").offset_by_name() for mode in expected
    }
    original_offsets = results[ObjectiveMode.PEAK].stage("original").offset_by_name()
    offset_rows: list[dict[str, object]] = []
    for message in results[ObjectiveMode.BALANCED].messages:
        peak_offset = offsets[ObjectiveMode.PEAK][message.name]
        balanced_offset = offsets[ObjectiveMode.BALANCED][message.name]
        variance_offset = offsets[ObjectiveMode.VARIANCE][message.name]
        offset_rows.append(
            {
                "message_name": message.name,
                "CAN_ID": f"0x{message.can_id:X}",
                "cycle_time_ms": message.cycle_time_us / 1_000,
                "payload_bytes": message.payload_bytes,
                "frame_time_us": message.frame_time_us,
                "DBC_original_offset_ms": (
                    message.original_offset_us / 1_000
                    if message.original_offset_us is not None
                    else ""
                ),
                "physical_original_offset_ms": original_offsets[message.name] / 1_000,
                "frame_time_us_peak_GCLS_Offset(ms)": peak_offset / 1_000,
                "frame_time_us_balanced_GCLS_Offset(ms)": balanced_offset / 1_000,
                "frame_time_us_variance_GCLS_Offset(ms)": variance_offset / 1_000,
                "peak_balanced_offset_changed": peak_offset != balanced_offset,
                "peak_balanced_steady_phase_changed": (
                    peak_offset % message.cycle_time_us
                    != balanced_offset % message.cycle_time_us
                ),
                "balanced_variance_offset_changed": balanced_offset != variance_offset,
                "peak_variance_offset_changed": peak_offset != variance_offset,
                "peak_variance_steady_phase_changed": (
                    peak_offset % message.cycle_time_us
                    != variance_offset % message.cycle_time_us
                ),
            }
        )
    with offsets_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(offset_rows[0]))
        writer.writeheader()
        writer.writerows(offset_rows)

    peak_stage = results[ObjectiveMode.PEAK].stage("gcls")
    balanced_stage = results[ObjectiveMode.BALANCED].stage("gcls")
    peak_stddev = load_statistics(peak_stage.steady_slot_loads)[2]
    balanced_stddev = load_statistics(balanced_stage.steady_slot_loads)[2]
    offset_change_count = sum(
        bool(row["peak_balanced_offset_changed"]) for row in offset_rows
    )
    phase_change_count = sum(
        bool(row["peak_balanced_steady_phase_changed"]) for row in offset_rows
    )
    variance_offset_change_count = sum(
        bool(row["peak_variance_offset_changed"]) for row in offset_rows
    )
    variance_phase_change_count = sum(
        bool(row["peak_variance_steady_phase_changed"]) for row in offset_rows
    )
    variance_stage = results[ObjectiveMode.VARIANCE].stage("gcls")
    variance_stddev = load_statistics(variance_stage.steady_slot_loads)[2]
    cross_evaluation = {
        "metric_system": WeightMode.FRAME_TIME_US.value,
        "input_hash": input_hash,
        "results": {str(row["result"]): row for row in rows},
        "balanced_vs_peak": {
            "steady_peak_change_us": (
                balanced_stage.objective.steady_peak - peak_stage.objective.steady_peak
            ),
            "Qss_improvement_rate": _rate(
                peak_stage.objective.sum_square_load,
                balanced_stage.objective.sum_square_load,
            ),
            "standard_deviation_improvement_rate": _rate(
                peak_stddev,
                balanced_stddev,
            ),
            "recommended_offset_difference_count": offset_change_count,
            "steady_phase_difference_count": phase_change_count,
        },
        "variance_vs_peak": {
            "steady_peak_change_us": (
                variance_stage.objective.steady_peak - peak_stage.objective.steady_peak
            ),
            "Qss_improvement_rate": _rate(
                peak_stage.objective.sum_square_load,
                variance_stage.objective.sum_square_load,
            ),
            "standard_deviation_improvement_rate": _rate(
                peak_stddev,
                variance_stddev,
            ),
            "recommended_offset_difference_count": variance_offset_change_count,
            "steady_phase_difference_count": variance_phase_change_count,
        },
    }

    summary: dict[str, Any] = {
        "semantics": (
            "peak is the strict peak GCLS reference (not a global optimum); balanced "
            "is the guarded recommendation; variance is an experimental physical objective"
        ),
        "recommended_mode": ObjectiveMode.BALANCED.value,
        "cross_evaluation": cross_evaluation,
        "modes": {},
    }
    for mode in expected:
        mode_summary = build_comparison_summary(network, configs[mode], results[mode])
        stage = results[mode].stage("gcls")
        steady_mean, steady_variance, steady_stddev = load_statistics(
            stage.steady_slot_loads
        )
        startup_mean, startup_variance, startup_stddev = load_statistics(
            stage.startup_slot_loads
        )
        mode_summary["load_statistics"] = {
            "steady": {
                "mean_us": steady_mean,
                "variance_us2": steady_variance,
                "standard_deviation_us": steady_stddev,
            },
            "startup": {
                "mean_us": startup_mean,
                "variance_us2": startup_variance,
                "standard_deviation_us": startup_stddev,
            },
        }
        summary["modes"][mode.value] = mode_summary
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return comparison_path, offsets_path, summary_path


def write_all_network_objective_report(dual_weight_root: Path) -> Path:
    """Aggregate unified objective-mode acceptance metrics for completed networks."""
    rows: list[dict[str, object]] = []
    for network_dir in sorted(
        (path for path in dual_weight_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        summary_path = network_dir / "results" / "objective_mode_summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        cross = summary.get("cross_evaluation")
        if not isinstance(cross, dict):
            continue
        values = cross["results"]
        delta = cross["balanced_vs_peak"]
        variance_delta = cross["variance_vs_peak"]
        row: dict[str, object] = {
            "网段": network_dir.name,
            "input_hash": cross["input_hash"],
            "seed": values["balanced"]["seed"],
            "strict_peak_gcls_reference_us": values["balanced"][
                "strict_peak_gcls_reference_us"
            ],
            "balanced_peak_budget_us": values["balanced"]["peak_budget_us"],
            **{f"balanced_vs_peak_{key}": value for key, value in delta.items()},
            **{
                f"variance_vs_peak_{key}": value
                for key, value in variance_delta.items()
            },
        }
        for label in ("original", "peak", "balanced", "variance"):
            for metric in (
                "Nvio",
                "Vvio_us",
                "Zss_us",
                "Qss_us2",
                "steady_variance_us2",
                "steady_standard_deviation_us",
                "Zst_us",
                "Qst_us2",
                "Kmax",
                "peak_budget_excess_us",
                "runtime_seconds",
            ):
                row[f"{label}_{metric}"] = values[label][metric]
        rows.append(row)
    if not rows:
        raise ValueError("no completed objective-mode reports were found")
    output = dual_weight_root / "ALL_network_objective_mode_summary.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output
