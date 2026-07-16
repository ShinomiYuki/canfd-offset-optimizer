"""Four-way ablation for Peak-pool size and conflict-directed 3-opt."""

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
from ..reporting.summary_writer import (
    combined_input_hash,
    triple_search_audit_dict,
)


ABLATION_VARIANTS = (
    ("A", 1, False),
    ("B", 4, False),
    ("C", 1, True),
    ("D", 4, True),
)


def run_triple_ablation(
    loaded: LoadedProject,
    output: Path,
    network_prefix: str,
    *,
    seed: int = 0,
    total_attempts: int | None = None,
) -> dict[str, object]:
    """Run A/B/C/D against one identical strict Peak reference."""
    if loaded.network.weight_mode.value != "frame_time_us":
        raise ValueError("3-opt ablation requires frame_time_us")
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
        conflict_triple_enabled=False,
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
    for label, pool_size, enabled in ABLATION_VARIANTS:
        optimization = replace(
            base_optimization,
            peak_candidate_pool_size=pool_size,
            conflict_triple_enabled=enabled,
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
        triple_audits = [
            record.triple_search_audit
            for record in result.balanced_candidate_searches
            if record.triple_search_audit is not None
        ]
        rows.append(
            {
                "消融组": label,
                "Peak候选池大小": pool_size,
                "3-opt启用": enabled,
                "实际候选数": len(result.selected_peak_candidates),
                "峰值预算(μs)": result.peak_budget_us,
                "Nvio": result.objective.violation_count,
                "Vvio": result.objective.violation_excess,
                "Zss(μs)": result.objective.steady_peak,
                "Qss(μs²)": result.objective.sum_square_load,
                "相对A组Qss改善率": (
                    (baseline_qss - result.objective.sum_square_load) / baseline_qss
                    if baseline_qss
                    else 0.0
                ),
                "Zst(μs)": result.objective.startup_peak,
                "Qst(μs²)": result.objective.startup_sum_square_load,
                "Kmax": result.objective.max_release_count,
                "检查三元组数": sum(item.checked_triplets for item in triple_audits),
                "检查Offset组合数": sum(
                    item.checked_offset_combinations for item in triple_audits
                ),
                "接受3-opt次数": sum(item.accepted_moves for item in triple_audits),
                "3-opt耗时(s)": sum(item.elapsed_seconds for item in triple_audits),
                "Balanced总耗时(s)": (
                    result.elapsed_seconds - result.peak_reference_elapsed_seconds
                ),
                "最终assignment_hash": result.assignment_hash,
            }
        )
        candidate_runs: list[dict[str, object]] = []
        for candidate, search in zip(
            result.selected_peak_candidates,
            result.balanced_candidate_searches,
            strict=True,
        ):
            candidate_run: dict[str, object] = {
                "pool_index": search.pool_index,
                "source_peak_attempt": candidate.source_attempt_index,
                "source_seed": candidate.source_seed,
                "candidate_assignment_hash": candidate.assignment_hash,
                "candidate_steady_phase_hash": candidate.steady_phase_hash,
                "objective_before": list(search.objective_before.as_tuple()),
                "objective_after": list(search.objective_after.as_tuple()),
                "strictly_improved": search.strictly_improved,
                "result_assignment_hash": search.result_assignment_hash,
                "runtime_seconds": search.elapsed_seconds,
                "triple_search": triple_search_audit_dict(
                    search.triple_search_audit
                ),
            }
            candidate_runs.append(candidate_run)
            audit_rows.append(
                {
                    "schema_version": 1,
                    "network": network_prefix,
                    "ablation_group": label,
                    "pool_size": pool_size,
                    "triple_enabled": enabled,
                    "peak_budget_us": result.peak_budget_us,
                    "peak_guardrail": [
                        peak.objective.violation_count,
                        peak.objective.violation_excess,
                    ],
                    **candidate_run,
                }
            )
        runs.append(
            {
                "group": label,
                "pool_size": pool_size,
                "triple_enabled": enabled,
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
                "candidate_searches": candidate_runs,
            }
        )

    results_dir = output / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with (results_dir / "triple_ablation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (results_dir / "triple_ablation_audit.jsonl").open(
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
        "variants": runs,
        "method_boundary": (
            "only conflict-directed three-message relocation is ablated; objective, "
            "Peak GCLS, 1-opt, Pair Search, and Peak-pool selection are unchanged"
        ),
    }
    (results_dir / "triple_ablation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
