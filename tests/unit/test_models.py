"""! @file test_models.py
@brief 领域模型和整数超周期测试。

@author 篠見由紀
"""

import pytest

from canfd_offset_optimizer.models import CanMessage, ObjectiveValue, TimeWindow, lcm


def test_typical_periods_have_500_ms_hyperperiod() -> None:
    assert lcm((10_000, 20_000, 50_000, 100_000, 500_000)) == 500_000


def test_four_message_periods_have_100_ms_hyperperiod() -> None:
    assert lcm((20_000, 100_000, 10_000, 50_000)) == 100_000


def test_message_rejects_invalid_cycle_and_offsets() -> None:
    with pytest.raises(ValueError, match="cycle_time_us"):
        CanMessage("bad", 1, False, 0, 100, (15_000,), None, "ECU", 0)
    with pytest.raises(ValueError, match="strictly increasing"):
        CanMessage("bad", 1, False, 10_000, 100, (20_000, 15_000), None, "ECU", 0)


def test_time_window_and_objective_are_immutable_and_comparable() -> None:
    assert TimeWindow(100_000, 600_000, 5_000).slot_count == 100
    better = ObjectiveValue(0, 0, 400, 500, 10_000, 2)
    worse = ObjectiveValue(1, 1, 100, 100, 100, 1)
    assert better < worse
