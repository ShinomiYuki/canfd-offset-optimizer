"""! @file test_objective.py
@brief 原始指标、固定目标模式和阈值测试。

@author 篠見由紀
"""

import pytest

from canfd_offset_optimizer.models import ObjectiveMode, ObjectiveValue
from canfd_offset_optimizer.optimization.objective import (
    ObjectivePolicy,
    calculate_objective,
)


def test_objective_formula() -> None:
    score = calculate_objective([4_000, 3_000, 4_500], [2_000, 2_500], [2, 1, 3], 3_750)
    assert score.as_tuple() == (
        2,
        1_000,
        4_500,
        45_250_000,
        2_500,
        10_250_000,
        3,
    )


def test_violation_worsening_cannot_be_hidden_by_lower_metrics() -> None:
    no_violation = calculate_objective([3_700, 3_700], [9_000], [9, 9], 3_750)
    violation = calculate_objective([3_751, 0], [0], [1, 0], 3_750)
    assert no_violation < violation


def test_fixed_objective_modes_have_exact_lexicographic_order() -> None:
    peak = calculate_objective(
        [100, 100, 200], [100, 200], [1, 1, 2],
        ObjectivePolicy(ObjectiveMode.PEAK, None),
    )
    balanced = calculate_objective(
        [100, 100, 200], [100, 200], [1, 1, 2],
        ObjectivePolicy(ObjectiveMode.BALANCED, None, 210),
    )
    variance = calculate_objective(
        [100, 100, 200], [100, 200], [1, 1, 2],
        ObjectivePolicy(ObjectiveMode.VARIANCE, None),
    )
    assert peak.priorities == (
        "violation_count", "violation_excess", "steady_peak",
        "steady_sum_square_load", "startup_peak",
        "startup_sum_square_load", "max_release_count",
    )
    assert balanced.priorities == (
        "violation_count",
        "violation_excess",
        "peak_budget_excess",
        "steady_sum_square_load",
        "steady_peak",
        "startup_peak",
        "startup_sum_square_load",
        "max_release_count",
    )
    assert variance.priorities == (
        "violation_count",
        "violation_excess",
        "steady_sum_square_load",
        "steady_peak",
        "startup_peak",
        "startup_sum_square_load",
        "max_release_count",
    )
    with pytest.raises(ValueError, match="incomparable"):
        _ = peak < balanced
    with pytest.raises(ValueError, match="incomparable"):
        _ = balanced < variance


def test_sum_of_squares_and_variance_are_equivalent_for_fixed_total_load() -> None:
    first = (0, 100, 200, 300)
    second = (100, 100, 200, 200)

    def variance(loads: tuple[int, ...]) -> float:
        mean = sum(loads) / len(loads)
        return sum((load - mean) ** 2 for load in loads) / len(loads)

    assert sum(first) == sum(second)
    assert sum(load * load for load in second) < sum(load * load for load in first)
    assert variance(second) < variance(first)


def test_mode_comparison_keys_drive_peak_budget_and_variance_tradeoffs() -> None:
    def value(
        mode: ObjectiveMode,
        peak: int,
        qss: int,
        budget: int | None = None,
    ) -> ObjectiveValue:
        return ObjectiveValue(
            0,
            0,
            peak,
            50,
            qss,
            1,
            2_500,
            mode,
            budget,
        )

    # peak 不允许整体平方和改善抵消 1 μs 的峰值恶化。
    assert value(ObjectiveMode.PEAK, 100, 100_000) < value(
        ObjectiveMode.PEAK, 101, 10_000
    )
    # balanced 在预算内先比较 Qss，但任何预算超出量都先于 Qss。
    assert value(ObjectiveMode.BALANCED, 104, 10_000, 105) < value(
        ObjectiveMode.BALANCED, 100, 100_000, 105
    )
    assert value(ObjectiveMode.BALANCED, 100, 100_000, 105) < value(
        ObjectiveMode.BALANCED, 106, 1_000, 105
    )
    # variance 在物理超限指标之后优先比较 Qss。
    assert value(ObjectiveMode.VARIANCE, 200, 10_000) < value(
        ObjectiveMode.VARIANCE, 100, 100_000
    )
