"""! @file test_local_search.py
@brief 1-opt、热点候选与可复现 GCLS 测试。

@author 篠見由紀
"""

from canfd_offset_optimizer.config import OptimizationConfig
from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.optimization.greedy import greedy_construct
from canfd_offset_optimizer.optimization.local_search import (
    conflict_candidates,
    conflict_pair_search,
    hot_slots,
    is_one_optimal,
    relocate_single_messages,
)
from canfd_offset_optimizer.optimization.objective import score_state
from canfd_offset_optimizer.timeline.slot_map import SlotMap, build_windows, precompute_slot_map


def fixture() -> tuple[tuple[CanMessage, ...], SlotMap]:
    offsets = tuple(range(15_000, 100_001, 5_000))
    specs = ((0x391, 20_000, 180), (0x460, 100_000, 300), (0x15E, 10_000, 120), (0x31B, 50_000, 220))
    messages = tuple(
        CanMessage(f"M{can_id:X}", can_id, False, cycle, weight, offsets, None, "VCU", index)
        for index, (can_id, cycle, weight) in enumerate(specs)
    )
    startup, steady, _ = build_windows(messages, 5_000, 500_000)
    return messages, precompute_slot_map(messages, startup, steady)


def test_relocation_reaches_one_optimum_and_hot_candidates_are_bounded() -> None:
    messages, slot_map = fixture()
    state, _ = greedy_construct(messages, slot_map, 3_750)
    before = score_state(state, 3_750)
    relocate_single_messages(state, 3_750)
    assert score_state(state, 3_750) <= before
    assert is_one_optimal(state, 3_750)
    candidates = conflict_candidates(state, hot_slots(state, 2), 2)
    assert 0 < len(candidates) <= 2
    hot = set(hot_slots(state, 2))
    assert all(
        hot.intersection(state.slot_map.for_candidate(message, state.current_offsets[message.name]).steady)
        for message in candidates
    )


def test_pair_search_only_accepts_improvement_and_gcls_is_reproducible() -> None:
    messages, slot_map = fixture()
    state, _ = greedy_construct(messages, slot_map, 3_750)
    relocate_single_messages(state, 3_750)
    before = score_state(state, 3_750)
    conflict_pair_search(state, 3_750, 3, 3, (1, 2), 5_000)
    assert score_state(state, 3_750) <= before
    config = OptimizationConfig(random_restarts=2, conflict_candidate_cap=3)
    first = run_gcls(messages, slot_map, config, seed=123)
    second = run_gcls(messages, slot_map, config, seed=123)
    assert first.assignments == second.assignments
    assert first.objective == second.objective
    assert first.objective <= first.greedy_objective
    assert first.objective <= first.initial_objective
    assert tuple(record.seed for record in first.restart_records) == (123, 124, 125)


def test_pair_search_escapes_a_one_optimum_by_legal_swap() -> None:
    offsets = (5_000, 10_000, 15_000, 20_000)
    specs = ((10_000, 50), (20_000, 50), (20_000, 200))
    messages = tuple(
        CanMessage(f"P{index}", index + 1, False, cycle, weight, offsets, None, "ECU", index)
        for index, (cycle, weight) in enumerate(specs)
    )
    startup, steady, _ = build_windows(messages, 5_000, 40_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    state, _ = greedy_construct(messages, slot_map, 300)
    # 构造已知 1-opt 平台；只有两个 20 ms 报文协同交换才能降低启动峰值。
    for message in messages:
        state.remove(message)
    for message, offset in zip(messages, (5_000, 20_000, 10_000), strict=True):
        state.apply(message, offset)
    before = score_state(state, 300)
    assert is_one_optimal(state, 300)
    statistics = conflict_pair_search(state, 300, 4, 3, (1, 2, 3), 5_000)
    assert statistics.accepted_moves >= 1
    assert score_state(state, 300) < before
    assert state.current_offsets["P1"] == 10_000
    assert state.current_offsets["P2"] == 20_000
