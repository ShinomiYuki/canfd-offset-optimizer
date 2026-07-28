"""Unit and tiny exhaustive-oracle tests for the joint CAN/CPU path."""

from __future__ import annotations

import json
from fractions import Fraction
from itertools import product

import pytest

from canfd_offset_optimizer.config import (
    ObjectiveConfig,
    OptimizationConfig,
    RestartPolicy,
)
from canfd_offset_optimizer.models import (
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    OffsetAssignment,
    hash_offset_assignments,
)
from canfd_offset_optimizer.optimization.joint import (
    JointEvaluator,
    JointOptimizationConfig,
    JointSearchMetadata,
    JointSolution,
    _observed_can_endpoint,
    _official_peak_key,
    _peak_feasible_archive,
    build_joint_domain,
    filter_pareto_solutions,
    generate_epsilon_budgets,
    optimize_can_cpu_balanced,
)
from canfd_offset_optimizer.optimization.gcls import calculate_peak_budget_us
from canfd_offset_optimizer.optimization.main_function import (
    MainFunctionGroup,
    MainFunctionMessage,
    MainFunctionSolveResult,
    solve_main_function_partition,
)
from canfd_offset_optimizer.optimization.objective import ObjectivePolicy, score_state
from canfd_offset_optimizer.reporting.joint_writer import (
    fraction_dict,
    write_joint_result,
)


def _message(
    name: str,
    index: int,
    period_us: int,
    frame_time_us: int = 100,
) -> CanMessage:
    return CanMessage(
        name=name,
        can_id=0x100 + index,
        is_extended=False,
        cycle_time_us=period_us,
        frame_time_us=frame_time_us,
        allowed_offsets_us=(10_000, 20_000, 30_000),
        original_offset_us=10_000,
        sender_ecu="ECU",
        definition_index=index,
    )


def _config(*, attempts: int = 1) -> OptimizationConfig:
    return OptimizationConfig(
        slot_width_us=10_000,
        offset_min_us=10_000,
        offset_max_us=30_000,
        offset_step_us=10_000,
        hyperperiod_cap_us=1_000_000,
        restart_policy=RestartPolicy.fixed(attempts),
        hot_slot_count=2,
        conflict_candidate_cap=4,
        variance_offset_cap=2,
    )


def _mixed_messages() -> tuple[CanMessage, ...]:
    return (
        _message("fast_a", 0, 20_000, 100),
        _message("edge", 1, 30_000, 120),
        _message("slow", 2, 60_000, 80),
    )


def test_joint_config_parses_rho_exactly_and_validates_point_count() -> None:
    config = JointOptimizationConfig.from_values("0.1", 7, 4)
    assert config.rho == Fraction(1, 10)
    assert config.epsilon_points == 7
    assert config.max_refinement_passes == 4
    with pytest.raises(ValueError, match="positive"):
        JointOptimizationConfig.from_values("0")
    with pytest.raises(ValueError, match=">= 2"):
        JointOptimizationConfig.from_values("1", 1)
    with pytest.raises(ValueError, match="max_refinement_passes"):
        JointOptimizationConfig.from_values("1", 2, 0)


def test_joint_domain_uses_strict_long_period_threshold_without_mutation() -> None:
    messages = _mixed_messages()
    domain = build_joint_domain(messages, _config())

    assert tuple(item.name for item in domain.decision_messages) == ("fast_a", "edge")
    assert tuple(item.name for item in domain.fixed_messages) == ("slow",)
    assert domain.fixed_offset_map == {"slow": 0}
    assert domain.fixed_messages[0].allowed_offsets_us == (0,)
    assert messages[2].allowed_offsets_us == (10_000, 20_000, 30_000)


def test_fixed_message_is_baseline_for_can_and_exact_cpu_evaluation() -> None:
    domain = build_joint_domain(_mixed_messages(), _config())
    evaluator = JointEvaluator(domain, Fraction(1), None)
    state, metrics = evaluator.evaluate_assignments({"fast_a": 10_000, "edge": 20_000})

    without_fixed = build_joint_domain(
        tuple(item for item in _mixed_messages() if item.name != "slow"),
        _config(),
    )
    without_evaluator = JointEvaluator(without_fixed, Fraction(1), None)
    _, without_metrics = without_evaluator.evaluate_assignments({"fast_a": 10_000, "edge": 20_000})

    assert sum(state.steady_slot_loads) > 0
    assert metrics.qss != without_metrics.qss
    assert {
        message.message_key
        for group in metrics.main_function_result.groups
        for message in group.messages
    } == {"0:256:fast_a", "1:257:edge", "2:258:slow"}


def test_joint_evaluator_matches_formal_can_and_main_function_solvers() -> None:
    domain = build_joint_domain(_mixed_messages(), _config())
    evaluator = JointEvaluator(domain, Fraction(3, 2), None)
    state, metrics = evaluator.evaluate_assignments({"fast_a": 20_000, "edge": 30_000})
    formal_can = score_state(state, ObjectivePolicy(ObjectiveMode.PEAK, None))
    offsets = {
        assignment.message_name: assignment.offset_us
        for assignment in evaluator.full_assignments(state)
    }
    formal_cpu = solve_main_function_partition(
        tuple(
            MainFunctionMessage(
                f"{message.definition_index}:{message.can_id}:{message.name}",
                message.cycle_time_us,
                offsets[message.name],
            )
            for message in domain.all_messages
        ),
        Fraction(3, 2),
    )

    assert metrics.can_objective == formal_can
    assert metrics.main_function_result == formal_cpu


def test_epsilon_budgets_are_exact_monotonic_and_include_endpoints() -> None:
    budgets = generate_epsilon_budgets(Fraction(1, 3), Fraction(7, 6), 5)
    assert budgets == (
        Fraction(1, 3),
        Fraction(13, 24),
        Fraction(3, 4),
        Fraction(23, 24),
        Fraction(7, 6),
    )
    assert tuple(sorted(budgets)) == budgets


def _synthetic_solution(
    name: str,
    qss: int,
    cpu: int,
    peak: int,
    offset_us: int,
) -> JointSolution:
    message = MainFunctionMessage(name, 100_000, 0)
    group = MainFunctionGroup((message,), 100_000, Fraction(cpu), (100_000,))
    solver_result = MainFunctionSolveResult(Fraction(cpu), Fraction(1), (group,))
    objective = ObjectiveValue(
        0,
        0,
        peak,
        peak,
        qss,
        1,
        qss,
        ObjectiveMode.PEAK,
    )
    assignments = (OffsetAssignment(name, 0x100 + offset_us // 10_000, offset_us),)
    metadata = JointSearchMetadata(
        "synthetic",
        0,
        "test",
        (),
        0,
        "test",
        0.0,
    )
    return JointSolution(
        assignments,
        hash_offset_assignments(assignments),
        peak,
        qss,
        Fraction(cpu),
        objective,
        solver_result,
        name,
        None,
        metadata,
    )


def test_pareto_filter_dominance_duplicates_peak_and_order() -> None:
    dominated = _synthetic_solution("b", 11, 11, 1, 11)
    balanced = _synthetic_solution("a-high-peak", 10, 10, 200, 12)
    balanced_lower_peak = _synthetic_solution("a-low-peak", 10, 10, 100, 13)
    can_side = _synthetic_solution("c", 9, 12, 300, 14)
    cpu_side = _synthetic_solution("d", 12, 9, 50, 15)

    result = filter_pareto_solutions((dominated, balanced, balanced_lower_peak, can_side, cpu_side))

    assert [(item.qss, item.cpu_proxy) for item in result] == [
        (9, Fraction(12)),
        (10, Fraction(10)),
        (12, Fraction(9)),
    ]
    assert result[1].peak == 100
    assert cpu_side in result  # 更低 Peak 不会让 (Q=12,P=9) 支配其他目标点。


def test_archive_refines_dominated_can_endpoint_and_next_pmax() -> None:
    initial = _synthetic_solution("initial", 10, 300, 100, 10)
    same_q_lower_cpu = _synthetic_solution("refined", 10, 250, 100, 20)
    both_better = _synthetic_solution("best", 9, 240, 100, 30)

    endpoint = _observed_can_endpoint((initial, same_q_lower_cpu))
    assert endpoint.assignment_hash == same_q_lower_cpu.assignment_hash
    assert endpoint.cpu_proxy == 250
    assert generate_epsilon_budgets(Fraction(100), endpoint.cpu_proxy, 3)[-1] == 250

    endpoint = _observed_can_endpoint((initial, same_q_lower_cpu, both_better))
    assert endpoint.assignment_hash == both_better.assignment_hash
    pareto = filter_pareto_solutions((initial, same_q_lower_cpu, both_better))
    assert pareto == (both_better,)


def test_peak_refinement_recomputes_budget_and_excludes_old_point() -> None:
    old_peak = _synthetic_solution("old-peak", 10, 10, 100, 10)
    improved_peak = _synthetic_solution("new-peak", 50, 50, 80, 20)
    selected = min((old_peak, improved_peak), key=_official_peak_key)
    budget = calculate_peak_budget_us(selected.peak, ObjectiveConfig())
    feasible = _peak_feasible_archive(
        {
            old_peak.assignment_hash: old_peak,
            improved_peak.assignment_hash: improved_peak,
        },
        selected,
        budget,
    )

    assert selected is improved_peak
    assert budget == 84
    assert feasible == (improved_peak,)


def test_no_decision_domain_returns_one_full_solution() -> None:
    messages = (
        _message("slow_a", 0, 60_000),
        _message("slow_b", 1, 120_000),
    )
    result = optimize_can_cpu_balanced(
        "all-fixed",
        messages,
        _config(),
        ObjectiveConfig(),
        joint_config=JointOptimizationConfig.from_values("1", 3),
    )

    assert result.status == "no_decision_messages"
    assert result.decision_message_count == 0
    assert result.fixed_message_count == 2
    assert result.epsilon_runs == ()
    assert result.pareto_solutions == (result.can_anchor,)
    assert {item.offset_us for item in result.can_anchor.assignments} == {0}


def test_equal_anchor_cpu_proxy_skips_redundant_epsilon_runs() -> None:
    result = optimize_can_cpu_balanced(
        "degenerate",
        (_message("phase-equivalent", 0, 10_000),),
        _config(),
        ObjectiveConfig(),
        joint_config=JointOptimizationConfig.from_values("1", 5),
    )

    assert result.status == "no_observed_cpu_tradeoff"
    assert result.cpu_anchor.cpu_proxy == result.can_anchor.cpu_proxy
    assert result.epsilon_runs == ()
    assert len(result.pareto_solutions) == 1


def test_refinement_converges_or_reports_bounded_limit() -> None:
    converged = optimize_can_cpu_balanced(
        "converged",
        _mixed_messages(),
        _config(),
        ObjectiveConfig(),
        joint_config=JointOptimizationConfig.from_values("1", 3, 3),
    )
    assert converged.refinement is not None
    assert converged.refinement.converged
    assert converged.refinement.passes_run == 2
    assert converged.refinement.termination_reason == "refinement_converged"
    assert converged.refinement.passes[0].signature == (converged.refinement.passes[1].signature)

    limited = optimize_can_cpu_balanced(
        "limited",
        _mixed_messages(),
        _config(),
        ObjectiveConfig(),
        joint_config=JointOptimizationConfig.from_values("1", 3, 1),
    )
    assert limited.refinement is not None
    assert not limited.refinement.converged
    assert limited.refinement.passes_run == 1
    assert limited.refinement.termination_reason == "refinement_limit_reached"


def test_joint_attempt_schedule_is_prefix_preserving() -> None:
    def run(attempts: int):
        return optimize_can_cpu_balanced(
            f"prefix-{attempts}",
            _mixed_messages(),
            _config(attempts=attempts),
            ObjectiveConfig(),
            seed=23,
            joint_config=JointOptimizationConfig.from_values(
                "1",
                3,
                1,
                endpoint_only=True,
            ),
        )

    one = run(1)
    three = run(3)
    for source in (
        "initial_peak_reference",
        "refinement_00_peak",
        "refinement_00_can",
        "refinement_00_cpu",
    ):
        one_stage = next(item for item in one.stage_solutions if item.source == source)
        three_stage = next(item for item in three.stage_solutions if item.source == source)
        assert [
            (item.seed, item.assignment_hash) for item in one_stage.search_metadata.attempts
        ] == [
            (item.seed, item.assignment_hash) for item in three_stage.search_metadata.attempts[:1]
        ]


def test_anchors_epsilon_constraints_and_determinism() -> None:
    arguments = (
        "tiny",
        _mixed_messages(),
        _config(attempts=2),
        ObjectiveConfig(),
    )
    first = optimize_can_cpu_balanced(
        *arguments,
        seed=17,
        joint_config=JointOptimizationConfig.from_values("1", 5),
    )
    second = optimize_can_cpu_balanced(
        *arguments,
        seed=17,
        joint_config=JointOptimizationConfig.from_values("1", 5),
    )

    assert first.cpu_anchor.cpu_proxy <= first.can_anchor.cpu_proxy
    assert first.can_anchor.peak <= first.peak_budget
    assert first.cpu_anchor.peak <= first.peak_budget
    assert all(run.solution.cpu_proxy <= run.budget for run in first.epsilon_runs)
    assert first.epsilon_runs[0].budget == first.cpu_anchor.cpu_proxy
    assert first.epsilon_runs[-1].budget == first.can_anchor.cpu_proxy
    assert first.epsilon_runs[-1].solution.qss <= first.can_anchor.qss
    assert all(
        previous.solution.cpu_proxy <= current.budget
        for previous, current in zip(
            first.epsilon_runs,
            first.epsilon_runs[1:],
        )
    )
    assert tuple(run.budget for run in first.epsilon_runs) == tuple(
        sorted(run.budget for run in first.epsilon_runs)
    )
    assert [item.assignment_hash for item in first.pareto_solutions] == [
        item.assignment_hash for item in second.pareto_solutions
    ]
    assert [(item.qss, item.cpu_proxy, item.peak) for item in first.pareto_solutions] == [
        (item.qss, item.cpu_proxy, item.peak) for item in second.pareto_solutions
    ]
    audited_solutions = (
        first.peak_reference,
        first.can_anchor,
        first.cpu_anchor,
        *(run.solution for run in first.epsilon_runs),
        *first.pareto_solutions,
    )
    assert all(
        next(
            assignment.offset_us
            for assignment in solution.assignments
            if assignment.message_name == "slow"
        )
        == 0
        for solution in audited_solutions
    )
    assert all(
        next(
            assignment.offset_us
            for assignment in attempt.assignments
            if assignment.message_name == "slow"
        )
        == 0
        for solution in audited_solutions
        for attempt in solution.search_metadata.attempts
    )


def test_tiny_pareto_solutions_are_nondominated_by_exhaustive_oracle() -> None:
    messages = _mixed_messages()
    config = _config(attempts=2)
    result = optimize_can_cpu_balanced(
        "oracle",
        messages,
        config,
        ObjectiveConfig(),
        seed=9,
        joint_config=JointOptimizationConfig.from_values("1", 7),
    )
    domain = build_joint_domain(messages, config)
    evaluator = JointEvaluator(domain, Fraction(1), None)
    oracle: list[tuple[int, Fraction, int]] = []
    for offsets in product(*(message.allowed_offsets_us for message in domain.decision_messages)):
        _, metrics = evaluator.evaluate_assignments(
            {
                message.name: offset
                for message, offset in zip(domain.decision_messages, offsets, strict=True)
            }
        )
        if metrics.peak <= result.peak_budget:
            oracle.append((metrics.qss, metrics.cpu_proxy, metrics.peak))

    for solution in result.pareto_solutions:
        assert not any(
            qss <= solution.qss
            and cpu <= solution.cpu_proxy
            and (qss < solution.qss or cpu < solution.cpu_proxy)
            for qss, cpu, _peak in oracle
        )
    oracle_pairs = {
        (qss, cpu)
        for qss, cpu, _peak in oracle
        if not any(
            other_qss <= qss and other_cpu <= cpu and (other_qss < qss or other_cpu < cpu)
            for other_qss, other_cpu, _other_peak in oracle
        )
    }
    assert {(item.qss, item.cpu_proxy) for item in result.pareto_solutions} == oracle_pairs


def test_joint_json_preserves_exact_fractions_and_full_audit(tmp_path) -> None:
    result = optimize_can_cpu_balanced(
        "json",
        _mixed_messages(),
        _config(),
        ObjectiveConfig(),
        seed=3,
        joint_config=JointOptimizationConfig.from_values("0.5", 3),
    )
    output = write_joint_result(tmp_path, result, "json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert fraction_dict(Fraction(2, 3))["exact"] == "2/3"
    assert payload["schema_version"] == 2
    assert payload["configuration"]["rho"]["exact"] == "1/2"
    assert payload["configuration"]["max_refinement_passes"] == 3
    assert payload["anchors"]["can_anchor"]["assignment_hash"]
    assert payload["anchors"]["can_anchor"]["main_function"]["groups"]
    assert payload["anchors"]["refined_can_endpoint"]["assignment_hash"]
    assert payload["candidate_archive"]["assignment_count"] > 0
    assert payload["stage_results"]
    assert payload["refinement"]["passes_run"] >= 1
    assert payload["refinement"]["termination_reason"] in {
        "refinement_converged",
        "refinement_limit_reached",
    }
    assert payload["recommendation"]["method"] in {
        "geometric_knee",
        "ideal_point_fallback",
        "unique_solution",
        "no_interior_knee",
    }
    assert payload["performance"]["refinement_seconds"] >= 0
    assert payload["performance"]["epsilon_seconds"] >= 0
    assert payload["performance"]["solver_calls"] > 0
