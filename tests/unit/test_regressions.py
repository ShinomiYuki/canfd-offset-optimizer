"""! @file test_regressions.py
@brief 数学守恒、状态原子性、双移动和确定性规则的回归测试。
"""

from itertools import product

import pytest

from canfd_offset_optimizer.config import OptimizationConfig
from canfd_offset_optimizer.exceptions import OptimizationError
from canfd_offset_optimizer.models import CanMessage, WeightMode
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.optimization.greedy import greedy_construct
from canfd_offset_optimizer.optimization.local_search import (
    conflict_pair_search,
    is_one_optimal,
)
from canfd_offset_optimizer.optimization.objective import score_state
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


def _message(
    name: str,
    can_id: int,
    cycle_us: int,
    weight_us: int,
    offsets: tuple[int, ...],
    index: int,
) -> CanMessage:
    return CanMessage(
        name, can_id, False, cycle_us, weight_us, offsets, None, "ECU", index
    )


def test_all_offsets_preserve_steady_releases_load_and_slot_bounds() -> None:
    offsets = (15_000, 20_000, 25_000, 30_000)
    messages = (
        _message("M10", 0x100, 10_000, 101, offsets, 0),
        _message("M20", 0x200, 20_000, 203, offsets, 1),
        _message("M50", 0x300, 50_000, 307, offsets, 2),
    )
    startup, steady, hyperperiod = build_windows(messages, 5_000, 100_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    expected_count = sum(hyperperiod // message.cycle_time_us for message in messages)
    expected_load = sum(
        hyperperiod // message.cycle_time_us * message.frame_time_us
        for message in messages
    )
    for message in messages:
        for offset in offsets:
            hits = slot_map.for_candidate(message, offset)
            assert len(hits.steady) == hyperperiod // message.cycle_time_us
            assert all(0 <= slot < steady.slot_count for slot in hits.steady)
            assert all(0 <= slot < startup.slot_count for slot in hits.startup)
    for assignment in product(offsets, repeat=len(messages)):
        state = SearchState(messages, slot_map)
        state.apply_assignments(
            dict(zip((message.name for message in messages), assignment, strict=True))
        )
        state.validate_invariants(require_complete=True)
        assert sum(state.steady_slot_counts) == expected_count
        assert sum(state.steady_slot_loads) == expected_load


def test_trial_apply_rollback_and_failed_batch_are_exactly_atomic() -> None:
    offsets = (15_000, 20_000, 25_000)
    messages = (
        _message("A", 1, 10_000, 100, offsets, 0),
        _message("B", 2, 20_000, 200, offsets, 1),
    )
    startup, steady, _ = build_windows(messages, 5_000, 40_000)
    state = SearchState(messages, precompute_slot_map(messages, startup, steady))
    state.apply(messages[0], 15_000)
    before = state.clone()
    state.apply(messages[1], 20_000)
    state.rollback(messages[1], 20_000)
    assert state.steady_slot_loads == before.steady_slot_loads
    assert state.startup_slot_loads == before.startup_slot_loads
    assert state.steady_slot_counts == before.steady_slot_counts
    assert state.startup_slot_counts == before.startup_slot_counts
    assert state.current_offsets == before.current_offsets

    empty = SearchState(messages, state.slot_map)
    with pytest.raises(OptimizationError, match="illegal offset"):
        empty.apply_assignments({"A": 15_000, "B": 99_000})
    assert empty.current_offsets == {}
    empty.validate_invariants()


def test_pair_search_never_accepts_a_disguised_single_message_move() -> None:
    movable = _message("movable", 1, 20_000, 200, (5_000, 10_000), 0)
    fixed = _message("fixed", 2, 20_000, 100, (5_000,), 1)
    messages = (movable, fixed)
    startup, steady, _ = build_windows(messages, 5_000, 20_000)
    state = SearchState(messages, precompute_slot_map(messages, startup, steady))
    state.apply(movable, 5_000)
    state.apply(fixed, 5_000)
    assert not is_one_optimal(state, 1_000)
    before = state.clone()
    statistics = conflict_pair_search(state, 1_000, 4, 2, (1,), 5_000)
    assert statistics.accepted_moves == 0
    assert state.current_offsets == before.current_offsets


def test_gcls_is_reproducible_one_optimal_and_input_order_independent() -> None:
    offsets = (15_000, 20_000, 25_000, 30_000)
    messages = (
        _message("C", 0x300, 20_000, 100, offsets, 2),
        _message("A", 0x100, 10_000, 100, offsets, 0),
        _message("B", 0x200, 20_000, 200, offsets, 1),
    )

    def solve(items: tuple[CanMessage, ...]) -> tuple[object, ...]:
        startup, steady, _ = build_windows(items, 5_000, 40_000)
        slot_map = precompute_slot_map(items, startup, steady)
        greedy, _ = greedy_construct(items, slot_map, 3_750)
        result = run_gcls(
            items,
            slot_map,
            OptimizationConfig(random_restarts=2, conflict_candidate_cap=3),
            seed=77,
        )
        final_state = SearchState(items, slot_map)
        final_state.apply_assignments(result.offset_by_name())
        assert result.objective <= score_state(greedy, 3_750)
        assert is_one_optimal(final_state, 3_750)
        return (
            result.assignments,
            result.objective,
            result.steady_slot_loads,
            result.startup_slot_loads,
            result.restart_records,
        )

    assert solve(messages) == solve(messages) == solve(tuple(reversed(messages)))


def test_equal_candidate_scores_use_the_smaller_offset_stably() -> None:
    target = _message("target", 1, 1_000, 10, (15_000, 16_000), 0)
    anchor = _message("anchor", 2, 100_000, 1, (100_000,), 1)
    messages = (target, anchor)
    startup, steady, _ = build_windows(messages, 5_000, 100_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    state, _ = greedy_construct(messages, slot_map, 3_750, messages)
    assert state.current_offsets["target"] == 15_000


def test_offset_larger_than_cycle_changes_startup_but_not_steady_conservation() -> None:
    message = _message("fast", 1, 10_000, 100, (5_000, 25_000), 0)
    startup, steady, _ = build_windows((message,), 5_000, 100_000)
    slot_map = precompute_slot_map((message,), startup, steady)
    early = slot_map.for_candidate(message, 5_000)
    delayed = slot_map.for_candidate(message, 25_000)
    assert len(early.steady) == len(delayed.steady) == 10
    assert early.steady == delayed.steady
    assert len(early.startup) == 2
    assert delayed.startup == ()


def test_approximate_weight_mode_disables_the_physical_microsecond_threshold() -> None:
    message = _message("dense", 1, 1, 1, (5_000,), 0)
    startup, steady, _ = build_windows((message,), 5_000, 5_000)
    slot_map = precompute_slot_map((message,), startup, steady)
    result = run_gcls(
        (message,),
        slot_map,
        OptimizationConfig(
            offset_min_us=5_000,
            offset_max_us=5_000,
            random_restarts=0,
        ),
        weight_mode=WeightMode.UNIT,
    )
    assert result.objective.steady_peak == 5_000
    assert result.objective.violation_count == 0
    assert result.objective.violation_excess == 0
