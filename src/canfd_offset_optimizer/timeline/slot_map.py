"""! @file slot_map.py
@brief 预计算周期报文在启动与稳态窗口中的离散时隙命中。

@author 篠見由紀
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..models import CanMessage, TimeWindow, lcm


DEFAULT_MAX_SLOT_COUNT = 20_000
DEFAULT_MAX_PRECOMPUTED_HITS = 2_000_000


@dataclass(frozen=True, slots=True)
class SlotMapResourceUsage:
    """Exact resource cardinalities computed without materializing hit arrays."""

    slot_count: int
    precomputed_hits: int


@dataclass(frozen=True, slots=True)
class SlotHits:
    """! @brief 一个候选 Offset 在两个分析窗口中的命中索引。"""

    startup: tuple[int, ...]
    steady: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SlotMap:
    """! @brief 所有 `(message, offset)` 候选命中的只读查找表。"""

    startup_window: TimeWindow
    steady_window: TimeWindow
    hits: Mapping[tuple[str, int], SlotHits]
    resource_usage: SlotMapResourceUsage
    max_slot_count: int
    max_precomputed_hits: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "hits", MappingProxyType(dict(self.hits)))

    def for_candidate(self, message: CanMessage, offset_us: int) -> SlotHits:
        """! @brief 返回指定候选的预计算结果。

        @raises ValueError 当 Offset 不属于报文候选集合时抛出。
        """
        if offset_us not in message.allowed_offsets_us:
            raise ValueError(f"illegal offset {offset_us} for {message.name}")
        try:
            return self.hits[(message.name, offset_us)]
        except KeyError as exc:
            raise ValueError(
                f"slot hits are missing for {message.name} at Offset {offset_us}"
            ) from exc


def build_windows(
    messages: tuple[CanMessage, ...],
    slot_width_us: int,
    hyperperiod_us: int | None = None,
    hyperperiod_cap_us: int = 5_000_000,
) -> tuple[TimeWindow, TimeWindow, int]:
    """! @brief 按绝对 Offset 语义构建启动与稳态窗口。

    @return `(startup, steady, hyperperiod_us)`。
    @raises ValueError 输入为空或窗口无法按时隙整分时抛出。
    """
    if not messages:
        raise ValueError("messages must not be empty")
    if slot_width_us <= 0:
        raise ValueError("slot_width_us must be positive")
    calculated = lcm(tuple(message.cycle_time_us for message in messages))
    hyperperiod = calculated if hyperperiod_us is None else hyperperiod_us
    if hyperperiod < calculated or hyperperiod % calculated:
        raise ValueError("explicit hyperperiod must be a positive multiple of the cycle LCM")
    # Compatibility-only argument: the former fixed duration cap is intentionally ignored.
    _ = hyperperiod_cap_us
    maximum_offset = max(
        max(
            max(message.allowed_offsets_us),
            message.original_offset_us
            if message.original_offset_us is not None
            else 0,
        )
        for message in messages
    )
    window_boundary = max(
        slot_width_us,
        ((maximum_offset + slot_width_us - 1) // slot_width_us) * slot_width_us,
    )
    startup = TimeWindow(0, window_boundary, slot_width_us)
    steady = TimeWindow(window_boundary, window_boundary + hyperperiod, slot_width_us)
    return startup, steady, hyperperiod


def release_times(
    message: CanMessage, offset_us: int, window: TimeWindow
) -> tuple[int, ...]:
    """! @brief 枚举首次发送延迟语义下落入半开窗口的释放时刻。

    @note 不对 Offset 取周期模，故启动窗口可区分同稳态相位候选。
    """
    if offset_us not in message.allowed_offsets_us:
        raise ValueError(f"illegal offset {offset_us} for {message.name}")
    if offset_us >= window.end_us:
        return ()
    if offset_us >= window.start_us:
        first = offset_us
    else:
        delta = window.start_us - offset_us
        first = offset_us + ((delta + message.cycle_time_us - 1) // message.cycle_time_us) * message.cycle_time_us
    return tuple(range(first, window.end_us, message.cycle_time_us))


def release_count(message: CanMessage, offset_us: int, window: TimeWindow) -> int:
    """Count releases exactly without allocating the corresponding tuple."""
    if offset_us not in message.allowed_offsets_us:
        raise ValueError(f"illegal offset {offset_us} for {message.name}")
    if offset_us >= window.end_us:
        return 0
    if offset_us >= window.start_us:
        first = offset_us
    else:
        delta = window.start_us - offset_us
        first = offset_us + (
            (delta + message.cycle_time_us - 1) // message.cycle_time_us
        ) * message.cycle_time_us
    return (window.end_us - 1 - first) // message.cycle_time_us + 1


def estimate_slot_map_resources(
    messages: tuple[CanMessage, ...], startup: TimeWindow, steady: TimeWindow
) -> SlotMapResourceUsage:
    """Return exact slot/hit cardinalities without creating hit or load arrays."""
    if not messages:
        raise ValueError("messages must not be empty")
    if startup.slot_width_us != steady.slot_width_us:
        raise ValueError("startup and steady windows must use the same slot width")
    hit_count = 0
    for message in messages:
        for offset in message.allowed_offsets_us:
            hit_count += release_count(message, offset, startup)
            hit_count += release_count(message, offset, steady)
    return SlotMapResourceUsage(
        slot_count=startup.slot_count + steady.slot_count,
        precomputed_hits=hit_count,
    )


def validate_slot_map_resources(
    messages: tuple[CanMessage, ...],
    startup: TimeWindow,
    steady: TimeWindow,
    *,
    max_slot_count: int = DEFAULT_MAX_SLOT_COUNT,
    max_precomputed_hits: int = DEFAULT_MAX_PRECOMPUTED_HITS,
) -> SlotMapResourceUsage:
    """Fail before allocation when exact timeline cardinalities exceed limits."""
    for name, value in (
        ("max_slot_count", max_slot_count),
        ("max_precomputed_hits", max_precomputed_hits),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    usage = estimate_slot_map_resources(messages, startup, steady)
    context = (
        f"hyperperiod_us={steady.end_us - steady.start_us}, "
        f"slot_width_us={steady.slot_width_us}"
    )
    if usage.slot_count > max_slot_count:
        raise ValueError(
            f"slot_count actual={usage.slot_count} exceeds max_slot_count="
            f"{max_slot_count}; {context}"
        )
    if usage.precomputed_hits > max_precomputed_hits:
        raise ValueError(
            f"precomputed_hits actual={usage.precomputed_hits} exceeds "
            f"max_precomputed_hits={max_precomputed_hits}; {context}"
        )
    return usage


def build_slot_hits(
    message: CanMessage, offset_us: int, window: TimeWindow
) -> tuple[int, ...]:
    """! @brief 将窗口内释放时刻转换为按时间升序的时隙索引。

    @invariant 所有返回索引均在 `[0, window.slot_count)`。
    """
    return tuple(
        (release - window.start_us) // window.slot_width_us
        for release in release_times(message, offset_us, window)
    )


def precompute_slot_map(
    messages: tuple[CanMessage, ...],
    startup: TimeWindow,
    steady: TimeWindow,
    *,
    max_slot_count: int = DEFAULT_MAX_SLOT_COUNT,
    max_precomputed_hits: int = DEFAULT_MAX_PRECOMPUTED_HITS,
) -> SlotMap:
    """! @brief 为全部报文与候选 Offset 构造命中表。"""
    usage = validate_slot_map_resources(
        messages,
        startup,
        steady,
        max_slot_count=max_slot_count,
        max_precomputed_hits=max_precomputed_hits,
    )
    hits: dict[tuple[str, int], SlotHits] = {}
    for message in messages:
        for offset in message.allowed_offsets_us:
            hits[(message.name, offset)] = SlotHits(
                startup=build_slot_hits(message, offset, startup),
                steady=build_slot_hits(message, offset, steady),
            )
    return SlotMap(
        startup,
        steady,
        hits,
        usage,
        max_slot_count,
        max_precomputed_hits,
    )
