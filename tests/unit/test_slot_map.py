"""! @file test_slot_map.py
@brief 启动/稳态窗口、绝对 Offset 与命中预计算测试。

@author 篠見由紀
"""

from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.timeline.slot_map import (
    build_slot_hits,
    build_windows,
    precompute_slot_map,
    release_times,
)


def message10() -> CanMessage:
    return CanMessage("M10", 0x15E, False, 10_000, 120, (15_000, 25_000, 100_000), None, "VCU", 0)


def test_500_ms_steady_window_has_50_releases() -> None:
    message = message10()
    startup, steady, hyperperiod = build_windows((message,), 5_000, 500_000)
    assert hyperperiod == 500_000
    assert len(release_times(message, 15_000, steady)) == 50
    assert all(0 <= slot < 100 for slot in build_slot_hits(message, 15_000, steady))
    assert startup.end_us == 100_000


def test_same_steady_phase_can_have_different_startup_hits() -> None:
    message = message10()
    startup, steady, _ = build_windows((message,), 5_000, 500_000)
    slot_map = precompute_slot_map((message,), startup, steady)
    hits15 = slot_map.for_candidate(message, 15_000)
    hits25 = slot_map.for_candidate(message, 25_000)
    assert hits15.steady == hits25.steady
    assert hits15.startup != hits25.startup
    assert hits15.startup[0] == 3
    assert hits25.startup[0] == 5


def test_precomputation_matches_direct_enumeration() -> None:
    message = message10()
    startup, steady, _ = build_windows((message,), 5_000, 500_000)
    slots = precompute_slot_map((message,), startup, steady).for_candidate(message, 15_000)
    expected = tuple((time - steady.start_us) // 5_000 for time in release_times(message, 15_000, steady))
    assert slots.steady == expected
