"""Conflict-directed 3-opt neighborhood and audit regression tests."""

from __future__ import annotations

from random import Random

import pytest

from canfd_offset_optimizer.models import (
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    TripleSearchAudit,
)
from canfd_offset_optimizer.optimization.local_search import (
    SearchStatistics,
    conflict_pair_search,
    is_one_optimal,
    relocate_single_messages,
)
from canfd_offset_optimizer.optimization.objective import ObjectivePolicy, score_state
from canfd_offset_optimizer.optimization.triple_search import (
    conflict_triple_search,
    triple_conflict_candidates,
    triple_conflict_neighborhood,
    triple_hot_slots,
)
from canfd_offset_optimizer.optimization.triple_incremental import (
    ReadOnlyTripleObjectiveEvaluator,
    TripleContributionCache,
)
from canfd_offset_optimizer.timeline.slot_map import (
    SlotMap,
    build_windows,
    precompute_slot_map,
)
from canfd_offset_optimizer.timeline.state import SearchState


def _fixture() -> tuple[tuple[CanMessage, ...], SlotMap, dict[str, int]]:
    offsets = (5_000, 10_000, 15_000, 20_000)
    specifications = (
        ("A", 40_000, 80, 10_000),
        ("B", 20_000, 150, 5_000),
        ("C", 10_000, 120, 5_000),
        ("D", 40_000, 200, 10_000),
        ("E", 40_000, 120, 10_000),
        ("F", 40_000, 120, 10_000),
    )
    messages = tuple(
        CanMessage(
            name,
            0x100 + index,
            False,
            cycle,
            weight,
            offsets,
            original,
            "ECU",
            index,
        )
        for index, (name, cycle, weight, original) in enumerate(specifications)
    )
    startup, steady, _ = build_windows(messages, 5_000, 40_000)
    assignment = {
        "A": 15_000,
        "B": 20_000,
        "C": 15_000,
        "D": 5_000,
        "E": 10_000,
        "F": 10_000,
    }
    return messages, precompute_slot_map(messages, startup, steady), assignment


def _run(
    state: SearchState, policy: ObjectivePolicy
) -> tuple[SearchStatistics, TripleSearchAudit]:
    return conflict_triple_search(
        state,
        policy,
        (0, 0),
        candidate_cap=6,
        hot_slot_count=3,
        max_rounds=2,
        pair_hot_slot_count=3,
        pair_candidate_cap=6,
        pair_neighbor_steps=(1, 2, 3),
        offset_step_us=5_000,
        variance_offset_cap=3,
    )


def test_conflict_directed_triple_escapes_pair_local_optimum_deterministically() -> None:
    messages, slot_map, assignment = _fixture()
    policy = ObjectivePolicy(ObjectiveMode.BALANCED, None, 336)

    def solve(
        order: tuple[CanMessage, ...],
    ) -> tuple[SearchState, SearchStatistics, tuple[ObjectiveValue, TripleSearchAudit]]:
        state = SearchState(order, slot_map)
        state.apply_assignments(assignment)
        assert relocate_single_messages(state, policy).accepted_moves == 0
        assert (
            conflict_pair_search(state, policy, 3, 6, (1, 2, 3), 5_000, 3)
            .accepted_moves
            == 0
        )
        before = score_state(state, policy)
        statistics, audit = _run(state, policy)
        return state, statistics, (before, audit)

    first_state, first_stats, first_data = solve(messages)
    second_state, second_stats, second_data = solve(tuple(reversed(messages)))
    first_before, first_audit = first_data
    second_before, second_audit = second_data
    assert first_before == second_before
    assert first_audit == second_audit
    assert first_stats == second_stats
    assert first_state.current_offsets == second_state.current_offsets
    after = score_state(first_state, policy)
    assert after < first_before
    assert after.sum_square_load < first_before.sum_square_load
    assert (after.violation_count, after.violation_excess) <= (0, 0)
    assert after.steady_peak <= 336
    assert first_audit.accepted_moves == 1
    assert first_audit.checked_triplets == 2 * 20
    assert first_audit.checked_offset_combinations == 2 * 20 * 64
    assert first_audit.timings is not None
    assert first_audit.timings.total_seconds == first_audit.elapsed_seconds
    move = first_audit.rounds[0]
    assert len(set(move.message_names)) == 3
    assert all(
        old != new
        for old, new in zip(move.old_offsets_us, move.new_offsets_us, strict=True)
    )
    assert move.checked_offset_combinations == move.checked_triplets * 64
    assert is_one_optimal(first_state, policy)
    clone = first_state.clone()
    assert (
        conflict_pair_search(clone, policy, 3, 6, (1, 2, 3), 5_000, 3)
        .accepted_moves
        == 0
    )


def test_triple_trials_are_read_only_when_budget_rejects_every_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages, slot_map, assignment = _fixture()
    state = SearchState(messages, slot_map)
    state.apply_assignments(assignment)
    before = state.clone()
    state_mutations = 0
    original_apply = state.apply
    original_remove = state.remove

    def counted_apply(message: CanMessage, offset: int) -> None:
        nonlocal state_mutations
        state_mutations += 1
        original_apply(message, offset)

    def counted_remove(message: CanMessage, offset: int | None = None) -> int:
        nonlocal state_mutations
        state_mutations += 1
        return original_remove(message, offset)

    monkeypatch.setattr(state, "apply", counted_apply)
    monkeypatch.setattr(state, "remove", counted_remove)
    policy = ObjectivePolicy(ObjectiveMode.BALANCED, None, 1)
    statistics, audit = _run(state, policy)
    assert audit.accepted_moves == 0
    assert audit.checked_triplets > 0
    assert audit.checked_offset_combinations > 0
    assert statistics.accepted_moves == 0
    assert state_mutations == 0
    assert state.current_offsets == before.current_offsets
    assert state.steady_slot_loads == before.steady_slot_loads
    assert state.startup_slot_loads == before.startup_slot_loads
    assert state.steady_slot_counts == before.steady_slot_counts
    assert state.startup_slot_counts == before.startup_slot_counts


def test_triple_candidate_set_is_conflict_ranked_and_capped() -> None:
    messages, slot_map, assignment = _fixture()
    state = SearchState(messages, slot_map)
    state.apply_assignments(assignment)
    slots = triple_hot_slots(state, 3)
    candidates = triple_conflict_candidates(state, slots, 6)
    assert len(candidates) <= 6
    assert len(set(candidates)) == len(candidates)
    assert all(
        set(slot_map.for_candidate(message, assignment[message.name]).steady)
        & set(slots)
        for message in candidates
    )
    expanded_slots, bounded_candidates = triple_conflict_neighborhood(state, 1, 6)
    assert len(expanded_slots) >= 1
    assert len(bounded_candidates) == 6
    assert set(candidates).issubset(bounded_candidates)


def test_triple_search_never_enumerates_all_network_triplets() -> None:
    messages, _, assignment = _fixture()
    extras = tuple(
        CanMessage(
            name,
            0x200 + index,
            False,
            40_000,
            90 + index,
            (5_000, 10_000, 15_000, 20_000),
            5_000,
            "ECU",
            6 + index,
        )
        for index, name in enumerate(("G", "H", "I"))
    )
    all_messages = messages + extras
    startup, steady, _ = build_windows(all_messages, 5_000, 40_000)
    state = SearchState(
        all_messages,
        precompute_slot_map(all_messages, startup, steady),
    )
    state.apply_assignments(assignment | {message.name: 5_000 for message in extras})
    policy = ObjectivePolicy(ObjectiveMode.BALANCED, None, 1)
    _, audit = conflict_triple_search(
        state,
        policy,
        (0, 0),
        candidate_cap=6,
        hot_slot_count=1,
        max_rounds=1,
        pair_hot_slot_count=3,
        pair_candidate_cap=6,
        pair_neighbor_steps=(1, 2, 3),
        offset_step_us=5_000,
        variance_offset_cap=3,
    )
    assert audit.checked_triplets == 20  # C(6, 3), not C(9, 3) = 84.
    assert audit.checked_offset_combinations == 20 * 64


def test_incremental_objective_matches_rebuilt_state_for_random_moves() -> None:
    offsets = (5_000, 20_000, 55_000, 100_000)
    cycles = (2_500, 5_000, 10_000, 20_000, 40_000)
    for seed in range(40):
        random = Random(seed)
        messages = tuple(
            CanMessage(
                f"M{index}",
                0x300 + index,
                False,
                random.choice(cycles),
                random.randint(40, 700),
                offsets,
                random.choice(offsets),
                "ECU",
                index,
            )
            for index in range(8)
        )
        startup, steady, _ = build_windows(messages, 5_000, 400_000)
        slot_map = precompute_slot_map(messages, startup, steady)
        state = SearchState(messages, slot_map)
        state.apply_assignments(
            {message.name: random.choice(offsets) for message in messages}
        )
        before = (
            state.current_offsets.copy(),
            state.steady_slot_loads.copy(),
            state.startup_slot_loads.copy(),
            state.steady_slot_counts.copy(),
            state.startup_slot_counts.copy(),
        )
        policy = ObjectivePolicy(
            ObjectiveMode.BALANCED,
            random.randint(100, 800),
            2_500,
        )
        evaluator = ReadOnlyTripleObjectiveEvaluator(
            state,
            policy,
            TripleContributionCache(messages, slot_map),
        )
        assert evaluator.baseline == score_state(state, policy)
        for _ in range(25):
            selected = random.sample(messages, 3)
            triplet = (selected[0], selected[1], selected[2])
            new_offsets = (
                random.choice(offsets),
                random.choice(offsets),
                random.choice(offsets),
            )
            direct = evaluator.evaluate(triplet, new_offsets)
            first = evaluator.relocations_for(triplet[0])[new_offsets[0]]
            second = evaluator.relocations_for(triplet[1])[new_offsets[1]]
            third = evaluator.relocations_for(triplet[2])[new_offsets[2]]
            pair_based = evaluator.evaluate_pair_with_relocation(
                evaluator.prepare_pair(first, second), third
            )
            rebuilt = state.clone()
            for message in triplet:
                rebuilt.remove(message)
            for message, offset in zip(triplet, new_offsets, strict=True):
                rebuilt.apply(message, offset)
            expected = score_state(rebuilt, policy)
            assert direct == expected
            assert pair_based == expected
            assert direct.metrics_tuple() == expected.metrics_tuple()
        assert state.current_offsets == before[0]
        assert state.steady_slot_loads == before[1]
        assert state.startup_slot_loads == before[2]
        assert state.steady_slot_counts == before[3]
        assert state.startup_slot_counts == before[4]
