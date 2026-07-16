"""Optional OR-Tools CP-SAT verifier for the balanced steady-state subproblem."""

from __future__ import annotations

import csv
import importlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import ObjectiveConfig, PeakToleranceConfig, RestartPolicy
from ..exceptions import ConfigurationError
from ..models import ObjectiveMode, PeakToleranceType, WeightMode
from ..optimization.gcls import run_gcls
from ..optimization.objective import ObjectivePolicy, score_state, slot_load_threshold_us
from ..parsers.project_loader import LoadedProject
from ..reporting.summary_writer import combined_input_hash
from ..reporting.restart_writer import configuration_hash
from ..timeline.state import SearchState


def _cp_model_module() -> Any:
    try:
        return importlib.import_module("ortools.sat.python.cp_model")
    except ImportError as exc:
        raise ConfigurationError(
            "verify-cpsat requires optional OR-Tools; install with "
            "python -m pip install -e \".[solver]\""
        ) from exc


def run_cpsat_verification(
    loaded: LoadedProject,
    output: Path,
    network_prefix: str,
    *,
    seed: int = 0,
    total_attempts: int | None = None,
    tolerance: float = 0.05,
    time_limit_seconds: float = 300.0,
    solver_seed: int = 0,
) -> dict[str, object]:
    """Minimize exact discrete Qss under the GCLS balanced safe set."""
    if loaded.network.weight_mode is not WeightMode.FRAME_TIME_US:
        raise ConfigurationError("verify-cpsat requires frame_time_us")
    if (total_attempts is not None and total_attempts <= 0) or time_limit_seconds <= 0:
        raise ConfigurationError("attempt and solver time limits must be positive")
    cp_model = _cp_model_module()
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
    balanced = run_gcls(
        loaded.network.messages,
        loaded.slot_map,
        config,
        loaded.config.model.average_load_limit,
        seed,
        loaded.network.weight_mode,
        ObjectiveConfig(
            mode=ObjectiveMode.BALANCED,
            peak_tolerance=PeakToleranceConfig(
                PeakToleranceType.RELATIVE, tolerance
            ),
        ),
        peak,
    )
    budget = balanced.peak_budget_us
    if budget is None:
        raise RuntimeError("balanced run did not produce a peak budget")
    balanced_offsets = balanced.offset_by_name()
    model = cp_model.CpModel()
    variables: dict[tuple[str, int], Any] = {}
    for message in loaded.network.messages:
        message_vars = []
        for offset in message.allowed_offsets_us:
            variable = model.NewBoolVar(f"x_{message.definition_index}_{offset}")
            variables[(message.name, offset)] = variable
            message_vars.append(variable)
            model.AddHint(
                variable,
                int(balanced_offsets[message.name] == offset),
            )
        model.Add(sum(message_vars) == 1)

    threshold = slot_load_threshold_us(
        loaded.network.steady_window.slot_width_us,
        loaded.config.model.average_load_limit,
    )
    loads = []
    squares = []
    q_upper = 0
    violation_flags = []
    violation_excesses = []
    int64_limit = (1 << 63) - 1
    for slot in range(loaded.network.steady_window.slot_count):
        terms = []
        upper = 0
        for message in loaded.network.messages:
            candidate_multiplicities = []
            for offset in message.allowed_offsets_us:
                multiplicity = Counter(
                    loaded.slot_map.for_candidate(message, offset).steady
                )[slot]
                candidate_multiplicities.append(multiplicity)
                if multiplicity:
                    terms.append(
                        message.frame_time_us
                        * multiplicity
                        * variables[(message.name, offset)]
                    )
            upper += message.frame_time_us * max(candidate_multiplicities)
        load = model.NewIntVar(0, upper, f"load_{slot}")
        model.Add(load == sum(terms))
        model.Add(load <= budget)
        square_upper = upper * upper
        if square_upper > int64_limit:
            raise ConfigurationError("CP-SAT square bound exceeds int64")
        square = model.NewIntVar(0, square_upper, f"square_{slot}")
        model.AddMultiplicationEquality(square, [load, load])
        q_upper += square_upper
        loads.append(load)
        squares.append(square)
        violation = model.NewBoolVar(f"violation_{slot}")
        model.Add(load >= threshold + 1).OnlyEnforceIf(violation)
        model.Add(load <= threshold).OnlyEnforceIf(violation.Not())
        excess = model.NewIntVar(0, max(0, upper - threshold), f"excess_{slot}")
        model.Add(excess == load - threshold).OnlyEnforceIf(violation)
        model.Add(excess == 0).OnlyEnforceIf(violation.Not())
        violation_flags.append(violation)
        violation_excesses.append(excess)
    if q_upper > int64_limit:
        raise ConfigurationError("CP-SAT Qss bound exceeds int64")
    nvio = sum(violation_flags)
    vvio = sum(violation_excesses)
    reference = peak.objective
    model.Add(nvio <= reference.violation_count)
    equal_n = model.NewBoolVar("same_violation_count_as_reference")
    model.Add(nvio == reference.violation_count).OnlyEnforceIf(equal_n)
    if reference.violation_count == 0:
        model.Add(equal_n == 1)
    else:
        model.Add(nvio <= reference.violation_count - 1).OnlyEnforceIf(
            equal_n.Not()
        )
    model.Add(vvio <= reference.violation_excess).OnlyEnforceIf(equal_n)
    model.Add(sum(squares) <= balanced.objective.sum_square_load)
    model.Minimize(sum(squares))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = solver_seed
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    feasible = status in {"OPTIMAL", "FEASIBLE"}
    assignment_rows: list[dict[str, object]] = []
    verified_objective: dict[str, int] | None = None
    best_feasible: int | None = None
    if feasible:
        assignments: dict[str, int] = {}
        for message in loaded.network.messages:
            selected = [
                offset
                for offset in message.allowed_offsets_us
                if solver.Value(variables[(message.name, offset)]) == 1
            ]
            if len(selected) != 1:
                raise RuntimeError(f"CP-SAT assignment is incomplete for {message.name}")
            assignments[message.name] = selected[0]
            assignment_rows.append(
                {
                    "报文名称": message.name,
                    "CAN_ID": f"0x{message.can_id:X}",
                    "周期(ms)": message.cycle_time_us / 1_000,
                    "保守帧占用时间(μs)": message.frame_time_us,
                    "CP-SAT_Offset(ms)": selected[0] / 1_000,
                }
            )
        state = SearchState(loaded.network.messages, loaded.slot_map)
        state.apply_assignments(assignments)
        objective = score_state(
            state,
            ObjectivePolicy(ObjectiveMode.BALANCED, threshold, budget),
        )
        if objective.steady_peak > budget:
            raise RuntimeError("CP-SAT assignment violates the peak budget")
        if objective.sum_square_load != round(solver.ObjectiveValue()):
            raise RuntimeError("CP-SAT Qss disagrees with SearchState reconstruction")
        verified_objective = {
            "Nvio": objective.violation_count,
            "Vvio": objective.violation_excess,
            "Zss": objective.steady_peak,
            "Qss": objective.sum_square_load,
            "Zst": objective.startup_peak,
            "Qst": objective.startup_sum_square_load,
            "Kmax": objective.max_release_count,
        }
        best_feasible = objective.sum_square_load
    best_bound = float(solver.BestObjectiveBound())
    relative_gap = (
        (best_feasible - best_bound) / max(1, abs(best_feasible))
        if best_feasible is not None
        else None
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "input_hash": combined_input_hash(loaded.network.input_files),
        "configuration_hash": configuration_hash(loaded.config),
        "network": network_prefix,
        "solver": "OR-Tools CP-SAT",
        "solver_status": status,
        "time_limit_seconds": time_limit_seconds,
        "solver_seed": solver_seed,
        "restart_policy": restart_policy.mode.value,
        "actual_peak_attempts": peak.restart_execution.actual_attempts,
        "num_search_workers": 1,
        "wall_time_seconds": solver.WallTime(),
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(),
        "best_feasible_Qss": best_feasible,
        "best_bound_Qss": best_bound,
        "relative_gap": relative_gap,
        "Qss_improvement_vs_gcls": (
            (balanced.objective.sum_square_load - best_feasible)
            / balanced.objective.sum_square_load
            if best_feasible is not None
            else None
        ),
        "strict_peak_reference": list(peak.objective.as_tuple()),
        "peak_budget_us": budget,
        "gcls_balanced_objective": list(balanced.objective.as_tuple()),
        "verified_cpsat_objective": verified_objective,
        "conclusion_boundary": (
            "only OPTIMAL proves the optimum for this fixed discrete model and budget; "
            "FEASIBLE reports bounds only"
        ),
    }
    results_dir = output / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "cpsat_verification.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if assignment_rows:
        with (results_dir / "cpsat_assignment.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(assignment_rows[0]))
            writer.writeheader()
            writer.writerows(assignment_rows)
    return payload
