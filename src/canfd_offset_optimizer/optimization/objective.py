"""! @file objective.py
@brief 计算统一原始指标，并按 peak、balanced、variance 生成固定比较键。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ObjectiveMode, ObjectiveValue
from ..timeline.state import SearchState


@dataclass(frozen=True, slots=True)
class ObjectivePolicy:
    """! @brief 一次搜索中固定不变的目标模式、阈值和峰值预算。"""

    mode: ObjectiveMode
    load_threshold_us: int | None
    peak_budget_us: int | None = None

    def __post_init__(self) -> None:
        if self.load_threshold_us is not None and self.load_threshold_us <= 0:
            raise ValueError("load threshold must be positive")
        if self.mode is ObjectiveMode.BALANCED:
            if self.peak_budget_us is None or self.peak_budget_us <= 0:
                raise ValueError("balanced policy requires a positive peak budget")
        elif self.peak_budget_us is not None:
            raise ValueError("peak budget is only valid for balanced policy")


def coerce_objective_policy(
    value: ObjectivePolicy | int | None,
) -> ObjectivePolicy:
    """! @brief 将旧版阈值参数兼容转换为 peak 策略。"""
    if isinstance(value, ObjectivePolicy):
        return value
    return ObjectivePolicy(ObjectiveMode.PEAK, value)


def slot_load_threshold_us(slot_width_us: int, load_limit: float) -> int:
    """! @brief 把时隙比例转换为至少 1 微秒的保守整数阈值。"""
    if slot_width_us <= 0 or not 0 < load_limit <= 1:
        raise ValueError("slot width and load limit must be positive and limit at most one")
    return max(1, int(slot_width_us * load_limit))


def calculate_objective(
    steady_slot_loads: list[int] | tuple[int, ...],
    startup_slot_loads: list[int] | tuple[int, ...],
    steady_slot_counts: list[int] | tuple[int, ...],
    policy: ObjectivePolicy | int | None,
) -> ObjectiveValue:
    """! @brief 计算 `(Nvio,Vvio,Zss,Qss,Zst,Qst,Kmax)` 原始指标。

    @param load_threshold 物理帧时间模式的时隙阈值；近似权重模式传入 None。
    @raises ValueError 阈值非正或数组负数时抛出。

    @note 无物理阈值时前两项固定为零；近似权重只允许 peak 模式。
    """
    resolved_policy = coerce_objective_policy(policy)
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
        if (
            resolved_policy.load_threshold_us is not None
            and load > resolved_policy.load_threshold_us
        ):
            violation_count += 1
            violation_excess += load - resolved_policy.load_threshold_us
    return ObjectiveValue(
        violation_count=violation_count,
        violation_excess=violation_excess,
        steady_peak=steady_peak,
        startup_peak=max(startup_slot_loads, default=0),
        sum_square_load=sum_square,
        max_release_count=max(steady_slot_counts, default=0),
        startup_sum_square_load=sum(load * load for load in startup_slot_loads),
        mode=resolved_policy.mode,
        peak_budget_us=resolved_policy.peak_budget_us,
    )


def score_state(
    state: SearchState, policy: ObjectivePolicy | int | None
) -> ObjectiveValue:
    """! @brief 从增量状态读取数组并计算目标，不修改状态。"""
    return calculate_objective(
        state.steady_slot_loads,
        state.startup_slot_loads,
        state.steady_slot_counts,
        policy,
    )
