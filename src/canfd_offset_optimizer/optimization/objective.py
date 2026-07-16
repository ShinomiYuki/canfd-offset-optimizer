"""! @file objective.py
@brief 计算设计文档规定的六项词典序目标。

@author 篠見由紀
"""

from __future__ import annotations

from ..models import ObjectiveValue
from ..timeline.state import SearchState


def slot_load_threshold_us(slot_width_us: int, load_limit: float) -> int:
    """! @brief 把时隙比例转换为至少 1 微秒的保守整数阈值。"""
    if slot_width_us <= 0 or not 0 < load_limit <= 1:
        raise ValueError("slot width and load limit must be positive and limit at most one")
    return max(1, int(slot_width_us * load_limit))


def calculate_objective(
    steady_slot_loads: list[int] | tuple[int, ...],
    startup_slot_loads: list[int] | tuple[int, ...],
    steady_slot_counts: list[int] | tuple[int, ...],
    load_threshold: int | None,
) -> ObjectiveValue:
    """! @brief 计算 `(N_vio,V_vio,Zss,Zst,Q,Kmax)`。

    @param load_threshold 物理帧时间模式的时隙阈值；近似权重模式传入 None。
    @raises ValueError 阈值非正或数组负数时抛出。

    @note 无物理阈值时前两项固定为零，后四项仍按近似权重单位优化。
    """
    if load_threshold is not None and load_threshold <= 0:
        raise ValueError("load_threshold must be positive when provided")
    if (
        any(value < 0 for value in steady_slot_loads)
        or any(value < 0 for value in startup_slot_loads)
        or any(value < 0 for value in steady_slot_counts)
    ):
        raise ValueError("loads and counts must be non-negative")
    violation_count = 0
    violation_excess = 0
    steady_peak = 0
    sum_square = 0
    for load in steady_slot_loads:
        steady_peak = max(steady_peak, load)
        sum_square += load * load
        if load_threshold is not None and load > load_threshold:
            violation_count += 1
            violation_excess += load - load_threshold
    return ObjectiveValue(
        violation_count=violation_count,
        violation_excess=violation_excess,
        steady_peak=steady_peak,
        startup_peak=max(startup_slot_loads, default=0),
        sum_square_load=sum_square,
        max_release_count=max(steady_slot_counts, default=0),
    )


def score_state(state: SearchState, load_threshold: int | None) -> ObjectiveValue:
    """! @brief 从增量状态读取数组并计算目标，不修改状态。"""
    return calculate_objective(
        state.steady_slot_loads,
        state.startup_slot_loads,
        state.steady_slot_counts,
        load_threshold,
    )
