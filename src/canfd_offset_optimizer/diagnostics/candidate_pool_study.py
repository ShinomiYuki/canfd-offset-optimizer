"""Peak-candidate-pool ablation for multi-start Balanced search."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

from ..config import ObjectiveConfig, RestartPolicy
from ..models import ObjectiveMode
from ..optimization.gcls import run_gcls
from ..parsers.project_loader import LoadedProject
from ..reporting.restart_writer import configuration_hash
from ..reporting.summary_writer import combined_input_hash


DEFAULT_POOL_SIZES = (1, 4, 8, 16, 32)


def run_candidate_pool_study(
    loaded: LoadedProject,
    output: Path,
    network_prefix: str,
    *,
    seed: int = 0,
    total_attempts: int | None = None,
    pool_sizes: tuple[int, ...] = DEFAULT_POOL_SIZES,
) -> dict[str, object]:
    """Run one shared Peak reference and a fixed Balanced candidate-pool grid."""
    if loaded.network.weight_mode.value != "frame_time_us":
        raise ValueError("candidate-pool studies require frame_time_us")
    if tuple(sorted(set(pool_sizes))) != pool_sizes or any(
        size not in DEFAULT_POOL_SIZES for size in pool_sizes
    ):
        raise ValueError("pool sizes must be unique, increasing, and drawn from 1,4,8,16,32")
    if total_attempts is not None and total_attempts <= 0:
        raise ValueError("total_attempts must be positive")
    restart_policy = (
        RestartPolicy.fixed(total_attempts)
        if total_attempts is not None
        else loaded.config.optimization.restart_policy
    )
    base_optimization = replace(
        loaded.config.optimization,
        restart_policy=restart_policy,
        peak_candidate_pool_size=1,
    )
    peak = run_gcls(
        loaded.network.messages,
        loaded.slot_map,
        base_optimization,
        loaded.config.model.average_load_limit,
        seed,
        loaded.network.weight_mode,
        ObjectiveConfig(mode=ObjectiveMode.PEAK),
    )
    balanced_objective = replace(loaded.config.objective, mode=ObjectiveMode.BALANCED)
    rows: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    baseline_qss: int | None = None
    for pool_size in pool_sizes:
        optimization = replace(
            base_optimization,
            peak_candidate_pool_size=pool_size,
        )
        result = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            optimization,
            loaded.config.model.average_load_limit,
            seed,
            loaded.network.weight_mode,
            balanced_objective,
            peak,
        )
        if baseline_qss is None:
            baseline_qss = result.objective.sum_square_load
        qss_improvement = (
            (baseline_qss - result.objective.sum_square_load) / baseline_qss
            if baseline_qss
            else 0.0
        )
        rows.append(
            {
                "候选池请求大小": pool_size,
                "实际候选数": len(result.selected_peak_candidates),
                "Peak候选归档数": len(peak.peak_candidate_archive),
                "峰值预算(μs)": result.peak_budget_us,
                "Nvio": result.objective.violation_count,
                "Vvio": result.objective.violation_excess,
                "Zss(μs)": result.objective.steady_peak,
                "Qss(μs²)": result.objective.sum_square_load,
                "相对pool_size_1_Qss改善率": qss_improvement,
                "Zst(μs)": result.objective.startup_peak,
                "Qst(μs²)": result.objective.startup_sum_square_load,
                "Kmax": result.objective.max_release_count,
                "局部搜索评价次数": sum(
                    record.evaluation_count
                    for record in result.balanced_candidate_searches
                ),
                "接受移动次数": sum(
                    record.accepted_moves
                    for record in result.balanced_candidate_searches
                ),
                "Balanced运行时间(s)": result.elapsed_seconds
                - result.peak_reference_elapsed_seconds,
                "最终assignment_hash": result.assignment_hash,
            }
        )
        selected_payload: list[dict[str, object]] = []
        for candidate, search in zip(
            result.selected_peak_candidates,
            result.balanced_candidate_searches,
            strict=True,
        ):
            candidate_payload: dict[str, object] = {
                "pool_index": search.pool_index,
                "peak_budget_us": result.peak_budget_us,
                "peak_guardrail": [
                    peak.objective.violation_count,
                    peak.objective.violation_excess,
                ],
                "source_peak_attempt": candidate.source_attempt_index,
                "source_seed": candidate.source_seed,
                "candidate_assignment_hash": candidate.assignment_hash,
                "candidate_steady_phase_hash": candidate.steady_phase_hash,
                "peak_objective": list(candidate.objective.as_tuple()),
                "balanced_objective_before": list(search.objective_before.as_tuple()),
                "balanced_objective_after": list(search.objective_after.as_tuple()),
                "strictly_improved": search.strictly_improved,
                "runtime_seconds": search.elapsed_seconds,
                "evaluation_count": search.evaluation_count,
                "accepted_moves": search.accepted_moves,
                "result_assignment_hash": search.result_assignment_hash,
                "candidate_assignments": [
                    {
                        "message_name": item.message_name,
                        "CAN_ID": item.can_id,
                        "Offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in candidate.assignments
                ],
                "result_assignments": [
                    {
                        "message_name": item.message_name,
                        "CAN_ID": item.can_id,
                        "Offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in search.result_assignments
                ],
            }
            selected_payload.append(candidate_payload)
            audit_rows.append(
                {
                    "schema_version": 1,
                    "network": network_prefix,
                    "pool_size": pool_size,
                    **candidate_payload,
                }
            )
        runs.append(
            {
                "requested_pool_size": pool_size,
                "actual_pool_size": len(result.selected_peak_candidates),
                "objective": list(result.objective.as_tuple()),
                "assignment_hash": result.assignment_hash,
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "CAN_ID": item.can_id,
                        "Offset_us": item.offset_us,
                    }
                    for item in result.assignments
                ],
                "selected_candidates": selected_payload,
            }
        )

    results_dir = output / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / "candidate_pool_comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (results_dir / "candidate_pool_audit.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for row in audit_rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    payload = {
        "schema_version": 1,
        "input_hash": combined_input_hash(loaded.network.input_files),
        "configuration_hash": configuration_hash(
            replace(loaded.config, optimization=base_optimization)
        ),
        "network": network_prefix,
        "seed": seed,
        "peak_actual_attempts": peak.restart_execution.actual_attempts,
        "peak_candidate_archive_size": len(peak.peak_candidate_archive),
        "strict_peak_reference": {
            "objective": list(peak.objective.as_tuple()),
            "assignment_hash": peak.assignment_hash,
        },
        "pool_sizes": list(pool_sizes),
        "runs": runs,
        "method_boundary": (
            "each selected Peak candidate receives exactly one unchanged Balanced "
            "1-opt plus Pair Search; no per-candidate random restart is added"
        ),
    }
    (results_dir / "candidate_pool_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
