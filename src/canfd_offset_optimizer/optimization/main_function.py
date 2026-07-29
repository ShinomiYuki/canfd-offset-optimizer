"""! @file main_function.py
@brief 固定 Offset 条件下的 MainFunction 确定性精确分组求解器。

@details
本模块只消费已经归一化为整数微秒的 ``(period_us, offset_us)``，不读取
DBC/ARXML、不修改 Offset，也不接入现有 GCLS 生产路径。算法先按
``D_i = gcd(T_i, O_i)`` 压缩相同类型，再用复杂度为 ``O(3^m)`` 的
subset-DP 精确求解类型集合划分，其中 ``m`` 是不同 D 类型数量。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from math import gcd

from ..exact import RhoInput as RhoInput
from ..exact import normalize_rho as normalize_rho

_MICROSECONDS_PER_SECOND = 1_000_000
_CACHE_MAX_SIZE = 256


def _require_plain_int(value: object, field_name: str) -> int:
    """! @brief 要求时间值为非 bool 的 Python 整数。

    @details
    gcd 的精确时间栅格不能接受浮点数，也不应把 ``True`` 静默当作 1 μs。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer number of microseconds")
    return value


@dataclass(frozen=True, slots=True)
class MainFunctionMessage:
    """! @brief 一条具有最终周期与 Offset 的纯领域输入。

    @param message_key 稳定且唯一的报文键，仅用于把类型分区映射回报文。
    @param period_us 正整数周期，单位为微秒。
    @param offset_us 非负最终 Offset，单位为微秒。

    @note ``message_key`` 不进入任何成本或 tie-break 计算。
    """

    message_key: str
    period_us: int
    offset_us: int

    def __post_init__(self) -> None:
        if not isinstance(self.message_key, str) or not self.message_key.strip():
            raise ValueError("message_key must be a non-empty string")
        period_us = _require_plain_int(self.period_us, "period_us")
        offset_us = _require_plain_int(self.offset_us, "offset_us")
        if period_us <= 0:
            raise ValueError("period_us must be positive")
        if offset_us < 0:
            raise ValueError("offset_us must be non-negative")

    @property
    def d_us(self) -> int:
        """! @brief 返回该报文支持的最大整数调度节拍。

        @details
        ``D_i = gcd(T_i, O_i)``；Python 的 ``gcd(T, 0) == T`` 正好覆盖
        Offset 为零的定义。
        """
        return gcd(self.period_us, self.offset_us)


@dataclass(frozen=True, slots=True)
class MainFunctionGroup:
    """! @brief 一个建议 MainFunction 分组及其最大可行 TimeBase。

    @param messages 按 message_key 稳定排序的具体报文。
    @param timebase_us 组内所有 ``D_i`` 的 gcd，单位为微秒。
    @param group_proxy_cost 该组每秒 CPU Cost Proxy 的精确有理数。
    @param d_types_us 该组包含的不同 D 类型，升序且不重复。
    """

    messages: tuple[MainFunctionMessage, ...]
    timebase_us: int
    group_proxy_cost: Fraction
    d_types_us: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("a MainFunction group must contain at least one message")
        if self.timebase_us <= 0:
            raise ValueError("timebase_us must be positive")
        actual_types = tuple(sorted({message.d_us for message in self.messages}))
        if self.d_types_us != actual_types:
            raise ValueError("d_types_us does not match group messages")
        group_gcd = 0
        for message in self.messages:
            group_gcd = gcd(group_gcd, message.d_us)
        if group_gcd != self.timebase_us:
            raise ValueError("timebase_us must equal the gcd of all group D values")
        if self.group_proxy_cost <= 0:
            raise ValueError("group_proxy_cost must be positive")

    @property
    def message_count(self) -> int:
        """! @brief 返回组内报文数量。"""
        return len(self.messages)


@dataclass(frozen=True, slots=True)
class MainFunctionSolveResult:
    """! @brief 固定 Offset 下的全局精确 MainFunction 分组结果。

    @param cpu_proxy 每秒 CPU Cost Proxy，即
        ``Σ (rho + N_g) * 1_000_000 / B_g_us``。
    @param rho 精确归一化后的固定调用成本参数。
    @param groups 按 D 类型 canonical signature 稳定排序的分组。
    """

    cpu_proxy: Fraction
    rho: Fraction
    groups: tuple[MainFunctionGroup, ...]

    def __post_init__(self) -> None:
        if self.rho <= 0:
            raise ValueError("rho must be positive")
        if not self.groups:
            raise ValueError("solve result must contain at least one group")
        if self.cpu_proxy != sum(
            (group.group_proxy_cost for group in self.groups), start=Fraction()
        ):
            raise ValueError("cpu_proxy must equal the sum of group_proxy_cost")
        keys = [message.message_key for group in self.groups for message in group.messages]
        if len(keys) != len(set(keys)):
            raise ValueError("each message must occur in exactly one group")

    @property
    def cpu_proxy_float(self) -> float:
        """! @brief 仅为展示返回 float；最优性比较未使用该值。"""
        return float(self.cpu_proxy)


@dataclass(frozen=True, slots=True)
class MainFunctionCacheInfo:
    """! @brief 有界 D 直方图求解缓存的只读统计。"""

    hits: int
    misses: int
    maxsize: int
    currsize: int


@dataclass(frozen=True, slots=True)
class _TypePartitionSolution:
    """! @brief 与具体 message identity 无关的不可变类型分区缓存值。"""

    cpu_proxy: Fraction
    groups: tuple[tuple[int, ...], ...]


def calculate_message_d_us(period_us: int, offset_us: int) -> int:
    """! @brief 计算 ``D_i = gcd(T_i, O_i)``。

    @raises TypeError 时间不是整数时抛出。
    @raises ValueError 周期非正或 Offset 为负时抛出。
    """
    period = _require_plain_int(period_us, "period_us")
    offset = _require_plain_int(offset_us, "offset_us")
    if period <= 0:
        raise ValueError("period_us must be positive")
    if offset < 0:
        raise ValueError("offset_us must be non-negative")
    return gcd(period, offset)


def calculate_group_timebase_us(messages: Iterable[MainFunctionMessage]) -> int:
    """! @brief 返回确定分组的唯一最优 TimeBase。

    @details
    对固定分组，``B_g = gcd_i(D_i)`` 是能同时整除全部周期与 Offset 的最大
    正整数。CPU Proxy 随 B 单调递减，因此无需额外搜索 TimeBase。
    """
    items = tuple(messages)
    if not items:
        raise ValueError("group messages must not be empty")
    timebase_us = 0
    for message in items:
        if not isinstance(message, MainFunctionMessage):
            raise TypeError("group messages must contain MainFunctionMessage values")
        timebase_us = gcd(timebase_us, message.d_us)
    return timebase_us


def _partition_key(
    cost: Fraction,
    groups: tuple[tuple[int, ...], ...],
) -> tuple[Fraction, int, tuple[tuple[int, ...], ...]]:
    """! @brief 构造唯一且无额外工程含义的确定性 DP 比较键。

    @details
    首先最小化 CPU Proxy；完全同成本时优先更少 MainFunction；仍相同时只按
    升序 D 类型组签名字典序稳定结果。
    """
    return cost, len(groups), groups


def _solve_histogram_exact(
    histogram: tuple[tuple[int, int], ...],
    rho: Fraction,
) -> _TypePartitionSolution:
    """! @brief 对规范化 D 直方图执行 ``O(3^m)`` exact subset-DP。

    @details
    ``F(S) = min[Cost(A) + F(S\\A)]``，其中 A 必须包含 S 的最低 set bit。
    任意无序集合 partition 都有且只有一个包含该 anchor 的首组，因此递推既不
    遗漏也不因组顺序重复枚举 partition。
    """
    d_values = tuple(d_us for d_us, _ in histogram)
    counts = tuple(count for _, count in histogram)
    type_count = len(histogram)
    state_count = 1 << type_count

    subset_gcd = [0] * state_count
    subset_count = [0] * state_count
    subset_cost = [Fraction()] * state_count
    subset_signature: list[tuple[int, ...]] = [()] * state_count

    for mask in range(1, state_count):
        lowbit = mask & -mask
        index = lowbit.bit_length() - 1
        previous = mask ^ lowbit
        subset_gcd[mask] = (
            d_values[index] if previous == 0 else gcd(subset_gcd[previous], d_values[index])
        )
        subset_count[mask] = subset_count[previous] + counts[index]
        subset_cost[mask] = (rho + subset_count[mask]) * _MICROSECONDS_PER_SECOND / subset_gcd[mask]
        subset_signature[mask] = tuple(
            d_values[bit_index] for bit_index in range(type_count) if mask & (1 << bit_index)
        )

    dp_cost = [Fraction()] * state_count
    dp_groups: list[tuple[tuple[int, ...], ...]] = [()] * state_count

    for mask in range(1, state_count):
        anchor = mask & -mask
        rest = mask ^ anchor
        best_cost: Fraction | None = None
        best_groups: tuple[tuple[int, ...], ...] | None = None
        submask = rest
        while True:
            group_mask = submask | anchor
            remaining = mask ^ group_mask
            candidate_cost = subset_cost[group_mask] + dp_cost[remaining]
            candidate_groups = tuple(sorted((subset_signature[group_mask],) + dp_groups[remaining]))
            if (
                best_cost is None
                or best_groups is None
                or _partition_key(candidate_cost, candidate_groups)
                < _partition_key(best_cost, best_groups)
            ):
                best_cost = candidate_cost
                best_groups = candidate_groups
            if submask == 0:
                break
            submask = (submask - 1) & rest
        assert best_cost is not None and best_groups is not None
        dp_cost[mask] = best_cost
        dp_groups[mask] = best_groups

    full_mask = state_count - 1
    return _TypePartitionSolution(dp_cost[full_mask], dp_groups[full_mask])


@lru_cache(maxsize=_CACHE_MAX_SIZE)
def _solve_histogram_cached(
    histogram: tuple[tuple[int, int], ...],
    rho: Fraction,
) -> _TypePartitionSolution:
    """! @brief 仅按 rho 与有序 D 直方图缓存不可变类型分区。"""
    return _solve_histogram_exact(histogram, rho)


def clear_main_function_cache() -> None:
    """! @brief 清空 exact solver 的有界缓存，供测试和基准隔离使用。"""
    _solve_histogram_cached.cache_clear()


def main_function_cache_info() -> MainFunctionCacheInfo:
    """! @brief 返回 exact solver 缓存命中、未命中与容量统计。"""
    info = _solve_histogram_cached.cache_info()
    return MainFunctionCacheInfo(
        hits=info.hits,
        misses=info.misses,
        maxsize=info.maxsize or 0,
        currsize=info.currsize,
    )


def solve_main_function_partition(
    messages: Iterable[MainFunctionMessage],
    rho: RhoInput = Fraction(1, 1),
) -> MainFunctionSolveResult:
    """! @brief 精确求解固定 Offset 下的最优 MainFunction partition。

    @details
    优化目标为：

    ``min Π Σ_g (rho + N_g) / B_g``，
    ``B_g = gcd_{i in g}(T_i, O_i)``。

    结果按每秒尺度返回，因此微秒分母统一乘以 1,000,000。相同 D 的报文先
    压缩为一个带 count 的类型；exact DP 的 cache key 不含 message_key。

    @param messages 已归一化的报文时间数据；输入顺序不影响结果。
    @param rho MainFunction 固定调用成本相对于单报文增量成本的比值，必须大于零。
    @return 不可变且 canonical 排序的全局精确最优分组。

    @raises ValueError 输入为空、键重复或 rho 非正时抛出。
    @raises TypeError 输入元素或数值类型不符合精确整数模型时抛出。
    """
    items = tuple(messages)
    if not items:
        raise ValueError("messages must not be empty")
    if any(not isinstance(message, MainFunctionMessage) for message in items):
        raise TypeError("messages must contain MainFunctionMessage values")
    keys = [message.message_key for message in items]
    if len(keys) != len(set(keys)):
        raise ValueError("message_key values must be unique")
    normalized_rho = normalize_rho(rho)

    by_d: dict[int, list[MainFunctionMessage]] = {}
    for message in items:
        by_d.setdefault(message.d_us, []).append(message)
    for bucket in by_d.values():
        bucket.sort(key=lambda message: message.message_key)
    histogram = tuple((d_us, len(by_d[d_us])) for d_us in sorted(by_d))

    type_solution = _solve_histogram_cached(histogram, normalized_rho)
    groups: list[MainFunctionGroup] = []
    for d_types in type_solution.groups:
        group_messages = tuple(
            sorted(
                (message for d_us in d_types for message in by_d[d_us]),
                key=lambda message: message.message_key,
            )
        )
        timebase_us = calculate_group_timebase_us(group_messages)
        group_cost = (normalized_rho + len(group_messages)) * _MICROSECONDS_PER_SECOND / timebase_us
        groups.append(
            MainFunctionGroup(
                messages=group_messages,
                timebase_us=timebase_us,
                group_proxy_cost=group_cost,
                d_types_us=d_types,
            )
        )
    return MainFunctionSolveResult(
        cpu_proxy=type_solution.cpu_proxy,
        rho=normalized_rho,
        groups=tuple(groups),
    )
