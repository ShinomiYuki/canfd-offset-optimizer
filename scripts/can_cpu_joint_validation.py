"""! @file can_cpu_joint_validation.py
@brief CAN/CPU joint 第三阶段受控、可恢复真实网段实验。

@details
严格拆分 endpoint saturation、refined baseline、seed、epsilon resolution 和 rho
sensitivity，避免无计划 Cartesian product。每个 run 前清空 MainFunction LRU，
condensed JSON 保留比较所需 exact objectives；baseline 另写完整 joint JSON。
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from time import perf_counter

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))

from canfd_offset_optimizer.config import RestartPolicy
from canfd_offset_optimizer.models import WeightMode
from canfd_offset_optimizer.optimization.joint import (
    JointOptimizationConfig,
    JointOptimizationResult,
    JointSolution,
    optimize_can_cpu_balanced,
)
from canfd_offset_optimizer.optimization.main_function import (
    clear_main_function_cache,
)
from canfd_offset_optimizer.parsers.project_loader import load_project
from canfd_offset_optimizer.reporting.joint_writer import (
    fraction_dict,
    write_joint_result,
)


NETWORKS = ("DK", "GL", "IC")
CHANNELS = {
    "DK": "CT_E0X_PT_CarFLZCU_VCU_DKMessagelis_97745bab",
    "GL": "CT_E0X_PT_CarFLZCU_VCU_GLMessagelis_c9d19cd8",
    "IC": "CT_E0X_PT_CarFLZCU_VCU_ICMessagelis_b318bb00",
}
DBC_DIR = _PROJECT / "input" / "dbc"
ARXML_DIR = _PROJECT / "input" / "arxml"
CONFIG_PATH = _PROJECT / "input" / "config" / "project.yaml"
OUTPUT_ROOT = _PROJECT / "output" / "diagnostics" / "can_cpu_joint_validation"


def _dbc_for(network: str) -> Path:
    matches = tuple(DBC_DIR.glob(f"*_VCU_{network} Message*.dbc"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one DBC for {network}, found {len(matches)}")
    return matches[0]


def _solution_summary(solution: JointSolution) -> dict[str, object]:
    return {
        "source": solution.source,
        "assignment_hash": solution.assignment_hash,
        "Peak": solution.peak,
        "Qss": solution.qss,
        "CPU_proxy": fraction_dict(solution.cpu_proxy),
        "main_function_count": solution.main_function_count,
        "timebases_us": sorted(group.timebase_us for group in solution.main_function_result.groups),
    }


def _result_summary(
    result: JointOptimizationResult,
    *,
    phase: str,
    attempts: int,
    seed: int,
    wall_seconds: float,
) -> dict[str, object]:
    assert result.refined_peak_reference is not None
    assert result.refined_can_endpoint is not None
    assert result.refined_cpu_endpoint is not None
    assert result.refinement is not None
    assert result.recommendation is not None
    recommended = (
        next(
            item
            for item in result.pareto_solutions
            if item.assignment_hash == result.recommendation.solution_hash
        )
        if result.recommendation.solution_hash is not None
        else None
    )
    return {
        "schema_version": 1,
        "phase": phase,
        "network": result.network_id,
        "attempts": attempts,
        "seed": seed,
        "rho": fraction_dict(result.config.rho),
        "epsilon_points": result.config.epsilon_points,
        "max_refinement_passes": result.config.max_refinement_passes,
        "endpoint_only": result.config.endpoint_only,
        "domain": {
            "eligible": result.decision_message_count + result.fixed_message_count,
            "decision": result.decision_message_count,
            "fixed": result.fixed_message_count,
        },
        "initial_peak_reference": _solution_summary(result.peak_reference),
        "initial_peak_budget": result.peak_budget,
        "initial_can_anchor": _solution_summary(result.can_anchor),
        "initial_cpu_anchor": _solution_summary(result.cpu_anchor),
        "refined_peak_reference": _solution_summary(result.refined_peak_reference),
        "refined_peak_budget": result.refined_peak_budget,
        "refined_can_endpoint": _solution_summary(result.refined_can_endpoint),
        "refined_cpu_endpoint": _solution_summary(result.refined_cpu_endpoint),
        "pareto_count": len(result.pareto_solutions),
        "pareto": [_solution_summary(solution) for solution in result.pareto_solutions],
        "refinement": {
            "passes_run": result.refinement.passes_run,
            "converged": result.refinement.converged,
            "termination_reason": result.refinement.termination_reason,
            "pass_signatures": [item.signature for item in result.refinement.passes],
            "pass_seconds": [item.elapsed_seconds for item in result.refinement.passes],
        },
        "recommendation": {
            "method": result.recommendation.method,
            "solution_hash": result.recommendation.solution_hash,
            "pareto_index": result.recommendation.pareto_index,
            "normalized_q": (
                fraction_dict(result.recommendation.normalized_q)
                if result.recommendation.normalized_q is not None
                else None
            ),
            "normalized_cpu": (
                fraction_dict(result.recommendation.normalized_cpu)
                if result.recommendation.normalized_cpu is not None
                else None
            ),
            "knee_score": (
                fraction_dict(result.recommendation.knee_score)
                if result.recommendation.knee_score is not None
                else None
            ),
            "selected": (_solution_summary(recommended) if recommended is not None else None),
        },
        "performance": {
            "joint_evaluations": result.performance.joint_evaluations,
            "solver_calls": result.performance.solver_calls,
            "cache_hits": result.performance.cache_hits,
            "cache_misses": result.performance.cache_misses,
            "cache_hit_rate": result.performance.cache_hit_rate,
            "unique_d_histograms": result.performance.unique_d_histograms,
            "solver_seconds": result.performance.solver_seconds,
            "refinement_seconds": result.performance.refinement_seconds,
            "epsilon_seconds": result.performance.epsilon_seconds,
            "optimization_seconds": result.performance.total_seconds,
            "wall_seconds_including_load": wall_seconds,
        },
    }


def _run_one(
    phase: str,
    network: str,
    *,
    attempts: int,
    seed: int,
    rho: Fraction,
    epsilon_points: int,
    max_refinement_passes: int,
    endpoint_only: bool,
    write_full: bool,
    resume: bool,
) -> Path:
    tag = (
        f"{network}_a{attempts}_s{seed}_r{rho.numerator}-{rho.denominator}"
        f"_k{epsilon_points}_p{max_refinement_passes}"
        f"{'_endpoints' if endpoint_only else ''}"
    )
    summary_path = OUTPUT_ROOT / phase / f"{tag}.json"
    if resume and summary_path.is_file():
        print(f"SKIP {summary_path}")
        return summary_path
    started = perf_counter()
    loaded = load_project(
        _dbc_for(network),
        ARXML_DIR,
        CONFIG_PATH,
        weight_mode_override=WeightMode.FRAME_TIME_US,
        channel_override=CHANNELS[network],
    )
    optimization = replace(
        loaded.config.optimization,
        restart_policy=RestartPolicy.fixed(attempts),
    )
    clear_main_function_cache()
    result = optimize_can_cpu_balanced(
        network,
        loaded.network.messages,
        optimization,
        loaded.config.objective,
        average_load_limit=loaded.config.model.average_load_limit,
        weight_mode=loaded.network.weight_mode,
        seed=seed,
        joint_config=JointOptimizationConfig(
            rho,
            epsilon_points,
            max_refinement_passes,
            endpoint_only,
        ),
    )
    summary = _result_summary(
        result,
        phase=phase,
        attempts=attempts,
        seed=seed,
        wall_seconds=perf_counter() - started,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if write_full:
        write_joint_result(OUTPUT_ROOT / phase / "full" / tag, result, network)
    print(
        f"DONE {tag} pareto={len(result.pareto_solutions)} "
        f"passes={result.refinement.passes_run if result.refinement else 0} "
        f"seconds={result.performance.total_seconds:.3f}"
    )
    return summary_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("saturation", "baseline", "seed", "epsilon", "rho"),
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--skip-reference",
        action="store_true",
        help="reuse baseline seed=0/K=21/rho=1 instead of rerunning it",
    )
    parser.add_argument(
        "--networks",
        default=",".join(NETWORKS),
        help="comma-separated subset of DK,GL,IC",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    networks = tuple(item.strip() for item in args.networks.split(",") if item.strip())
    if not networks or any(item not in NETWORKS for item in networks):
        raise ValueError("--networks must be a non-empty subset of DK,GL,IC")
    if args.attempts <= 0:
        raise ValueError("--attempts must be positive")

    if args.phase == "saturation":
        cases = ((attempts, 0, Fraction(1), 21, 3, True, False) for attempts in (1, 3, 5, 10))
    elif args.phase == "baseline":
        cases = ((args.attempts, 0, Fraction(1), 21, 3, False, True),)
    elif args.phase == "seed":
        seeds = (1, 2) if args.skip_reference else (0, 1, 2)
        cases = (
            (args.attempts, seed, Fraction(1), 21, 3, False, False)
            for seed in seeds
        )
    elif args.phase == "epsilon":
        point_counts = (41,) if args.skip_reference else (21, 41)
        cases = (
            (args.attempts, 0, Fraction(1), points, 3, False, False)
            for points in point_counts
        )
    else:
        rho_values = (
            (Fraction(1, 4), Fraction(1, 2), Fraction(2), Fraction(4))
            if args.skip_reference
            else (
                Fraction(1, 4),
                Fraction(1, 2),
                Fraction(1),
                Fraction(2),
                Fraction(4),
            )
        )
        cases = (
            (args.attempts, 0, rho, 21, 3, False, False)
            for rho in rho_values
        )
    case_values = tuple(cases)
    for network in networks:
        for (
            attempts,
            seed,
            rho,
            epsilon_points,
            passes,
            endpoint_only,
            write_full,
        ) in case_values:
            _run_one(
                args.phase,
                network,
                attempts=attempts,
                seed=seed,
                rho=rho,
                epsilon_points=epsilon_points,
                max_refinement_passes=passes,
                endpoint_only=endpoint_only,
                write_full=write_full,
                resume=args.resume,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
