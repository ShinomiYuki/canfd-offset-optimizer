"""Conflict-directed three-message joint relocation for Balanced states."""

from __future__ import annotations

from collections import Counter
from itertools import combinations, product
from time import perf_counter

from ..models import (
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    TripleMoveAudit,
    TripleSearchAudit,
    TripleSearchTimings,
)
from ..timeline.state import SearchState
from .local_search import (
    SearchStatistics,
    conflict_pair_search,
    relocate_single_messages,
)
from .objective import ObjectivePolicy, score_state
from .triple_incremental import (
    PairObjectiveSnapshot,
    ReadOnlyTripleObjectiveEvaluator,
    TripleContributionCache,
)


def triple_hot_slots(state: SearchState, count: int) -> tuple[int, ...]:
    """Rank steady slots by their exact ``L_s²`` contribution."""
    if count <= 0:
        raise ValueError("triple hot slot count must be positive")
    ranked = sorted(
        range(len(state.steady_slot_loads)),
        key=lambda slot: (-(state.steady_slot_loads[slot] ** 2), slot),
    )
    return tuple(ranked[:count])


def triple_conflict_candidates(
    state: SearchState,
    slots: tuple[int, ...],
    candidate_cap: int,
) -> tuple[CanMessage, ...]:
    """Select 6--8 messages by deterministic hotspot square-load contribution."""
    if not 6 <= candidate_cap <= 8:
        raise ValueError("triple candidate cap must be in [6, 8]")
    hot = set(slots)
    ranked: list[tuple[int, CanMessage]] = []
    for message in state.messages:
        offset = state.current_offsets[message.name]
        occurrences = Counter(
            slot
            for slot in state.slot_map.for_candidate(message, offset).steady
            if slot in hot
        )
        contribution = 0
        for slot, count in occurrences.items():
            load = state.steady_slot_loads[slot]
            removed = count * message.frame_time_us
            contribution += load * load - (load - removed) ** 2
        if contribution > 0:
            ranked.append((contribution, message))
    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].definition_index,
            item[1].can_id,
            item[1].name,
        )
    )
    return tuple(message for _, message in ranked[:candidate_cap])


def triple_conflict_neighborhood(
    state: SearchState,
    minimum_hot_slots: int,
    candidate_cap: int,
) -> tuple[tuple[int, ...], tuple[CanMessage, ...]]:
    """Expand square-ranked hotspots until the bounded candidate set is populated."""
    ranked_slots = triple_hot_slots(state, len(state.steady_slot_loads))
    selected_count = min(minimum_hot_slots, len(ranked_slots))
    target = min(candidate_cap, len(state.messages))
    while True:
        slots = ranked_slots[:selected_count]
        candidates = triple_conflict_candidates(state, slots, candidate_cap)
        if len(candidates) >= target or selected_count == len(ranked_slots):
            return slots, candidates
        selected_count += 1


def _signature(state: SearchState, policy: ObjectivePolicy) -> tuple[object, ...]:
    return (
        tuple(sorted(state.current_offsets.items())),
        tuple(state.steady_slot_loads),
        tuple(state.startup_slot_loads),
        tuple(state.steady_slot_counts),
        tuple(state.startup_slot_counts),
        score_state(state, policy),
    )


def _message_key(message: CanMessage) -> tuple[int, int, str]:
    return message.definition_index, message.can_id, message.name


def conflict_triple_search(
    state: SearchState,
    policy: ObjectivePolicy,
    guardrail: tuple[int, int],
    *,
    candidate_cap: int,
    hot_slot_count: int,
    max_rounds: int,
    pair_hot_slot_count: int,
    pair_candidate_cap: int,
    pair_neighbor_steps: tuple[int, ...],
    offset_step_us: int,
    variance_offset_cap: int,
) -> tuple[SearchStatistics, TripleSearchAudit]:
    """Apply deterministic best-improvement three-message moves.

    Candidate objectives are evaluated from immutable snapshots and sparse contribution
    deltas. The formal state is modified exactly once for each accepted round-best move.
    """
    if policy.mode is not ObjectiveMode.BALANCED or policy.peak_budget_us is None:
        raise ValueError("conflict-directed 3-opt requires a Balanced policy")
    if not 6 <= candidate_cap <= 8:
        raise ValueError("triple candidate cap must be in [6, 8]")
    if hot_slot_count <= 0 or max_rounds <= 0:
        raise ValueError("triple hot-slot and round limits must be positive")
    state.validate_invariants(require_complete=True)
    started = perf_counter()
    precompute_started = perf_counter()
    contributions = TripleContributionCache(state.messages, state.slot_map)
    contribution_precompute_seconds = perf_counter() - precompute_started
    total = SearchStatistics()
    checked_triplets_total = 0
    checked_offsets_total = 0
    audits: list[TripleMoveAudit] = []
    stop_reason = "local_optimum"
    candidate_selection_seconds = 0.0
    enumeration_seconds = 0.0
    state_mutation_rollback_seconds = 0.0
    objective_evaluation_seconds = 0.0
    cleanup_seconds = 0.0

    for round_index in range(max_rounds):
        round_started = perf_counter()
        objective_started = perf_counter()
        baseline = score_state(state, policy)
        objective_evaluation_seconds += perf_counter() - objective_started
        evaluator = ReadOnlyTripleObjectiveEvaluator(state, policy, contributions)
        if evaluator.baseline != baseline:
            raise RuntimeError("incremental 3-opt baseline does not match SearchState")
        complete_signature = _signature(state, policy)

        candidate_started = perf_counter()
        _, candidates = triple_conflict_neighborhood(
            state, hot_slot_count, candidate_cap
        )
        candidate_selection_seconds += perf_counter() - candidate_started
        best: tuple[
            ObjectiveValue,
            tuple[tuple[int, int, str], ...],
            tuple[int, int, int],
            tuple[CanMessage, CanMessage, CanMessage],
        ] | None = None
        round_triplets = 0
        round_offsets = 0

        enumeration_started = perf_counter()
        prepared = {
            message.name: evaluator.relocations_for(message)
            for message in candidates
        }
        for raw_triplet in combinations(candidates, 3):
            ordered_triplet = sorted(raw_triplet, key=_message_key)
            triplet = (
                ordered_triplet[0],
                ordered_triplet[1],
                ordered_triplet[2],
            )
            first, second, third = triplet
            old_offsets = (
                state.current_offsets[first.name],
                state.current_offsets[second.name],
                state.current_offsets[third.name],
            )
            first_relocations = prepared[first.name]
            second_relocations = prepared[second.name]
            third_relocations = prepared[third.name]
            pair_snapshots: dict[tuple[int, int], PairObjectiveSnapshot] = {}
            round_triplets += 1
            for new_offsets in product(
                first.allowed_offsets_us,
                second.allowed_offsets_us,
                third.allowed_offsets_us,
            ):
                objective_started = perf_counter()
                pair_key = (new_offsets[0], new_offsets[1])
                pair_snapshot = pair_snapshots.get(pair_key)
                if pair_snapshot is None:
                    pair_snapshot = evaluator.prepare_pair(
                        first_relocations[new_offsets[0]],
                        second_relocations[new_offsets[1]],
                    )
                    pair_snapshots[pair_key] = pair_snapshot
                score = evaluator.evaluate_pair_with_relocation(
                    pair_snapshot,
                    third_relocations[new_offsets[2]],
                )
                objective_evaluation_seconds += perf_counter() - objective_started
                round_offsets += 1
                if (
                    all(
                        new != old
                        for new, old in zip(
                            new_offsets, old_offsets, strict=True
                        )
                    )
                    and (score.violation_count, score.violation_excess) <= guardrail
                    and score.steady_peak <= policy.peak_budget_us
                    and score < baseline
                ):
                    key = (
                        score,
                        (
                            _message_key(first),
                            _message_key(second),
                            _message_key(third),
                        ),
                        new_offsets,
                        triplet,
                    )
                    if best is None or key[:3] < best[:3]:
                        best = key
        enumeration_seconds += perf_counter() - enumeration_started
        if _signature(state, policy) != complete_signature:
            raise RuntimeError("read-only 3-opt evaluation modified SearchState")

        checked_triplets_total += round_triplets
        checked_offsets_total += round_offsets
        total += SearchStatistics(round_offsets, 0)
        if best is None:
            stop_reason = "local_optimum"
            break

        score_after_move, _, new_offsets, triplet = best
        accepted_old_offsets = (
            state.current_offsets[triplet[0].name],
            state.current_offsets[triplet[1].name],
            state.current_offsets[triplet[2].name],
        )
        mutation_started = perf_counter()
        for message in triplet:
            state.remove(message)
        for message, offset in zip(triplet, new_offsets, strict=True):
            state.apply(message, offset)
        state_mutation_rollback_seconds += perf_counter() - mutation_started
        objective_started = perf_counter()
        official_score = score_state(state, policy)
        objective_evaluation_seconds += perf_counter() - objective_started
        if official_score != score_after_move:
            raise RuntimeError("incremental 3-opt objective differs from applied state")
        total += SearchStatistics(0, 1)

        cleanup_started = perf_counter()
        cleanup = relocate_single_messages(state, policy)
        cleanup += conflict_pair_search(
            state,
            policy,
            pair_hot_slot_count,
            pair_candidate_cap,
            pair_neighbor_steps,
            offset_step_us,
            variance_offset_cap,
        )
        cleanup_seconds += perf_counter() - cleanup_started
        total += cleanup
        objective_started = perf_counter()
        after_cleanup = score_state(state, policy)
        objective_evaluation_seconds += perf_counter() - objective_started
        audits.append(
            TripleMoveAudit(
                round_index=round_index,
                message_names=(triplet[0].name, triplet[1].name, triplet[2].name),
                can_ids=(triplet[0].can_id, triplet[1].can_id, triplet[2].can_id),
                old_offsets_us=accepted_old_offsets,
                new_offsets_us=new_offsets,
                objective_before=baseline,
                objective_after_move=score_after_move,
                objective_after_cleanup=after_cleanup,
                checked_triplets=round_triplets,
                checked_offset_combinations=round_offsets,
                cleanup_evaluations=cleanup.evaluations,
                cleanup_accepted_moves=cleanup.accepted_moves,
                elapsed_seconds=perf_counter() - round_started,
            )
        )
    else:
        stop_reason = "max_rounds_reached"

    state.validate_invariants(require_complete=True)
    elapsed_seconds = perf_counter() - started
    audit = TripleSearchAudit(
        candidate_cap=candidate_cap,
        max_rounds=max_rounds,
        hot_slot_count=hot_slot_count,
        checked_triplets=checked_triplets_total,
        checked_offset_combinations=checked_offsets_total,
        accepted_moves=len(audits),
        elapsed_seconds=elapsed_seconds,
        stop_reason=stop_reason,
        rounds=tuple(audits),
        timings=TripleSearchTimings(
            contribution_precompute_seconds=contribution_precompute_seconds,
            candidate_selection_seconds=candidate_selection_seconds,
            enumeration_seconds=enumeration_seconds,
            state_mutation_rollback_seconds=state_mutation_rollback_seconds,
            objective_evaluation_seconds=objective_evaluation_seconds,
            cleanup_seconds=cleanup_seconds,
            total_seconds=elapsed_seconds,
        ),
    )
    return total, audit
