"""! @file test_objective.py
@brief 六项目标顺序和阈值测试。

@author 篠見由紀
"""

from canfd_offset_optimizer.optimization.objective import calculate_objective


def test_objective_formula() -> None:
    score = calculate_objective([4_000, 3_000, 4_500], [2_000, 2_500], [2, 1, 3], 3_750)
    assert score.as_tuple() == (2, 1_000, 4_500, 2_500, 45_250_000, 3)


def test_violation_worsening_cannot_be_hidden_by_lower_metrics() -> None:
    no_violation = calculate_objective([3_700, 3_700], [9_000], [9, 9], 3_750)
    violation = calculate_objective([3_751, 0], [0], [1, 0], 3_750)
    assert no_violation < violation
