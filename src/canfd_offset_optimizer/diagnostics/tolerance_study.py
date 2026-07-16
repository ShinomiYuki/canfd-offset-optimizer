"""Balanced relative peak-tolerance scan."""

from __future__ import annotations

import csv
import importlib
import json
import os
from dataclasses import replace
from math import sqrt
from pathlib import Path
from typing import cast

from ..config import ObjectiveConfig, PeakToleranceConfig, RestartPolicy
from ..models import ObjectiveMode, PeakToleranceType
from ..optimization.gcls import run_gcls
from ..parsers.project_loader import LoadedProject
from ..reporting.summary_writer import combined_input_hash
from ..reporting.restart_writer import configuration_hash


DEFAULT_TOLERANCES = (0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20)


def _stddev(loads: tuple[int, ...]) -> float:
    mean = sum(loads) / len(loads)
    return sqrt(sum((load - mean) ** 2 for load in loads) / len(loads))


def run_tolerance_scan(
    loaded: LoadedProject,
    output: Path,
    network_prefix: str,
    *,
    seed: int = 0,
    total_attempts: int | None = None,
    tolerances: tuple[float, ...] = DEFAULT_TOLERANCES,
) -> dict[str, object]:
    """Reuse one strict Peak reference across a fixed relative tolerance grid."""
    if loaded.network.weight_mode.value != "frame_time_us":
        raise ValueError("tolerance scans require frame_time_us")
    if tuple(sorted(set(tolerances))) != tolerances or any(
        value < 0 or value > 1 for value in tolerances
    ):
        raise ValueError("tolerances must be unique, increasing, and in [0, 1]")
    if total_attempts is not None and total_attempts <= 0:
        raise ValueError("total_attempts must be positive")
    restart_policy = (
        RestartPolicy.fixed(total_attempts)
        if total_attempts is not None
        else loaded.config.optimization.restart_policy
    )
    config = replace(
        loaded.config.optimization,
        restart_policy=restart_policy,
    )
    peak = run_gcls(
        loaded.network.messages,
        loaded.slot_map,
        config,
        loaded.config.model.average_load_limit,
        seed,
        loaded.network.weight_mode,
        ObjectiveConfig(mode=ObjectiveMode.PEAK),
    )
    peak_offsets = peak.offset_by_name()
    rows: list[dict[str, object]] = []
    assignments: list[dict[str, object]] = []
    for tolerance in tolerances:
        objective = ObjectiveConfig(
            mode=ObjectiveMode.BALANCED,
            peak_tolerance=PeakToleranceConfig(
                PeakToleranceType.RELATIVE, tolerance
            ),
        )
        result = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            config,
            loaded.config.model.average_load_limit,
            seed,
            loaded.network.weight_mode,
            objective,
            peak,
        )
        offsets = result.offset_by_name()
        offset_difference = sum(
            offsets[message.name] != peak_offsets[message.name]
            for message in result.messages
        )
        phase_difference = sum(
            offsets[message.name] % message.cycle_time_us
            != peak_offsets[message.name] % message.cycle_time_us
            for message in result.messages
        )
        value = result.objective
        rows.append(
            {
                "容差(%)": tolerance * 100,
                "峰值预算(μs)": result.peak_budget_us,
                "Nvio": value.violation_count,
                "Vvio": value.violation_excess,
                "Zss(μs)": value.steady_peak,
                "Qss(μs²)": value.sum_square_load,
                "稳态标准差(μs)": _stddev(result.steady_slot_loads),
                "Zst(μs)": value.startup_peak,
                "Qst(μs²)": value.startup_sum_square_load,
                "Kmax": value.max_release_count,
                "相对Peak_Offset差异数": offset_difference,
                "相对Peak_steady_phase差异数": phase_difference,
                "实际attempts": result.restart_execution.actual_attempts,
                "fallback原因": result.balanced_fallback_reason,
            }
        )
        assignments.append(
            {
                "tolerance": tolerance,
                "peak_budget_us": result.peak_budget_us,
                "objective": list(value.as_tuple()),
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "CAN_ID": item.can_id,
                        "Offset_us": item.offset_us,
                    }
                    for item in result.assignments
                ],
            }
        )
    results_dir = output / "results"
    plots_dir = output / "plots"
    results_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / "tolerance_scan.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema_version": 1,
        "input_hash": combined_input_hash(loaded.network.input_files),
        "configuration_hash": configuration_hash(loaded.config),
        "network": network_prefix,
        "seed": seed,
        "requested_restart_policy": restart_policy.mode.value,
        "actual_attempts": peak.restart_execution.actual_attempts,
        "strict_peak_reference": {
            "objective": list(peak.objective.as_tuple()),
            "assignments": [
                {
                    "message_name": item.message_name,
                    "CAN_ID": item.can_id,
                    "Offset_us": item.offset_us,
                }
                for item in peak.assignments
            ],
        },
        "tolerances": assignments,
        "interpretation_boundary": (
            "no improvement means only that the configured GCLS search did not find "
            "a better budget-feasible assignment; it does not prove infeasibility"
        ),
    }
    (results_dir / "tolerance_assignments.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    x = [cast(float, row["容差(%)"]) for row in rows]
    z = [cast(int, row["Zss(μs)"]) for row in rows]
    q = [cast(int, row["Qss(μs²)"]) for row in rows]
    cache_dir = output / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg", force=True)
    plt = importlib.import_module("matplotlib.pyplot")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].plot(x, z, marker="o", label="Zss")
    axes[0].set_xlabel("Relative peak tolerance (%)")
    axes[0].set_ylabel("Zss (μs)")
    axes[0].grid(alpha=0.3)
    axes[1].plot(x, q, marker="o", label="Qss", color="tab:orange")
    axes[1].set_xlabel("Relative peak tolerance (%)")
    axes[1].set_ylabel("Qss (μs²)")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(plots_dir / f"{network_prefix}_tolerance_scan.png", dpi=160)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(7, 5))
    axis.plot(z, q, marker="o")
    for tolerance, z_value, q_value in zip(x, z, q, strict=True):
        axis.annotate(f"{tolerance:g}%", (z_value, q_value))
    axis.set_xlabel("Zss (μs)")
    axis.set_ylabel("Qss (μs²)")
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(plots_dir / f"{network_prefix}_tolerance_pareto.png", dpi=160)
    plt.close(fig)
    return payload
