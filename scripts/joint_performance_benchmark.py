"""Reproducible lossless Joint performance and semantic benchmark."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from typing import Any

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))

from canfd_offset_optimizer.config import RestartPolicy
from canfd_offset_optimizer.final_experiment import (
    FinalExperimentInput,
    load_final_experiment_project,
)
from canfd_offset_optimizer.optimization.joint import (
    JointOptimizationConfig,
    JointOptimizationResult,
    JointSolution,
    optimize_can_cpu_balanced,
)
from canfd_offset_optimizer.optimization.main_function import clear_main_function_cache


NETWORKS = ("CH", "DA", "DK", "EP", "GL", "IC", "LC", "PT", "SU")
CHANNELS = {
    "CH": "CT_E0X_PT_CarFLZCU_VCU_CHMessagelis_7a0ed425",
    "DA": "CT_E0X_PT_CarFLZCU_VCU_DAMessagelis_75db032f",
    "DK": "CT_E0X_PT_CarFLZCU_VCU_DKMessagelis_97745bab",
    "EP": "CT_E0X_PT_CarFLZCU_VCU_EPMessagelis_8106544b",
    "GL": "CT_E0X_PT_CarFLZCU_VCU_GLMessagelis_c9d19cd8",
    "IC": "CT_E0X_PT_CarFLZCU_VCU_ICMessagelis_b318bb00",
    "LC": "CT_E0X_PT_CarFLZCU_VCU_LCMessagelis_2bbbcc10",
    "PT": "CT_E0X_PT_CarFLZCU_VCU_PTMessagelis_a564bd25",
    "SU": "CT_E0X_PT_CarFLZCU_VCU_SUMessagelis_1374b015",
}
DBC_DIR = _PROJECT / "input" / "dbc"
ARXML_DIR = _PROJECT / "input" / "arxml"
CONFIG_PATH = _PROJECT / "input" / "config" / "project.yaml"
ROUTING_PATH = _PROJECT / "input" / "网关路由配置表V02_V4.7_to_V4.8.xlsx"
OUTPUT_ROOT = _PROJECT / "output" / "diagnostics" / "joint_performance_optimization"


def _fraction(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return f"{value.numerator}/{value.denominator}"


def _dbc_for(network: str) -> Path:
    matches = tuple(DBC_DIR.glob(f"*_VCU_{network} Message*.dbc"))
    if len(matches) != 1:
        raise RuntimeError(f"{network}: expected exactly one DBC, found {len(matches)}")
    return matches[0]


def _load_network(network: str):
    return load_final_experiment_project(
        FinalExperimentInput(
            network_id=network,
            dbc_path=_dbc_for(network),
            selected_sender="FLZCU",
            protocol="CAN_FD",
            routing_excel_path=ROUTING_PATH,
            routing_target_network=f"{network}CAN",
            arxml_dir=ARXML_DIR,
            config_path=CONFIG_PATH,
            channel=CHANNELS[network],
        )
    )


def _solution_semantics(solution: JointSolution) -> dict[str, Any]:
    return {
        "source": solution.source,
        "refinement_pass": solution.refinement_pass,
        "origin_attempt": solution.origin_attempt,
        "assignment_hash": solution.assignment_hash,
        "peak": solution.peak,
        "qss": solution.qss,
        "cpu_proxy": _fraction(solution.cpu_proxy),
        "can_objective": list(solution.can_objective.as_tuple()),
        "epsilon_budget": _fraction(solution.epsilon_budget),
        "assignments": [
            {
                "definition_index": item.definition_index,
                "can_id": item.can_id,
                "message_name": item.message_name,
                "offset_us": item.offset_us,
            }
            for item in solution.assignments
        ],
        "main_function_groups": [
            {
                "timebase_us": group.timebase_us,
                "group_proxy_cost": _fraction(group.group_proxy_cost),
                "d_types_us": list(group.d_types_us),
                "messages": [
                    {
                        "message_key": message.message_key,
                        "period_us": message.period_us,
                        "offset_us": message.offset_us,
                        "d_us": message.d_us,
                    }
                    for message in group.messages
                ],
            }
            for group in solution.main_function_result.groups
        ],
        "search": {
            "stage": solution.search_metadata.stage,
            "base_seed": solution.search_metadata.base_seed,
            "objective": solution.search_metadata.objective,
            "hard_constraints": list(solution.search_metadata.hard_constraints),
            "actual_attempts": solution.search_metadata.actual_attempts,
            "stop_reason": solution.search_metadata.stop_reason,
            "attempts": [
                {
                    "attempt_index": attempt.attempt_index,
                    "attempt_kind": attempt.attempt_kind.value,
                    "seed": attempt.seed,
                    "assignment_hash": attempt.assignment_hash,
                    "peak": attempt.peak,
                    "qss": attempt.qss,
                    "cpu_proxy": _fraction(attempt.cpu_proxy),
                    "can_objective": list(attempt.can_objective.as_tuple()),
                    "feasible": attempt.feasible,
                    "accepted_moves": attempt.accepted_moves,
                }
                for attempt in solution.search_metadata.attempts
            ],
        },
    }


def _result_semantics(result: JointOptimizationResult) -> dict[str, Any]:
    assert result.refined_peak_reference is not None
    assert result.refined_can_endpoint is not None
    assert result.refined_cpu_endpoint is not None
    assert result.refinement is not None
    assert result.recommendation is not None
    return {
        "network": result.network_id,
        "config": {
            "rho": _fraction(result.config.rho),
            "epsilon_points": result.config.epsilon_points,
            "max_refinement_passes": result.config.max_refinement_passes,
            "endpoint_only": result.config.endpoint_only,
            "attempts": result.peak_reference.search_metadata.actual_attempts,
            "seed": result.peak_reference.search_metadata.base_seed,
        },
        "domain": {
            "decision": result.decision_message_count,
            "fixed": result.fixed_message_count,
        },
        "status": result.status,
        "initial_peak_budget": result.peak_budget,
        "refined_peak_budget": result.refined_peak_budget,
        "peak_reference": _solution_semantics(result.peak_reference),
        "can_anchor": _solution_semantics(result.can_anchor),
        "cpu_anchor": _solution_semantics(result.cpu_anchor),
        "refined_peak_reference": _solution_semantics(result.refined_peak_reference),
        "refined_can_endpoint": _solution_semantics(result.refined_can_endpoint),
        "refined_cpu_endpoint": _solution_semantics(result.refined_cpu_endpoint),
        "epsilon_runs": [
            {
                "index": run.index,
                "budget": _fraction(run.budget),
                "status": run.status,
                "solution": _solution_semantics(run.solution),
            }
            for run in result.epsilon_runs
        ],
        "pareto": [_solution_semantics(solution) for solution in result.pareto_solutions],
        "stage_solutions": [
            _solution_semantics(solution) for solution in result.stage_solutions
        ],
        "refinement": {
            "passes_run": result.refinement.passes_run,
            "max_passes": result.refinement.max_passes,
            "converged": result.refinement.converged,
            "termination_reason": result.refinement.termination_reason,
            "objective_front_stable": result.refinement.objective_front_stable,
            "assignment_front_stable": result.refinement.assignment_front_stable,
            "passes": [
                {
                    "pass_index": item.pass_index,
                    "peak_reference_hash": item.peak_reference_hash,
                    "peak_objective": list(item.peak_objective.as_tuple()),
                    "peak_budget": item.peak_budget,
                    "can_endpoint_hash": item.can_endpoint_hash,
                    "can_qss": item.can_qss,
                    "can_cpu_proxy": _fraction(item.can_cpu_proxy),
                    "cpu_endpoint_hash": item.cpu_endpoint_hash,
                    "cpu_qss": item.cpu_qss,
                    "cpu_cpu_proxy": _fraction(item.cpu_cpu_proxy),
                    "epsilon_budgets": [_fraction(value) for value in item.epsilon_budgets],
                    "epsilon_solution_hashes": list(item.epsilon_solution_hashes),
                    "pareto_hashes": list(item.pareto_hashes),
                    "pareto_objectives": [
                        [qss, _fraction(cpu)] for qss, cpu in item.pareto_objectives
                    ],
                    "archive_size": item.archive_size,
                    "peak_feasible_archive_size": item.peak_feasible_archive_size,
                    "signature": item.signature,
                }
                for item in result.refinement.passes
            ],
        },
        "recommendation": {
            "method": result.recommendation.method,
            "solution_hash": result.recommendation.solution_hash,
            "pareto_index": result.recommendation.pareto_index,
            "normalized_q": _fraction(result.recommendation.normalized_q),
            "normalized_cpu": _fraction(result.recommendation.normalized_cpu),
            "knee_score": _fraction(result.recommendation.knee_score),
        },
    }


def _performance(result: JointOptimizationResult, wall_seconds: float) -> dict[str, Any]:
    value = result.performance
    return {
        "joint_evaluations": value.joint_evaluations,
        "solver_calls": value.solver_calls,
        "cache_hits": value.cache_hits,
        "cache_misses": value.cache_misses,
        "cache_hit_rate": value.cache_hit_rate,
        "unique_d_histograms": value.unique_d_histograms,
        "solver_seconds": value.solver_seconds,
        "refinement_seconds": value.refinement_seconds,
        "epsilon_seconds": value.epsilon_seconds,
        "optimization_seconds": value.total_seconds,
        "wall_seconds_including_load": wall_seconds,
    }


def _git_head() -> str:
    return subprocess.check_output(
        ("git", "rev-parse", "HEAD"),
        cwd=_PROJECT,
        text=True,
        encoding="utf-8",
    ).strip()


def _run_network(network: str, output: Path, profile: bool) -> dict[str, Any]:
    wall_started = perf_counter()
    loaded = _load_network(network)
    optimization = replace(
        loaded.config.optimization,
        restart_policy=RestartPolicy.fixed(3, source_kind="cli"),
    )
    clear_main_function_cache()

    def operation() -> JointOptimizationResult:
        return optimize_can_cpu_balanced(
            network,
            loaded.network.messages,
            optimization,
            loaded.config.objective,
            average_load_limit=loaded.config.model.average_load_limit,
            weight_mode=loaded.network.weight_mode,
            seed=0,
            joint_config=JointOptimizationConfig(Fraction(1), 21, 3, False),
        )

    profiler = cProfile.Profile() if profile else None
    if profiler is None:
        result = operation()
    else:
        result = profiler.runcall(operation)
        profile_path = output / f"{network}.prof"
        profiler.dump_stats(profile_path)
        report = io.StringIO()
        stats = pstats.Stats(profiler, stream=report)
        report.write("\nTOP CUMULATIVE\n")
        stats.sort_stats("cumulative").print_stats(40)
        report.write("\nTOP OWN TIME\n")
        stats.sort_stats("time").print_stats(40)
        (output / f"{network}_profile.txt").write_text(
            report.getvalue(),
            encoding="utf-8",
        )
    wall_seconds = perf_counter() - wall_started
    payload = {
        "metadata": {
            "git_head": _git_head(),
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "network": network,
        },
        "performance": _performance(result, wall_seconds),
        "semantic": _result_semantics(result),
    }
    (output / f"{network}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{network}: {result.performance.total_seconds:.3f}s, "
        f"eval={result.performance.joint_evaluations}, "
        f"pareto={len(result.pareto_solutions)}"
    )
    return payload


def _compare(reference: Path, candidate: Path, networks: tuple[str, ...]) -> int:
    rows = []
    all_equal = True
    for network in networks:
        before = json.loads((reference / f"{network}.json").read_text(encoding="utf-8"))
        after = json.loads((candidate / f"{network}.json").read_text(encoding="utf-8"))
        equal = before["semantic"] == after["semantic"]
        all_equal = all_equal and equal
        before_seconds = float(before["performance"]["optimization_seconds"])
        after_seconds = float(after["performance"]["optimization_seconds"])
        rows.append(
            {
                "network": network,
                "before_seconds": before_seconds,
                "after_seconds": after_seconds,
                "speedup": before_seconds / after_seconds,
                "semantic_equal": equal,
                "before_performance": before["performance"],
                "after_performance": after["performance"],
            }
        )
    payload = {"all_semantic_equal": all_equal, "networks": rows}
    (candidate / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for row in rows:
        print(
            f"{row['network']}: {row['before_seconds']:.3f}s -> "
            f"{row['after_seconds']:.3f}s, {row['speedup']:.3f}x, "
            f"semantic_equal={row['semantic_equal']}"
        )
    return 0 if all_equal else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", help="output label such as baseline or optimized")
    parser.add_argument("--networks", default=",".join(NETWORKS))
    parser.add_argument("--profile-network", choices=NETWORKS)
    parser.add_argument("--compare-to")
    args = parser.parse_args()
    networks = tuple(item.strip() for item in args.networks.split(",") if item.strip())
    if not networks or any(network not in NETWORKS for network in networks):
        raise ValueError("--networks must be a non-empty subset of the locked nine networks")
    output = OUTPUT_ROOT / args.label
    output.mkdir(parents=True, exist_ok=True)
    for network in networks:
        _run_network(network, output, network == args.profile_network)
    if args.compare_to:
        return _compare(OUTPUT_ROOT / args.compare_to, output, networks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
