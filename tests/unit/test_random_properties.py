"""Deterministic randomized properties for incremental search invariants."""

from __future__ import annotations

import random

from canfd_offset_optimizer.config import ObjectiveConfig, OptimizationConfig
from canfd_offset_optimizer.models import CanMessage, ObjectiveMode
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.optimization.local_search import (
    delta_q_for_relocations,
    lowest_delta_relocation_offsets,
)
from canfd_offset_optimizer.optimization.objective import ObjectivePolicy, score_state
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


OFFSETS = (5_000, 10_000, 15_000, 20_000)


def _instance(seed: int, count: int = 5) -> tuple[tuple[CanMessage, ...], object]:
    generator = random.Random(seed)
    cycles = (10_000, 20_000, 40_000)
    messages = tuple(
        CanMessage(
            name=f"M{index}",
            can_id=0x100 + index,
            is_extended=False,
            cycle_time_us=generator.choice(cycles),
            frame_time_us=generator.randint(40, 400),
            allowed_offsets_us=OFFSETS,
            original_offset_us=generator.choice(OFFSETS),
            sender_ecu="ECU",
            definition_index=index,
        )
        for index in range(count)
    )
    startup, steady, _ = build_windows(messages, 5_000, 40_000)
    return messages, precompute_slot_map(messages, startup, steady)


def _signature(state: SearchState, policy: ObjectivePolicy) -> tuple[object, ...]:
    return (
        tuple(sorted(state.current_offsets.items())),
        tuple(state.steady_slot_loads),
        tuple(state.startup_slot_loads),
        tuple(state.steady_slot_counts),
        tuple(state.startup_slot_counts),
        score_state(state, policy),
    )


def test_random_single_and_pair_delta_q_equal_full_recalculation() -> None:
    generator = random.Random(20260716)
    for instance_seed in range(20):
        messages, slot_map = _instance(instance_seed)
        state = SearchState(messages, slot_map)  # type: ignore[arg-type]
        assignment = {
            message.name: generator.choice(message.allowed_offsets_us)
            for message in messages
        }
        state.apply_assignments(assignment)
        baseline_q = sum(load * load for load in state.steady_slot_loads)

        for message in messages:
            new_offset = generator.choice(message.allowed_offsets_us)
            predicted = delta_q_for_relocations(state, ((message, new_offset),))
            copied = state.clone()
            copied.replace(message, new_offset)
            rebuilt_q = sum(load * load for load in copied.steady_slot_loads)
            assert predicted == rebuilt_q - baseline_q

        first, second = generator.sample(list(messages), 2)
        first_new = generator.choice(first.allowed_offsets_us)
        second_new = generator.choice(second.allowed_offsets_us)
        predicted_pair = delta_q_for_relocations(
            state, ((first, first_new), (second, second_new))
        )
        copied = state.clone()
        copied.replace(first, first_new)
        copied.replace(second, second_new)
        rebuilt_q = sum(load * load for load in copied.steady_slot_loads)
        assert predicted_pair == rebuilt_q - baseline_q


def test_intersecting_old_and_new_slots_have_zero_net_delta() -> None:
    message = CanMessage(
        "phase_equivalent",
        1,
        False,
        10_000,
        137,
        (5_000, 15_000),
        5_000,
        "ECU",
        0,
    )
    startup, steady, _ = build_windows((message,), 5_000, 20_000)
    state = SearchState(
        (message,), precompute_slot_map((message,), startup, steady)
    )
    state.apply(message, 5_000)
    assert (
        state.slot_map.for_candidate(message, 5_000).steady
        == state.slot_map.for_candidate(message, 15_000).steady
    )
    assert delta_q_for_relocations(state, ((message, 15_000),)) == 0


def test_random_apply_rollback_is_exact_and_offsets_are_legal() -> None:
    policy = ObjectivePolicy(ObjectiveMode.VARIANCE, 3_750)
    generator = random.Random(99)
    for instance_seed in range(20, 40):
        messages, slot_map = _instance(instance_seed)
        state = SearchState(messages, slot_map)  # type: ignore[arg-type]
        state.apply_assignments(
            {
                message.name: generator.choice(message.allowed_offsets_us)
                for message in messages
            }
        )
        before = _signature(state, policy)
        message = generator.choice(messages)
        old = state.remove(message)
        trial = generator.choice(message.allowed_offsets_us)
        state.apply(message, trial)
        state.rollback(message, trial)
        state.apply(message, old)
        assert _signature(state, policy) == before
        state.validate_invariants(require_complete=True)
        assert all(
            state.current_offsets[item.name] in item.allowed_offsets_us
            for item in messages
        )


def test_variance_offset_cap_excludes_current_and_uses_stable_ties() -> None:
    messages, slot_map = _instance(41)
    state = SearchState(messages, slot_map)  # type: ignore[arg-type]
    state.apply_assignments({message.name: OFFSETS[0] for message in messages})
    message = messages[0]
    offsets = lowest_delta_relocation_offsets(state, message, 2, OFFSETS[0])
    assert len(offsets) == 2
    assert OFFSETS[0] not in offsets
    assert offsets == lowest_delta_relocation_offsets(state, message, 2, OFFSETS[0])


def test_random_reproducibility_input_order_and_balanced_guarantees() -> None:
    config = OptimizationConfig(
        offset_min_us=5_000,
        offset_max_us=20_000,
        random_restarts=1,
        conflict_candidate_cap=4,
        variance_offset_cap=2,
    )
    for instance_seed in range(8):
        messages, slot_map = _instance(100 + instance_seed)

        def solve(items: tuple[CanMessage, ...]) -> object:
            startup, steady, _ = build_windows(items, 5_000, 40_000)
            local_map = precompute_slot_map(items, startup, steady)
            return run_gcls(
                items,
                local_map,
                config,
                seed=17,
                objective_config=ObjectiveConfig(ObjectiveMode.BALANCED),
            )

        first = solve(messages)
        second = solve(messages)
        reversed_result = solve(tuple(reversed(messages)))
        assert first.assignments == second.assignments == reversed_result.assignments  # type: ignore[attr-defined]
        assert first.objective == second.objective == reversed_result.objective  # type: ignore[attr-defined]
        reference = first.peak_reference_objective  # type: ignore[attr-defined]
        assert reference is not None
        objective = first.objective  # type: ignore[attr-defined]
        assert (objective.violation_count, objective.violation_excess) <= (
            reference.violation_count,
            reference.violation_excess,
        )
        assert objective.steady_peak <= first.peak_budget_us  # type: ignore[attr-defined,operator]
        assert objective.sum_square_load <= reference.sum_square_load
        expected_total = sum(
            40_000 // message.cycle_time_us * message.frame_time_us
            for message in messages
        )
        assert sum(first.steady_slot_loads) == expected_total  # type: ignore[attr-defined]
