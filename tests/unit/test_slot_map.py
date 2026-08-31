"""! @file test_slot_map.py
@brief 启动/稳态窗口、绝对 Offset 与命中预计算测试。

@author 篠見由紀
"""

import pytest

from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.timeline import slot_map as slot_map_module
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


def test_5000_and_2000_ms_cycles_use_10000_ms_hyperperiod_despite_legacy_cap() -> None:
    messages = (
        CanMessage("M5", 1, False, 5_000_000, 8, (0,), 0, "ECU", 0),
        CanMessage("M2", 2, False, 2_000_000, 8, (0,), 0, "ECU", 1),
    )
    startup, steady, hyperperiod = build_windows(
        messages,
        5_000,
        hyperperiod_cap_us=5_000_000,
    )
    slot_map = precompute_slot_map(messages, startup, steady)
    assert hyperperiod == 10_000_000
    assert steady.slot_count == 2_000
    assert slot_map.resource_usage.slot_count == 2_001


def test_slot_count_limit_fails_before_hit_tuple_allocation(monkeypatch) -> None:
    message = message10()
    startup, steady, _ = build_windows((message,), 5_000, 500_000)
    monkeypatch.setattr(
        slot_map_module,
        "build_slot_hits",
        lambda *_args: pytest.fail("hit tuples must not be allocated"),
    )
    with pytest.raises(
        ValueError,
        match=r"slot_count actual=120 exceeds max_slot_count=119; "
        r"hyperperiod_us=500000, slot_width_us=5000",
    ):
        precompute_slot_map(
            (message,),
            startup,
            steady,
            max_slot_count=119,
        )


def test_precomputed_hit_limit_fails_before_hit_tuple_allocation(monkeypatch) -> None:
    message = message10()
    startup, steady, _ = build_windows((message,), 5_000, 500_000)
    monkeypatch.setattr(
        slot_map_module,
        "build_slot_hits",
        lambda *_args: pytest.fail("hit tuples must not be allocated"),
    )
    with pytest.raises(
        ValueError,
        match=r"precomputed_hits actual=167 exceeds max_precomputed_hits=166; "
        r"hyperperiod_us=500000, slot_width_us=5000",
    ):
        precompute_slot_map(
            (message,),
            startup,
            steady,
            max_precomputed_hits=166,
        )
