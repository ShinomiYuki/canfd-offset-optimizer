"""! @file models.py
@brief 与 DBC、ARXML 库解耦的领域模型。

@details
核心时间量全部使用整数微秒；搜索状态以外的公共对象均不可变。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import reduce
from math import gcd, isfinite
from pathlib import Path
from typing import Any


class FrameFormat(str, Enum):
    """! @brief CAN 帧标识符格式。"""

    STANDARD = "standard"
    EXTENDED = "extended"


class WeightMode(str, Enum):
    """! @brief 报文权重的计算来源。"""

    FRAME_TIME_US = "frame_time_us"
    PAYLOAD_BYTES = "payload_bytes"
    UNIT = "unit"


CAN_FD_PAYLOAD_LENGTHS = frozenset(
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)
)


@dataclass(frozen=True, slots=True)
class CanMessage:
    """! @brief 描述一条参与 Offset 优化的周期 CAN FD 报文。

    @invariant 周期、权重和载荷长度为正，候选 Offset 非空且严格递增。
    """

    name: str
    can_id: int
    is_extended: bool
    cycle_time_us: int
    frame_time_us: int
    allowed_offsets_us: tuple[int, ...]
    original_offset_us: int | None
    sender_ecu: str
    definition_index: int
    payload_bytes: int = 8

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("message name must not be empty")
        max_id = 0x1FFFFFFF if self.is_extended else 0x7FF
        if not 0 <= self.can_id <= max_id:
            raise ValueError(f"CAN ID 0x{self.can_id:X} is invalid for this frame format")
        if self.cycle_time_us <= 0:
            raise ValueError("cycle_time_us must be positive")
        if self.frame_time_us <= 0:
            raise ValueError("frame_time_us must be positive")
        if self.payload_bytes not in CAN_FD_PAYLOAD_LENGTHS:
            raise ValueError(
                f"payload_bytes={self.payload_bytes} is not representable by a CAN FD DLC"
            )
        if self.definition_index < 0:
            raise ValueError("definition_index must be non-negative")
        if not self.sender_ecu.strip():
            raise ValueError("sender_ecu must not be empty")
        if not self.allowed_offsets_us:
            raise ValueError("allowed_offsets_us must not be empty")
        if any(offset < 0 for offset in self.allowed_offsets_us):
            raise ValueError("allowed_offsets_us must be non-negative")
        if tuple(sorted(set(self.allowed_offsets_us))) != self.allowed_offsets_us:
            raise ValueError("allowed_offsets_us must be unique and strictly increasing")
        if self.original_offset_us is not None and self.original_offset_us < 0:
            raise ValueError("original_offset_us must be non-negative")

    @property
    def frame_format(self) -> FrameFormat:
        """! @brief 返回标准帧或扩展帧枚举。"""
        return FrameFormat.EXTENDED if self.is_extended else FrameFormat.STANDARD


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    """! @brief 帧时间计算所需的 CAN FD 通道参数。"""

    name: str
    nominal_bitrate: int | None
    data_bitrate: int | None
    brs: bool | None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("channel name must not be empty")
        if self.nominal_bitrate is not None and self.nominal_bitrate <= 0:
            raise ValueError("nominal_bitrate must be positive when provided")
        if self.data_bitrate is not None and self.data_bitrate <= 0:
            raise ValueError("data_bitrate must be positive when provided")


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """! @brief 半开时间窗口及其离散时隙宽度。"""

    start_us: int
    end_us: int
    slot_width_us: int

    def __post_init__(self) -> None:
        if self.start_us < 0 or self.end_us <= self.start_us:
            raise ValueError("time window must be non-empty and non-negative")
        if self.slot_width_us <= 0:
            raise ValueError("slot_width_us must be positive")
        if (self.end_us - self.start_us) % self.slot_width_us:
            raise ValueError("window length must be divisible by slot_width_us")

    @property
    def slot_count(self) -> int:
        """! @brief 返回窗口中的离散时隙数量。"""
        return (self.end_us - self.start_us) // self.slot_width_us


@dataclass(frozen=True, slots=True)
class NetworkModel:
    """! @brief 已完成单位归一化、可直接供优化层消费的网络。"""

    messages: tuple[CanMessage, ...]
    channel: ChannelConfig
    hyperperiod_us: int
    startup_window: TimeWindow
    steady_window: TimeWindow
    weight_mode: WeightMode
    warnings: tuple[str, ...] = ()
    field_sources: tuple[tuple[str, str], ...] = ()
    input_files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("network must contain at least one periodic message")
        if self.hyperperiod_us <= 0:
            raise ValueError("hyperperiod_us must be positive")
        if self.steady_window.end_us - self.steady_window.start_us != self.hyperperiod_us:
            raise ValueError("steady window length must equal hyperperiod_us")
        if self.startup_window.start_us != 0:
            raise ValueError("startup window must begin at zero")
        if self.steady_window.start_us != self.startup_window.end_us:
            raise ValueError("steady window must begin where startup window ends")
        if self.startup_window.slot_width_us != self.steady_window.slot_width_us:
            raise ValueError("startup and steady windows must use the same slot width")
        maximum_offset = max(
            max(message.allowed_offsets_us) for message in self.messages
        )
        if self.startup_window.end_us != maximum_offset:
            raise ValueError("startup window must end at the maximum legal Offset")
        if any(
            offset % self.steady_window.slot_width_us
            for message in self.messages
            for offset in message.allowed_offsets_us
        ):
            raise ValueError("all legal Offsets must align to the slot width")
        if any(
            self.hyperperiod_us % message.cycle_time_us for message in self.messages
        ):
            raise ValueError("hyperperiod must be a multiple of every message cycle")
        names = [message.name for message in self.messages]
        if len(names) != len(set(names)):
            raise ValueError("message names must be unique")

    @property
    def average_load(self) -> float:
        """! @brief 返回 Offset 无法改变的长期平均总线负载。"""
        return sum(message.frame_time_us / message.cycle_time_us for message in self.messages)


@dataclass(frozen=True, slots=True)
class OffsetAssignment:
    """! @brief 一条报文的最终 Offset 分配。"""

    message_name: str
    can_id: int
    offset_us: int


@dataclass(frozen=True, slots=True, order=True)
class ObjectiveValue:
    """! @brief 按设计优先级可直接词典序比较的目标值。"""

    violation_count: int
    violation_excess: int
    steady_peak: int
    startup_peak: int
    sum_square_load: int
    max_release_count: int

    def __post_init__(self) -> None:
        if min(self.as_tuple()) < 0:
            raise ValueError("objective components must be non-negative")

    def as_tuple(self) -> tuple[int, int, int, int, int, int]:
        """! @brief 返回固定顺序的目标比较键。"""
        return (
            self.violation_count,
            self.violation_excess,
            self.steady_peak,
            self.startup_peak,
            self.sum_square_load,
            self.max_release_count,
        )


@dataclass(frozen=True, slots=True)
class RestartRecord:
    """! @brief 一次可复现重启的 seed 与结果。"""

    seed: int
    objective: ObjectiveValue


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """! @brief GCLS 结果及报告所需的全部已计算指标。"""

    messages: tuple[CanMessage, ...]
    assignments: tuple[OffsetAssignment, ...]
    objective: ObjectiveValue
    initial_objective: ObjectiveValue
    greedy_objective: ObjectiveValue
    steady_slot_loads: tuple[int, ...]
    startup_slot_loads: tuple[int, ...]
    steady_slot_counts: tuple[int, ...]
    startup_slot_counts: tuple[int, ...]
    restart_records: tuple[RestartRecord, ...]
    evaluation_count: int
    accepted_moves: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        message_by_name = {message.name: message for message in self.messages}
        if len(message_by_name) != len(self.messages):
            raise ValueError("result message names must be unique")
        if {assignment.message_name for assignment in self.assignments} != set(
            message_by_name
        ) or len(self.assignments) != len(self.messages):
            raise ValueError("result must assign every message exactly once")
        for assignment in self.assignments:
            message = message_by_name[assignment.message_name]
            if assignment.can_id != message.can_id:
                raise ValueError(f"result CAN ID mismatch for {message.name}")
            if assignment.offset_us not in message.allowed_offsets_us:
                raise ValueError(f"result Offset is illegal for {message.name}")
        if len(self.steady_slot_loads) != len(self.steady_slot_counts):
            raise ValueError("steady load/count arrays must have equal length")
        if len(self.startup_slot_loads) != len(self.startup_slot_counts):
            raise ValueError("startup load/count arrays must have equal length")
        arrays = (
            self.steady_slot_loads,
            self.startup_slot_loads,
            self.steady_slot_counts,
            self.startup_slot_counts,
        )
        if any(value < 0 for array in arrays for value in array):
            raise ValueError("result load/count arrays must be non-negative")
        if self.objective > self.greedy_objective or self.objective > self.initial_objective:
            raise ValueError("optimized objective must not be worse than its baselines")
        if (
            self.evaluation_count < 0
            or self.accepted_moves < 0
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("result statistics must be non-negative")

    def offset_by_name(self) -> dict[str, int]:
        """! @brief 返回便于查询的报文名到 Offset 映射副本。"""
        return {item.message_name: item.offset_us for item in self.assignments}


@dataclass(frozen=True, slots=True)
class RunSummary:
    """! @brief 可序列化运行摘要的显式容器。"""

    data: dict[str, Any] = field(default_factory=dict)


def lcm(values: tuple[int, ...]) -> int:
    """! @brief 计算正整数元组的最小公倍数。

    @raises ValueError 当输入为空或含非正整数时抛出。
    """
    if not values or any(value <= 0 for value in values):
        raise ValueError("LCM requires non-empty positive integers")

    def pair(left: int, right: int) -> int:
        return left // gcd(left, right) * right

    return reduce(pair, values)
