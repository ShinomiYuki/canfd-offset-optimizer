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
    BalancedCandidateSearchRecord,
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    OffsetAssignment,
    OptimizationResult,
    PeakToleranceType,
    PeakCandidate,
    RestartAttemptKind,
    RestartExecutionSummary,
    RestartMode,
    RestartRecord,
    WeightMode,
    hash_offset_assignments,
    hash_steady_phases,
    steady_phase_vector,
)
from ..timeline.slot_map import SlotMap, precompute_slot_map
from ..timeline.state import SearchState
from .greedy import greedy_construct, greedy_order
from .local_search import (
    SearchStatistics,
    conflict_pair_search,
    relocate_single_messages,
)
from .objective import ObjectivePolicy, score_state, slot_load_threshold_us
from .triple_search import conflict_triple_search


def _original_baseline_score(
    messages: tuple[CanMessage, ...], slot_map: SlotMap, policy: ObjectivePolicy
) -> ObjectiveValue:
    """Score real input Offsets without changing the optimization candidate domain."""
    baseline_messages = tuple(
        replace(
            message,
            allowed_offsets_us=(
                message.original_offset_us
                if message.original_offset_us is not None
                else min(message.allowed_offsets_us),
            ),
        )
        for message in messages
    )
    baseline_map = precompute_slot_map(
        baseline_messages, slot_map.startup_window, slot_map.steady_window
    )
    state = SearchState(baseline_messages, baseline_map)
    for message in baseline_messages:
        state.apply(message, message.allowed_offsets_us[0])
    return score_state(state, policy)


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


def _peak_candidate(
    messages: tuple[CanMessage, ...],
    assignments: tuple[OffsetAssignment, ...],
    objective: ObjectiveValue,
    source_attempt_index: int,
    source_seed: int | None,
) -> PeakCandidate:
    phases = steady_phase_vector(assignments, messages)
    return PeakCandidate(
        source_attempt_index=source_attempt_index,
        source_seed=source_seed,
        objective=objective,
        assignments=assignments,
        assignment_hash=hash_offset_assignments(assignments),
        steady_phases=phases,
        steady_phase_hash=hash_steady_phases(phases),
    )


def _peak_candidate_archive(
    messages: tuple[CanMessage, ...],
    records: tuple[RestartRecord, ...],
    best_assignments: tuple[OffsetAssignment, ...],
    best_objective: ObjectiveValue,
) -> tuple[PeakCandidate, ...]:
    """Build a deterministic, assignment-deduplicated Peak archive."""
    candidates = [
        _peak_candidate(
            messages,
            record.assignments,
            record.objective,
            record.attempt_index,
            record.seed,
        )
        for record in records
    ]
    best_hash = hash_offset_assignments(best_assignments)
    if all(candidate.assignment_hash != best_hash for candidate in candidates):
        candidates.append(
            _peak_candidate(messages, best_assignments, best_objective, -1, None)
        )
    unique: dict[str, PeakCandidate] = {}
    for candidate in candidates:
        previous = unique.get(candidate.assignment_hash)
        if previous is None or (
            candidate.objective.as_tuple(),
            candidate.source_attempt_index,
            candidate.assignment_hash,
        ) < (
            previous.objective.as_tuple(),
            previous.source_attempt_index,
            previous.assignment_hash,
        ):
            unique[candidate.assignment_hash] = candidate
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.objective.as_tuple(),
                item.source_attempt_index,
                item.assignment_hash,
            ),
        )
    )


def _steady_phase_distance(left: PeakCandidate, right: PeakCandidate) -> int:
    if len(left.steady_phases) != len(right.steady_phases):
        raise ValueError("peak candidates use incompatible steady-phase vectors")
    return sum(a != b for a, b in zip(left.steady_phases, right.steady_phases))


def select_peak_candidates(
    reference: OptimizationResult,
    budget_us: int,
    pool_size: int,
) -> tuple[PeakCandidate, ...]:
    """Select budget-feasible Peak candidates with deterministic farthest-first."""
    if pool_size not in {1, 4, 8, 16, 32}:
        raise ValueError("peak candidate pool size must be one of 1, 4, 8, 16, 32")
    reference_hash = hash_offset_assignments(reference.assignments)
    eligible = [
        candidate
        for candidate in reference.peak_candidate_archive
        if (
            candidate.objective.violation_count,
            candidate.objective.violation_excess,
        )
        == (
            reference.objective.violation_count,
            reference.objective.violation_excess,
        )
        and candidate.objective.steady_peak <= budget_us
    ]
    reference_candidate = next(
        (item for item in eligible if item.assignment_hash == reference_hash), None
    )
    if reference_candidate is None:
        reference_candidate = _peak_candidate(
            reference.messages,
            reference.assignments,
            reference.objective,
            -1,
            None,
        )
        eligible.append(reference_candidate)

    # Equal steady phases cannot add the diversity requested by the pool. Keep the
    # best-quality representative, except that the strict Peak reference is fixed first.
    by_phase: dict[str, PeakCandidate] = {
        reference_candidate.steady_phase_hash: reference_candidate
    }
    for candidate in sorted(
        eligible,
        key=lambda item: (
            item.objective.as_tuple(),
            item.source_attempt_index,
            item.assignment_hash,
        ),
    ):
        by_phase.setdefault(candidate.steady_phase_hash, candidate)

    selected = [reference_candidate]
    remaining = [
        item
        for phase_hash, item in by_phase.items()
        if phase_hash != reference_candidate.steady_phase_hash
    ]
    while remaining and len(selected) < pool_size:
        candidate = min(
            remaining,
            key=lambda item: (
                -min(_steady_phase_distance(item, chosen) for chosen in selected),
                item.objective.as_tuple(),
                item.source_attempt_index,
                item.assignment_hash,
            ),
        )
        selected.append(candidate)
        remaining.remove(candidate)
    return tuple(selected)


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
    initial_score = _original_baseline_score(messages, slot_map, policy)
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
    record_tuple = tuple(records)
    candidate_archive = (
        _peak_candidate_archive(
            ordered_messages,
            record_tuple,
            assignments,
            best_score,
        )
        if policy.mode is ObjectiveMode.PEAK
        else ()
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
        restart_records=record_tuple,
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
        peak_candidate_archive=candidate_archive,
    )


def _peak_budget(reference_peak_us: int, objective: ObjectiveConfig) -> int:
    tolerance = objective.peak_tolerance
    if tolerance.type is PeakToleranceType.RELATIVE:
        return ceil(reference_peak_us * (1.0 + tolerance.value))
    return reference_peak_us + int(tolerance.value)


def _run_balanced_candidate_pool(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    config: OptimizationConfig,
    policy: ObjectivePolicy,
    reference: OptimizationResult,
    candidates: tuple[PeakCandidate, ...],
    restart_observer: Callable[[RestartRecord], None] | None,
) -> OptimizationResult:
    """Run one configured Balanced local search from each selected Peak candidate."""
    started = perf_counter()
    if policy.mode is not ObjectiveMode.BALANCED or policy.peak_budget_us is None:
        raise ValueError("candidate-pool search requires a balanced policy")
    if not candidates:
        raise ValueError("candidate-pool search requires at least one candidate")

    baseline_state = SearchState(messages, slot_map)
    for message in messages:
        original = message.original_offset_us
        baseline_state.apply(
            message,
            original
            if original is not None and original in message.allowed_offsets_us
            else min(message.allowed_offsets_us),
        )
    initial_score = _original_baseline_score(messages, slot_map, policy)
    ordered_messages = tuple(
        sorted(messages, key=lambda item: (item.definition_index, item.can_id, item.name))
    )
    order = greedy_order(messages)
    best_state: SearchState | None = None
    best_score: ObjectiveValue | None = None
    total = SearchStatistics()
    records: list[RestartRecord] = []
    search_records: list[BalancedCandidateSearchRecord] = []

    for pool_index, candidate in enumerate(candidates):
        attempt_started = perf_counter()
        state = SearchState(messages, slot_map)
        state.apply_assignments(
            {item.message_name: item.offset_us for item in candidate.assignments}
        )
        objective_before = score_state(state, policy)
        stats = relocate_single_messages(state, policy, order)
        stats += conflict_pair_search(
            state,
            policy,
            config.hot_slot_count,
            config.conflict_candidate_cap,
            config.pair_neighbor_steps,
            config.offset_step_us,
            config.variance_offset_cap,
        )
        triple_audit = None
        if config.conflict_triple_enabled:
            triple_stats, triple_audit = conflict_triple_search(
                state,
                policy,
                (
                    reference.objective.violation_count,
                    reference.objective.violation_excess,
                ),
                candidate_cap=config.triple_candidate_cap,
                hot_slot_count=config.triple_hot_slot_count,
                max_rounds=config.triple_max_rounds,
                pair_hot_slot_count=config.hot_slot_count,
                pair_candidate_cap=config.conflict_candidate_cap,
                pair_neighbor_steps=config.pair_neighbor_steps,
                offset_step_us=config.offset_step_us,
                variance_offset_cap=config.variance_offset_cap,
            )
            stats += triple_stats
        total += stats
        objective_after = score_state(state, policy)
        result_assignments = _snapshot_assignments(state)
        elapsed = perf_counter() - attempt_started
        search_record = BalancedCandidateSearchRecord(
            pool_index=pool_index,
            source_attempt_index=candidate.source_attempt_index,
            source_seed=candidate.source_seed,
            candidate_assignment_hash=candidate.assignment_hash,
            candidate_steady_phase_hash=candidate.steady_phase_hash,
            objective_before=objective_before,
            objective_after=objective_after,
            result_assignments=result_assignments,
            result_assignment_hash=hash_offset_assignments(result_assignments),
            strictly_improved=objective_after < objective_before,
            elapsed_seconds=elapsed,
            evaluation_count=stats.evaluations,
            accepted_moves=stats.accepted_moves,
            triple_search_audit=triple_audit,
        )
        search_records.append(search_record)
        restart_record = RestartRecord(
            attempt_index=pool_index,
            attempt_kind=RestartAttemptKind.DETERMINISTIC,
            seed=candidate.source_seed if candidate.source_seed is not None else 0,
            objective=objective_after,
            assignments=result_assignments,
            assignment_hash=search_record.result_assignment_hash,
            elapsed_seconds=elapsed,
            evaluation_count=stats.evaluations,
            accepted_moves=stats.accepted_moves,
        )
        records.append(restart_record)
        if restart_observer is not None:
            restart_observer(restart_record)

        eligible = _is_balanced_candidate_eligible(
            objective_after, reference.objective
        )
        improves_best = best_score is None or objective_after < best_score
        if best_score is not None and objective_after == best_score:
            assert best_state is not None
            improves_best = _assignment_key(state) < _assignment_key(best_state)
        if eligible and improves_best:
            best_state = state.clone()
            best_score = objective_after

    if best_state is None or best_score is None:
        raise RuntimeError("Peak candidate pool produced no eligible Balanced result")
    final_assignments = _snapshot_assignments(best_state)
    return OptimizationResult(
        messages=ordered_messages,
        assignments=final_assignments,
        objective=best_score,
        initial_objective=initial_score,
        greedy_objective=search_records[0].objective_before,
        steady_slot_loads=tuple(best_state.steady_slot_loads),
        startup_slot_loads=tuple(best_state.startup_slot_loads),
        steady_slot_counts=tuple(best_state.steady_slot_counts),
        startup_slot_counts=tuple(best_state.startup_slot_counts),
        restart_records=tuple(records),
        restart_execution=RestartExecutionSummary(
            mode=RestartMode.FIXED,
            actual_attempts=len(records),
            stop_reason="peak_candidate_pool_exhausted",
        ),
        evaluation_count=total.evaluations,
        accepted_moves=total.accepted_moves,
        elapsed_seconds=perf_counter() - started,
        peak_reference_objective=reference.objective,
        peak_budget_us=policy.peak_budget_us,
        peak_reference_restart_records=reference.restart_records,
        peak_reference_evaluation_count=reference.evaluation_count,
        peak_reference_elapsed_seconds=reference.elapsed_seconds,
        pre_restart_objective=search_records[0].objective_before,
        pre_restart_assignments=candidates[0].assignments,
        peak_candidate_archive=reference.peak_candidate_archive,
        selected_peak_candidates=candidates,
        balanced_candidate_searches=tuple(search_records),
    )


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
    candidates = select_peak_candidates(
        reference,
        budget,
        config.peak_candidate_pool_size,
    )
    balanced = _run_balanced_candidate_pool(
        messages,
        slot_map,
        config,
        ObjectivePolicy(ObjectiveMode.BALANCED, load_threshold, budget),
        reference,
        candidates,
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
