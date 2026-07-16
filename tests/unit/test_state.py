"""! @file test_state.py
@brief 增量状态 apply/remove/rollback/clone 与守恒不变量测试。

@author 篠見由紀
"""

import pytest

from canfd_offset_optimizer.exceptions import OptimizationError
from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


def messages() -> tuple[CanMessage, ...]:
    offsets = (15_000, 20_000, 25_000)
    return (
        CanMessage("M20", 0x391, False, 20_000, 200, offsets, None, "VCU", 0),
        CanMessage("M10", 0x15E, False, 10_000, 100, offsets, None, "VCU", 1),
    )


def state() -> SearchState:
    items = messages()
    startup, steady, _ = build_windows(items, 5_000, 100_000)
    return SearchState(items, precompute_slot_map(items, startup, steady))


def test_apply_and_rollback_restore_arrays_exactly() -> None:
    search = state()
    message = search.messages[0]
    baseline = search.clone()
    search.apply(message, 15_000)
    assert sum(search.steady_slot_counts) == 5
    assert sum(search.steady_slot_loads) == 1_000
    search.rollback(message, 15_000)
    assert search.steady_slot_loads == baseline.steady_slot_loads
    assert search.startup_slot_loads == baseline.startup_slot_loads
    assert search.current_offsets == {}
    search.validate_invariants()


def test_total_steady_load_is_conserved_across_offsets() -> None:
    for offset in (15_000, 20_000, 25_000):
        search = state()
        for message in search.messages:
            search.apply(message, offset)
        search.validate_invariants(require_complete=True)
        assert sum(search.steady_slot_counts) == 15
        assert sum(search.steady_slot_loads) == 2_000


def test_remove_replace_clone_and_misuse_checks() -> None:
    search = state()
    message = search.messages[0]
    search.apply(message, 15_000)
    clone = search.clone()
    clone.replace(message, 20_000)
    assert search.current_offsets[message.name] == 15_000
    assert clone.current_offsets[message.name] == 20_000
    with pytest.raises(OptimizationError, match="already applied"):
        search.apply(message, 20_000)
    search.remove(message, 15_000)
    search.validate_invariants()
