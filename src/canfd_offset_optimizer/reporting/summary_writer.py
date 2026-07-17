"""! @file summary_writer.py
@brief 生成包含输入哈希、来源、配置、种子与指标的 summary.json。

@author 篠見由紀
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ..config import ProjectConfig
from ..models import (
    NetworkModel,
    ObjectiveValue,
    OptimizationResult,
    TripleSearchAudit,
    WeightMode,
)
from ..optimization.objective import slot_load_threshold_us
from .filenames import infer_report_prefix
from .restart_writer import configuration_hash


def triple_search_audit_dict(audit: TripleSearchAudit | None) -> dict[str, object] | None:
    """Serialize an optional conflict-directed 3-opt audit without re-evaluation."""
    if audit is None:
        return None
    return {
        "candidate_cap": audit.candidate_cap,
        "hot_slot_count": audit.hot_slot_count,
        "max_rounds": audit.max_rounds,
        "checked_triplets": audit.checked_triplets,
        "checked_offset_combinations": audit.checked_offset_combinations,
        "accepted_moves": audit.accepted_moves,
        "runtime_seconds": audit.elapsed_seconds,
        "stop_reason": audit.stop_reason,
        "timing_semantics": (
            "enumeration_seconds is inclusive; contribution precompute, candidate "
            "selection, cleanup, and total are wall-clock stages; state mutation and "
            "objective evaluation are measured sub-stages and must not be summed with "
            "enumeration_seconds"
        ),
        "timings": (
            {
                "contribution_precompute_seconds": (
                    audit.timings.contribution_precompute_seconds
                ),
                "candidate_selection_seconds": (
                    audit.timings.candidate_selection_seconds
                ),
                "enumeration_seconds": audit.timings.enumeration_seconds,
                "state_mutation_rollback_seconds": (
                    audit.timings.state_mutation_rollback_seconds
                ),
                "objective_evaluation_seconds": (
                    audit.timings.objective_evaluation_seconds
                ),
                "cleanup_seconds": audit.timings.cleanup_seconds,
                "total_seconds": audit.timings.total_seconds,
            }
            if audit.timings is not None
            else None
        ),
        "rounds": [
            {
                "round_index": item.round_index,
                "message_names": list(item.message_names),
                "CAN_IDs": list(item.can_ids),
                "old_offsets_us": list(item.old_offsets_us),
                "new_offsets_us": list(item.new_offsets_us),
                "objective_before": list(item.objective_before.as_tuple()),
                "objective_after_move": list(item.objective_after_move.as_tuple()),
                "objective_after_cleanup": list(
                    item.objective_after_cleanup.as_tuple()
                ),
                "checked_triplets": item.checked_triplets,
                "checked_offset_combinations": item.checked_offset_combinations,
                "cleanup_evaluations": item.cleanup_evaluations,
                "cleanup_accepted_moves": item.cleanup_accepted_moves,
                "runtime_seconds": item.elapsed_seconds,
            }
            for item in audit.rounds
        ],
    }


def sha256_file(path: Path) -> str:
    """! @brief 流式计算输入文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_input_hash(paths: tuple[Path, ...]) -> str:
    """Hash stable file names and content digests into one location-independent ID."""
    digest = hashlib.sha256()
    inputs = sorted(
        (
            (path.name, sha256_file(path))
            for path in paths
            if path.is_file()
        )
    )
    for name, file_hash in inputs:
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(bytes.fromhex(file_hash))
    return digest.hexdigest()


def build_summary(
    network: NetworkModel,
    config: ProjectConfig,
    result: OptimizationResult,
) -> dict[str, object]:
    """! @brief 从不可变模型和结果构造标准 JSON 可序列化摘要。"""
    inputs = [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in network.input_files
        if path.is_file()
    ]
    physical_time_weight = network.weight_mode is WeightMode.FRAME_TIME_US

    def objective(value: ObjectiveValue) -> dict[str, int]:
        return {
            "violation_count": value.violation_count,
            "violation_excess": value.violation_excess,
            "steady_peak": value.steady_peak,
            "startup_peak": value.startup_peak,
            "sum_square_load": value.sum_square_load,
            "startup_sum_square_load": value.startup_sum_square_load,
            "max_release_count": value.max_release_count,
            "peak_budget_excess": value.peak_budget_excess,
        }

    return {
        "input_hash": combined_input_hash(network.input_files),
        "configuration_hash": configuration_hash(config),
        "input_files": inputs,
        "field_sources": dict(network.field_sources),
        "cli_overrides": dict(network.cli_overrides),
        "effective_configuration": {
            "weight_mode": config.model.weight_mode.value,
            "objective_mode": config.objective.mode.value,
            "random_restarts": (
                config.optimization.restart_policy.legacy_additional_restarts
            ),
            "restart_policy": {
                "mode": config.optimization.restart_policy.mode.value,
                "total_attempts": config.optimization.restart_policy.total_attempts,
                "min_attempts": config.optimization.restart_policy.min_attempts,
                "check_interval": config.optimization.restart_policy.check_interval,
                "patience_attempts": config.optimization.restart_policy.patience_attempts,
                "max_attempts": config.optimization.restart_policy.max_attempts,
                "source_kind": config.optimization.restart_policy.source_kind,
                "legacy_additional_restarts": (
                    config.optimization.restart_policy.legacy_additional_restarts
                ),
            },
            "peak_tolerance_type": config.objective.peak_tolerance.type.value,
            "peak_tolerance_value": config.objective.peak_tolerance.value,
            "variance_offset_cap": config.optimization.variance_offset_cap,
            "peak_candidate_pool_size": (
                config.optimization.peak_candidate_pool_size
            ),
            "conflict_triple_enabled": config.optimization.conflict_triple_enabled,
            "triple_candidate_cap": config.optimization.triple_candidate_cap,
            "triple_hot_slot_count": config.optimization.triple_hot_slot_count,
            "triple_max_rounds": config.optimization.triple_max_rounds,
        },
        "yaml_overrides": {
            key: value
            for key, value in asdict(config.network).items()
            if value is not None
        },
        "network": {
            "channel": network.channel.name,
            "nominal_bitrate": network.channel.nominal_bitrate,
            "data_bitrate": network.channel.data_bitrate,
            "brs": network.channel.brs,
            "hyperperiod_us": network.hyperperiod_us,
            "slot_width_us": network.steady_window.slot_width_us,
            "startup_window": {
                "start_us": network.startup_window.start_us,
                "end_us": network.startup_window.end_us,
                "interval": "[start, end)",
            },
            "steady_window": {
                "start_us": network.steady_window.start_us,
                "end_us": network.steady_window.end_us,
                "interval": "[start, end)",
            },
        },
        "algorithm": {
            "name": "GCLS",
            "seed": (
                result.restart_records[0].seed if result.restart_records else None
            ),
            "seed_count": len(result.restart_records),
            "restart_mode": result.restart_execution.mode.value,
            "restart_actual_attempts": result.restart_execution.actual_attempts,
            "restart_stop_reason": result.restart_execution.stop_reason,
            "restart_max_attempts_reached": (
                result.restart_execution.max_attempts_reached
            ),
            "hot_slot_count": config.optimization.hot_slot_count,
            "conflict_candidate_cap": config.optimization.conflict_candidate_cap,
            "pair_neighbor_steps": config.optimization.pair_neighbor_steps,
            "variance_offset_cap": config.optimization.variance_offset_cap,
            "objective_mode": result.objective.mode.value,
            "peak_tolerance": {
                "type": config.objective.peak_tolerance.type.value,
                "value": config.objective.peak_tolerance.value,
            },
            "variance_metric": config.objective.variance_metric,
            "evaluation_count": result.evaluation_count,
            "accepted_moves": result.accepted_moves,
            "peak_reference_evaluation_count": (
                result.peak_reference_evaluation_count
            ),
            "peak_reference_runtime_seconds": (
                result.peak_reference_elapsed_seconds
            ),
            "balanced_fallback_reason": result.balanced_fallback_reason,
            "peak_candidate_archive_size": len(result.peak_candidate_archive),
            "selected_peak_candidate_count": len(result.selected_peak_candidates),
        },
        "average_load": network.average_load if physical_time_weight else None,
        "average_weight_rate": network.average_load,
        "average_load_limit": (
            config.model.average_load_limit if physical_time_weight else None
        ),
        "average_load_constraint_applicable": physical_time_weight,
        "slot_load_threshold_us": (
            slot_load_threshold_us(
                network.steady_window.slot_width_us,
                config.model.average_load_limit,
            )
            if physical_time_weight
            else None
        ),
        "baseline_policy": "legal original Offset, otherwise minimum allowed Offset",
        "objective_before": result.initial_objective.as_tuple(),
        "objective_first_greedy": result.greedy_objective.as_tuple(),
        "objective_after": result.objective.as_tuple(),
        "objectives": {
            "before": objective(result.initial_objective),
            "first_greedy": objective(result.greedy_objective),
            "after": objective(result.objective),
            "lexicographic_order": list(result.objective.priorities),
            "objective_mode": result.objective.mode.value,
            "peak_budget_us": result.peak_budget_us,
            "peak_reference": (
                objective(result.peak_reference_objective)
                if result.peak_reference_objective
                else None
            ),
        },
        "restarts": [
            {
                "attempt_index": record.attempt_index,
                "attempt_kind": record.attempt_kind.value,
                "seed": record.seed,
                "objective": record.objective.as_tuple(),
                "assignment_hash": record.assignment_hash,
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "can_id": item.can_id,
                        "offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in record.assignments
                ],
                "runtime_seconds": record.elapsed_seconds,
                "evaluation_count": record.evaluation_count,
                "accepted_moves": record.accepted_moves,
            }
            for record in result.restart_records
        ],
        "peak_reference_restarts": [
            {"seed": record.seed, "objective": record.objective.as_tuple()}
            for record in result.peak_reference_restart_records
        ],
        "peak_candidate_archive": [
            {
                "source_attempt_index": candidate.source_attempt_index,
                "source_seed": candidate.source_seed,
                "peak_objective": candidate.objective.as_tuple(),
                "assignment_hash": candidate.assignment_hash,
                "steady_phase_hash": candidate.steady_phase_hash,
                "steady_phases": list(candidate.steady_phases),
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "can_id": item.can_id,
                        "offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in candidate.assignments
                ],
            }
            for candidate in result.peak_candidate_archive
        ],
        "selected_peak_candidates": [
            {
                "pool_index": index,
                "source_attempt_index": candidate.source_attempt_index,
                "source_seed": candidate.source_seed,
                "peak_objective": candidate.objective.as_tuple(),
                "assignment_hash": candidate.assignment_hash,
                "steady_phase_hash": candidate.steady_phase_hash,
                "steady_phases": list(candidate.steady_phases),
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "can_id": item.can_id,
                        "offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in candidate.assignments
                ],
            }
            for index, candidate in enumerate(result.selected_peak_candidates)
        ],
        "balanced_candidate_searches": [
            {
                "pool_index": record.pool_index,
                "source_attempt_index": record.source_attempt_index,
                "source_seed": record.source_seed,
                "candidate_assignment_hash": record.candidate_assignment_hash,
                "candidate_steady_phase_hash": record.candidate_steady_phase_hash,
                "objective_before": record.objective_before.as_tuple(),
                "objective_after": record.objective_after.as_tuple(),
                "strictly_improved": record.strictly_improved,
                "result_assignment_hash": record.result_assignment_hash,
                "runtime_seconds": record.elapsed_seconds,
                "evaluation_count": record.evaluation_count,
                "accepted_moves": record.accepted_moves,
                "triple_search": triple_search_audit_dict(
                    record.triple_search_audit
                ),
            }
            for record in result.balanced_candidate_searches
        ],
        "runtime_seconds": result.elapsed_seconds,
        "warnings": list(network.warnings),
        "weight_mode": network.weight_mode.value,
        "weight_accuracy": (
            "conservative_iso_can_fd_estimate_with_intermission"
            if physical_time_weight
            else "explicit_approximation"
        ),
        "objective_load_unit": "microseconds" if physical_time_weight else "weight_units",
    }


def write_summary(
    output_root: Path,
    network: NetworkModel,
    config: ProjectConfig,
    result: OptimizationResult,
    report_prefix: str | None = None,
) -> Path:
    """! @brief 将运行摘要写入 `results/summary.json`。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "summary.json"
    prefix = report_prefix or infer_report_prefix(
        network.input_files[0] if network.input_files else Path("network.dbc"),
        output_root.name,
    )
    payload = build_summary(network, config, result)
    payload["restart_audit_files"] = {
        "gcls": f"{prefix}_restart_records.jsonl",
        "peak_reference": (
            f"{prefix}_peak_reference_restart_records.jsonl"
            if result.peak_reference_restart_records
            else None
        ),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
