"""! @file joint_writer.py
@brief 联合优化结果的稳定、精确 JSON 审计输出。
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from ..models import OffsetAssignment
from ..optimization.joint import (
    JointOptimizationResult,
    JointSearchAttempt,
    JointSearchMetadata,
    JointSolution,
)
from ..optimization.main_function import MainFunctionSolveResult
from .restart_writer import objective_dict


def fraction_dict(value: Fraction) -> dict[str, int | float | str]:
    """! @brief 同时保留精确分子/分母与仅供展示的数值。"""
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "exact": f"{value.numerator}/{value.denominator}",
        "display_value": float(value),
    }


def _assignment_dict(item: OffsetAssignment) -> dict[str, int | str]:
    return {
        "message_name": item.message_name,
        "CAN_ID": item.can_id,
        "Offset_us": item.offset_us,
        "definition_index": item.definition_index,
    }


def _main_function_dict(result: MainFunctionSolveResult) -> dict[str, object]:
    return {
        "cpu_proxy": fraction_dict(result.cpu_proxy),
        "rho": fraction_dict(result.rho),
        "group_count": len(result.groups),
        "groups": [
            {
                "timebase_us": group.timebase_us,
                "group_proxy_cost": fraction_dict(group.group_proxy_cost),
                "d_types_us": list(group.d_types_us),
                "messages": [
                    {
                        "message_key": message.message_key,
                        "period_us": message.period_us,
                        "offset_us": message.offset_us,
                        "D_us": message.d_us,
                    }
                    for message in group.messages
                ],
            }
            for group in result.groups
        ],
    }


def _attempt_dict(attempt: JointSearchAttempt) -> dict[str, object]:
    return {
        "attempt_index": attempt.attempt_index,
        "attempt_kind": attempt.attempt_kind.value,
        "seed": attempt.seed,
        "assignment_hash": attempt.assignment_hash,
        "assignments": [_assignment_dict(item) for item in attempt.assignments],
        "metrics": {
            "Peak_us": attempt.peak,
            "Qss": attempt.qss,
            "CPU_proxy": fraction_dict(attempt.cpu_proxy),
        },
        "formal_can_objective": objective_dict(attempt.can_objective),
        "feasible": attempt.feasible,
        "evaluation_count": attempt.evaluation_count,
        "accepted_moves": attempt.accepted_moves,
        "elapsed_seconds": attempt.elapsed_seconds,
    }


def _metadata_dict(metadata: JointSearchMetadata) -> dict[str, object]:
    return {
        "stage": metadata.stage,
        "base_seed": metadata.base_seed,
        "objective": metadata.objective,
        "hard_constraints": list(metadata.hard_constraints),
        "actual_attempts": metadata.actual_attempts,
        "stop_reason": metadata.stop_reason,
        "elapsed_seconds": metadata.elapsed_seconds,
        "attempts": [_attempt_dict(item) for item in metadata.attempts],
    }


def joint_solution_dict(solution: JointSolution) -> dict[str, object]:
    """! @brief 序列化一个完整 Pareto/anchor 解及其 provenance。"""
    return {
        "source": solution.source,
        "assignment_hash": solution.assignment_hash,
        "assignments": [_assignment_dict(item) for item in solution.assignments],
        "metrics": {
            "Peak_us": solution.peak,
            "Qss": solution.qss,
            "CPU_proxy": fraction_dict(solution.cpu_proxy),
        },
        "formal_can_objective": objective_dict(solution.can_objective),
        "epsilon_budget": (
            fraction_dict(solution.epsilon_budget) if solution.epsilon_budget is not None else None
        ),
        "main_function": _main_function_dict(solution.main_function_result),
        "search": _metadata_dict(solution.search_metadata),
    }


def joint_result_dict(result: JointOptimizationResult) -> dict[str, object]:
    """! @brief 构造 schema versioned 联合优化审计对象。"""
    return {
        "schema_version": 1,
        "network": result.network_id,
        "status": result.status,
        "configuration": {
            "rho": fraction_dict(result.config.rho),
            "epsilon_points": result.config.epsilon_points,
        },
        "domain": {
            "decision_message_count": result.decision_message_count,
            "fixed_message_count": result.fixed_message_count,
            "fixed_rule": "cycle_time_us > offset_max_us => Offset_us = 0",
        },
        "peak_budget_us": result.peak_budget,
        "anchors": {
            "peak_reference": joint_solution_dict(result.peak_reference),
            "can_anchor": joint_solution_dict(result.can_anchor),
            "cpu_anchor": joint_solution_dict(result.cpu_anchor),
        },
        "epsilon_runs": [
            {
                "index": run.index,
                "budget": fraction_dict(run.budget),
                "status": run.status,
                "solution": joint_solution_dict(run.solution),
            }
            for run in result.epsilon_runs
        ],
        "pareto_solutions": [joint_solution_dict(solution) for solution in result.pareto_solutions],
        "performance": {
            "joint_evaluations": result.performance.joint_evaluations,
            "solver_calls": result.performance.solver_calls,
            "cache_hits": result.performance.cache_hits,
            "cache_misses": result.performance.cache_misses,
            "cache_hit_rate": result.performance.cache_hit_rate,
            "unique_d_histograms": result.performance.unique_d_histograms,
            "solver_seconds": result.performance.solver_seconds,
            "total_seconds": result.performance.total_seconds,
        },
    }


def write_joint_result(
    output_root: Path,
    result: JointOptimizationResult,
    report_prefix: str,
) -> Path:
    """! @brief 写入 ``results/<prefix>_joint_summary.json`` 并返回路径。"""
    output_path = output_root / "results" / f"{report_prefix}_joint_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            joint_result_dict(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path
