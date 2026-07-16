"""! @file gcls.py
@brief 编排贪心、1-opt、冲突双搜索和可复现随机重启。

@author 篠見由紀
"""

from __future__ import annotations

import random
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from math import ceil
from time import perf_counter
from typing import Callable

from ..config import ObjectiveConfig, OptimizationConfig, RestartPolicy
from ..models import (
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    OffsetAssignment,
    OptimizationResult,
    PeakToleranceType,
    RestartAttemptKind,
    RestartExecutionSummary,
    RestartMode,
    RestartRecord,
    WeightMode,
    hash_offset_assignments,
)
from ..timeline.slot_map import SlotMap
from ..timeline.state import SearchState
from .greedy import greedy_construct, greedy_order
from .local_search import (
    SearchStatistics,
    conflict_pair_search,
    relocate_single_messages,
)
from .objective import ObjectivePolicy, score_state, slot_load_threshold_us


def _restart_order(messages: tuple[CanMessage, ...], seed: int) -> tuple[CanMessage, ...]:
    """! @brief 只在同周期、同权重组内按 seed 扰动顺序。"""
    base = greedy_order(messages)
    groups: dict[tuple[int, int], list[CanMessage]] = defaultdict(list)
    group_sequence: list[tuple[int, int]] = []
    for message in base:
        key = (message.cycle_time_us, message.frame_time_us)
        if key not in groups:
            group_sequence.append(key)
        groups[key].append(message)
    generator = random.Random(seed)
    ordered: list[CanMessage] = []
    for key in group_sequence:
        group = groups[key]
        generator.shuffle(group)
        ordered.extend(group)
    return tuple(ordered)


def _assignment_key(state: SearchState) -> tuple[int, ...]:
    return tuple(
        state.current_offsets[message.name]
        for message in sorted(
            state.messages,
            key=lambda item: (item.definition_index, item.can_id, item.name),
        )
    )


def _snapshot_assignments(state: SearchState) -> tuple[OffsetAssignment, ...]:
    messages = sorted(
        state.messages,
        key=lambda item: (item.definition_index, item.can_id, item.name),
    )
    return tuple(
        OffsetAssignment(
            message.name,
            message.can_id,
            state.current_offsets[message.name],
            message.definition_index,
        )
        for message in messages
    )


def _is_balanced_candidate_eligible(
    score: ObjectiveValue,
    reference: ObjectiveValue,
) -> bool:
    """Return whether a balanced candidate satisfies every hard guardrail."""
    return (
        score.peak_budget_excess == 0
        and (score.violation_count, score.violation_excess)
        <= (reference.violation_count, reference.violation_excess)
        and score.sum_square_load <= reference.sum_square_load
    )


def _balanced_guardrail_failures(
    score: ObjectiveValue,
    reference: ObjectiveValue,
    budget_us: int,
) -> tuple[str, ...]:
    """Return explicit post-solve guarantee failures in reporting order."""
    failures: list[str] = []
    if (score.violation_count, score.violation_excess) > (
        reference.violation_count,
        reference.violation_excess,
    ):
        failures.append("(Nvio, Vvio) exceeds strict-peak GCLS reference")
    if score.steady_peak > budget_us:
        failures.append("Zss exceeds peak budget")
    if score.sum_square_load > reference.sum_square_load:
        failures.append("Qss exceeds strict-peak GCLS reference")
    return tuple(failures)


def _run_gcls_with_policy(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    config: OptimizationConfig,
    policy: ObjectivePolicy,
    seed: int,
    incumbent_assignments: dict[str, int] | None = None,
    peak_reference_result: OptimizationResult | None = None,
    restart_policy: RestartPolicy | None = None,
    restart_observer: Callable[[RestartRecord], None] | None = None,
) -> OptimizationResult:
    started = perf_counter()
    selected_restart_policy = restart_policy or config.restart_policy
    attempt_limit = selected_restart_policy.attempt_limit
    baseline_state = SearchState(messages, slot_map)
    for message in messages:
        original = message.original_offset_us
        baseline_offset = (
            original
            if original is not None and original in message.allowed_offsets_us
            else min(message.allowed_offsets_us)
        )
        baseline_state.apply(message, baseline_offset)
    initial_score = score_state(baseline_state, policy)
    # 先把合法原始配置也推进到同一局部最优条件；这样既不会推荐更差结果，
    # 也不会因直接保留一个未经搜索的基线而破坏最终 1-opt 不变量。
    total = relocate_single_messages(
        baseline_state, policy, greedy_order(messages)
    )
    total += conflict_pair_search(
        baseline_state,
        policy,
        config.hot_slot_count,
        config.conflict_candidate_cap,
        config.pair_neighbor_steps,
        config.offset_step_us,
        config.variance_offset_cap,
    )
    best_state = baseline_state.clone()
    best_score = score_state(baseline_state, policy)
    reference_objective = (
        peak_reference_result.objective if peak_reference_result is not None else None
    )

    def is_eligible(score: ObjectiveValue) -> bool:
        if policy.mode is not ObjectiveMode.BALANCED:
            return True
        if reference_objective is None:
            raise ValueError("balanced search requires a peak reference")
        return _is_balanced_candidate_eligible(score, reference_objective)

    if incumbent_assignments is not None:
        incumbent_state = SearchState(messages, slot_map)
        incumbent_state.apply_assignments(incumbent_assignments)
        # The untouched strict-peak assignment is the guaranteed feasible fallback.
        incumbent_initial_score = score_state(incumbent_state, policy)
        if not is_eligible(incumbent_initial_score):
            raise ValueError("balanced peak-reference assignment is not feasible")
        if not is_eligible(best_score) or (
            incumbent_initial_score < best_score
            or (
                incumbent_initial_score == best_score
                and _assignment_key(incumbent_state) < _assignment_key(best_state)
            )
        ):
            best_state = incumbent_state.clone()
            best_score = incumbent_initial_score
        incumbent_stats = relocate_single_messages(
            incumbent_state, policy, greedy_order(messages)
        )
        incumbent_stats += conflict_pair_search(
            incumbent_state,
            policy,
            config.hot_slot_count,
            config.conflict_candidate_cap,
            config.pair_neighbor_steps,
            config.offset_step_us,
            config.variance_offset_cap,
        )
        total += incumbent_stats
        incumbent_score = score_state(incumbent_state, policy)
        if is_eligible(incumbent_score) and (
            incumbent_score < best_score
            or (
                incumbent_score == best_score
                and _assignment_key(incumbent_state) < _assignment_key(best_state)
            )
        ):
            best_state = incumbent_state.clone()
            best_score = incumbent_score
    first_greedy_score = None
    pre_restart_objective = best_score
    pre_restart_assignments = _snapshot_assignments(best_state)
    records: list[RestartRecord] = []
    last_strict_improvement_attempt = 0
    stop_reason = "fixed_limit"
    for attempt in range(attempt_limit):
        attempt_started = perf_counter()
        actual_seed = seed + attempt
        order = greedy_order(messages) if attempt == 0 else _restart_order(messages, actual_seed)
        state, evaluations = greedy_construct(messages, slot_map, policy, order)
        greedy_score = score_state(state, policy)
        if first_greedy_score is None:
            first_greedy_score = greedy_score
        stats = SearchStatistics(evaluations, 0)
        stats += relocate_single_messages(state, policy, order)
        stats += conflict_pair_search(
            state,
            policy,
            config.hot_slot_count,
            config.conflict_candidate_cap,
            config.pair_neighbor_steps,
            config.offset_step_us,
            config.variance_offset_cap,
        )
        total += stats
        score = score_state(state, policy)
        attempt_assignments = _snapshot_assignments(state)
        record = RestartRecord(
                attempt_index=attempt,
                attempt_kind=(
                    RestartAttemptKind.DETERMINISTIC
                    if attempt == 0
                    else RestartAttemptKind.RANDOM
                ),
                seed=actual_seed,
                objective=score,
                assignments=attempt_assignments,
                assignment_hash=hash_offset_assignments(attempt_assignments),
                elapsed_seconds=perf_counter() - attempt_started,
                evaluation_count=stats.evaluations,
                accepted_moves=stats.accepted_moves,
            )
        records.append(record)
        if restart_observer is not None:
            restart_observer(record)
        strict_improvement = is_eligible(score) and score < best_score
        if is_eligible(score) and (
            score < best_score
            or (score == best_score and _assignment_key(state) < _assignment_key(best_state))
        ):
            best_state = state.clone()
            best_score = score
        if strict_improvement:
            last_strict_improvement_attempt = attempt + 1
        actual_attempts = attempt + 1
        if (
            selected_restart_policy.mode is RestartMode.ADAPTIVE
            and actual_attempts >= selected_restart_policy.min_attempts
            and actual_attempts % selected_restart_policy.check_interval == 0
            and actual_attempts - last_strict_improvement_attempt
            >= selected_restart_policy.patience_attempts
        ):
            stop_reason = "patience_exhausted"
            break
    if first_greedy_score is None:
        raise RuntimeError("GCLS produced no attempt")
    ordered_messages = tuple(
        sorted(messages, key=lambda item: (item.definition_index, item.can_id, item.name))
    )
    assignments = tuple(
        OffsetAssignment(
            message.name,
            message.can_id,
            best_state.current_offsets[message.name],
            message.definition_index,
        )
        for message in ordered_messages
    )
    return OptimizationResult(
        messages=ordered_messages,
        assignments=assignments,
        objective=best_score,
        initial_objective=initial_score,
        greedy_objective=first_greedy_score,
        steady_slot_loads=tuple(best_state.steady_slot_loads),
        startup_slot_loads=tuple(best_state.startup_slot_loads),
        steady_slot_counts=tuple(best_state.steady_slot_counts),
        startup_slot_counts=tuple(best_state.startup_slot_counts),
        restart_records=tuple(records),
        restart_execution=RestartExecutionSummary(
            mode=selected_restart_policy.mode,
            actual_attempts=len(records),
            stop_reason=(
                "max_attempts_reached_unverified"
                if selected_restart_policy.mode is RestartMode.ADAPTIVE
                and len(records) == selected_restart_policy.max_attempts
                and stop_reason != "patience_exhausted"
                else stop_reason
            ),
            max_attempts_reached=(
                selected_restart_policy.mode is RestartMode.ADAPTIVE
                and len(records) == selected_restart_policy.max_attempts
                and stop_reason != "patience_exhausted"
            ),
        ),
        evaluation_count=total.evaluations,
        accepted_moves=total.accepted_moves,
        elapsed_seconds=perf_counter() - started,
        peak_reference_objective=(
            peak_reference_result.objective if peak_reference_result else None
        ),
        peak_budget_us=policy.peak_budget_us,
        peak_reference_restart_records=(
            peak_reference_result.restart_records if peak_reference_result else ()
        ),
        peak_reference_evaluation_count=(
            peak_reference_result.evaluation_count if peak_reference_result else 0
        ),
        peak_reference_elapsed_seconds=(
            peak_reference_result.elapsed_seconds if peak_reference_result else 0.0
        ),
        pre_restart_objective=pre_restart_objective,
        pre_restart_assignments=pre_restart_assignments,
    )


def _peak_budget(reference_peak_us: int, objective: ObjectiveConfig) -> int:
    tolerance = objective.peak_tolerance
    if tolerance.type is PeakToleranceType.RELATIVE:
        return ceil(reference_peak_us * (1.0 + tolerance.value))
    return reference_peak_us + int(tolerance.value)


def run_gcls(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    config: OptimizationConfig,
    average_load_limit: float = 0.75,
    seed: int = 0,
    weight_mode: WeightMode = WeightMode.FRAME_TIME_US,
    objective_config: ObjectiveConfig | None = None,
    peak_reference_result: OptimizationResult | None = None,
    restart_observer: Callable[[RestartRecord], None] | None = None,
) -> OptimizationResult:
    """! @brief 按固定目标模式运行 GCLS；balanced 自动执行严格峰值预阶段。

    @note RestartPolicy 统一使用包含首次确定性运行在内的总尝试数。
    """
    objective = objective_config or ObjectiveConfig(mode=ObjectiveMode.PEAK)
    mode = objective.mode
    if weight_mode is not WeightMode.FRAME_TIME_US and mode is not ObjectiveMode.PEAK:
        mode = ObjectiveMode.PEAK
    load_threshold = (
        slot_load_threshold_us(config.slot_width_us, average_load_limit)
        if weight_mode is WeightMode.FRAME_TIME_US
        else None
    )
    if mode is not ObjectiveMode.BALANCED:
        incumbent_assignments = None
        selected_restart_policy = config.restart_policy
        if mode is ObjectiveMode.VARIANCE and peak_reference_result is not None:
            if peak_reference_result.objective.mode is not ObjectiveMode.PEAK:
                raise ValueError("variance incumbent must use peak objective mode")
            incumbent_assignments = peak_reference_result.offset_by_name()
            selected_restart_policy = RestartPolicy.fixed(
                peak_reference_result.restart_execution.actual_attempts
            )
        return _run_gcls_with_policy(
            messages,
            slot_map,
            config,
            ObjectivePolicy(mode, load_threshold),
            seed,
            incumbent_assignments,
            restart_policy=selected_restart_policy,
            restart_observer=restart_observer,
        )
    reference = deepcopy(
        peak_reference_result
        or _run_gcls_with_policy(
            messages,
            slot_map,
            config,
            ObjectivePolicy(ObjectiveMode.PEAK, load_threshold),
            seed,
            restart_observer=restart_observer,
        )
    )
    if reference.objective.mode is not ObjectiveMode.PEAK:
        raise ValueError("balanced peak reference must use peak objective mode")
    expected_reference_seeds = tuple(
        seed + attempt
        for attempt in range(reference.restart_execution.actual_attempts)
    )
    if tuple(record.seed for record in reference.restart_records) != expected_reference_seeds:
        raise ValueError(
            "balanced peak reference must use the same seed sequence"
        )
    budget = _peak_budget(reference.objective.steady_peak, objective)
    balanced = _run_gcls_with_policy(
        messages,
        slot_map,
        config,
        ObjectivePolicy(ObjectiveMode.BALANCED, load_threshold, budget),
        seed,
        reference.offset_by_name(),
        reference,
        RestartPolicy.fixed(reference.restart_execution.actual_attempts),
        restart_observer,
    )
    failures = _balanced_guardrail_failures(
        balanced.objective, reference.objective, budget
    )
    if failures:
        fallback_policy = ObjectivePolicy(
            ObjectiveMode.BALANCED, load_threshold, budget
        )
        fallback_state = SearchState(messages, slot_map)
        fallback_state.apply_assignments(reference.offset_by_name())
        fallback_objective = score_state(fallback_state, fallback_policy)
        balanced = replace(
            balanced,
            assignments=deepcopy(reference.assignments),
            objective=fallback_objective,
            steady_slot_loads=deepcopy(reference.steady_slot_loads),
            startup_slot_loads=deepcopy(reference.startup_slot_loads),
            steady_slot_counts=deepcopy(reference.steady_slot_counts),
            startup_slot_counts=deepcopy(reference.startup_slot_counts),
            balanced_fallback_reason="; ".join(failures),
        )
    remaining_failures = _balanced_guardrail_failures(
        balanced.objective, reference.objective, budget
    )
    if remaining_failures:
        raise RuntimeError(
            "strict-peak fallback failed balanced guarantees: "
            + "; ".join(remaining_failures)
        )
    return replace(
        balanced,
        evaluation_count=(
            balanced.evaluation_count + reference.evaluation_count
        ),
        accepted_moves=balanced.accepted_moves + reference.accepted_moves,
        elapsed_seconds=balanced.elapsed_seconds + reference.elapsed_seconds,
        peak_reference_objective=reference.objective,
        peak_budget_us=budget,
        peak_reference_restart_records=reference.restart_records,
        peak_reference_evaluation_count=reference.evaluation_count,
        peak_reference_elapsed_seconds=reference.elapsed_seconds,
    )
