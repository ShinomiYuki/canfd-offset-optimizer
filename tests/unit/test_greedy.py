"""! @file test_greedy.py
@brief 四报文夹具的贪心完整性、确定性和基线比较测试。

@author 篠見由紀
"""

from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.optimization.greedy import greedy_construct, greedy_order
from canfd_offset_optimizer.optimization.objective import score_state
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


def four_messages() -> tuple[CanMessage, ...]:
    offsets = tuple(range(15_000, 100_001, 5_000))
    values = (
        ("M391", 0x391, 20_000, 180),
        ("M460", 0x460, 100_000, 300),
        ("M15E", 0x15E, 10_000, 120),
        ("M31B", 0x31B, 50_000, 220),
    )
    return tuple(
        CanMessage(name, can_id, False, cycle, weight, offsets, None, "VCU", index)
        for index, (name, can_id, cycle, weight) in enumerate(values)
    )


def test_greedy_is_complete_deterministic_and_not_worse_than_minimum_offset() -> None:
    messages = four_messages()
    startup, steady, _ = build_windows(messages, 5_000, 500_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    first, _ = greedy_construct(messages, slot_map, 3_750)
    second, _ = greedy_construct(messages, slot_map, 3_750)
    baseline = SearchState(messages, slot_map)
    for message in messages:
        baseline.apply(message, min(message.allowed_offsets_us))
    assert max(baseline.steady_slot_counts) == len(messages)
    assert first.current_offsets == second.current_offsets
    assert len(first.current_offsets) == 4
    assert score_state(first, 3_750) <= score_state(baseline, 3_750)
    assert tuple(message.name for message in greedy_order(messages))[0] == "M15E"
