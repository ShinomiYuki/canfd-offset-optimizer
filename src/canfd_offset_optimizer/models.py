"""! @file models.py
@brief 与 DBC、ARXML 库解耦的领域模型。

@details
核心时间量全部使用整数微秒；搜索状态以外的公共对象均不可变。

@author 篠見由紀
"""

from __future__ import annotations

import hashlib
import json
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


class ObjectiveMode(str, Enum):
    """! @brief 负载均衡目标的固定安全优先级模式。"""

    PEAK = "peak"
    BALANCED = "balanced"
    VARIANCE = "variance"


class PeakToleranceType(str, Enum):
    """! @brief balanced 峰值预算的宽容量表达方式。"""

    RELATIVE = "relative"
    ABSOLUTE = "absolute"


class RestartMode(str, Enum):
    """! @brief GCLS 尝试次数的固定或确定性自适应策略。"""

    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class RestartAttemptKind(str, Enum):
    """! @brief 一次 GCLS 尝试使用确定性或随机化顺序。"""

    DETERMINISTIC = "deterministic"
    RANDOM = "random"


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
    cli_overrides: tuple[tuple[str, str], ...] = ()

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
    definition_index: int = 0

    def __post_init__(self) -> None:
        if not self.message_name.strip():
            raise ValueError("assignment message_name must be non-empty")
        if not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("assignment CAN ID is outside the CAN identifier range")
        if self.offset_us < 0 or self.definition_index < 0:
            raise ValueError("assignment Offset/index must be non-negative")


@dataclass(frozen=True, slots=True)
class ObjectiveValue:
    """! @brief 完整原始指标及由目标模式决定的词典序比较键。"""

    violation_count: int
    violation_excess: int
    steady_peak: int
    startup_peak: int
    sum_square_load: int
    max_release_count: int
    startup_sum_square_load: int = 0
    mode: ObjectiveMode = ObjectiveMode.PEAK
    peak_budget_us: int | None = None

    def __post_init__(self) -> None:
        if min(self.metrics_tuple()) < 0:
            raise ValueError("objective components must be non-negative")
        if self.mode is ObjectiveMode.BALANCED:
            if self.peak_budget_us is None or self.peak_budget_us <= 0:
                raise ValueError("balanced objective requires a positive peak budget")
        elif self.peak_budget_us is not None:
            raise ValueError("peak budget is only valid for balanced objective")

    @property
    def peak_budget_excess(self) -> int:
        """! @brief 返回稳态峰值超过 balanced 预算的微秒数。"""
        if self.peak_budget_us is None:
            return 0
        return max(0, self.steady_peak - self.peak_budget_us)

    @property
    def priorities(self) -> tuple[str, ...]:
        """! @brief 返回当前模式固定且可审计的指标顺序。"""
        common = ("violation_count", "violation_excess")
        if self.mode is ObjectiveMode.PEAK:
            return common + (
                "steady_peak",
                "steady_sum_square_load",
                "startup_peak",
                "startup_sum_square_load",
                "max_release_count",
            )
        if self.mode is ObjectiveMode.BALANCED:
            return common + (
                "peak_budget_excess",
                "steady_sum_square_load",
                "steady_peak",
                "startup_peak",
                "startup_sum_square_load",
                "max_release_count",
            )
        return common + (
            "steady_sum_square_load",
            "steady_peak",
            "startup_peak",
            "startup_sum_square_load",
            "max_release_count",
        )

    def metrics_tuple(self) -> tuple[int, int, int, int, int, int, int]:
        """! @brief 返回与模式无关的完整原始指标。"""
        return (
            self.violation_count,
            self.violation_excess,
            self.steady_peak,
            self.sum_square_load,
            self.startup_peak,
            self.startup_sum_square_load,
            self.max_release_count,
        )

    def as_tuple(self) -> tuple[int, ...]:
        """! @brief 返回当前模式实际使用的词典序比较键。"""
        values = {
            "violation_count": self.violation_count,
            "violation_excess": self.violation_excess,
            "peak_budget_excess": self.peak_budget_excess,
            "steady_peak": self.steady_peak,
            "steady_sum_square_load": self.sum_square_load,
            "startup_peak": self.startup_peak,
            "startup_sum_square_load": self.startup_sum_square_load,
            "max_release_count": self.max_release_count,
        }
        return tuple(values[name] for name in self.priorities)

    def _check_comparable(self, other: object) -> ObjectiveValue:
        if not isinstance(other, ObjectiveValue):
            raise TypeError(f"cannot compare ObjectiveValue with {type(other).__name__}")
        if (self.mode, self.peak_budget_us) != (other.mode, other.peak_budget_us):
            raise ValueError("objectives from different modes or budgets are incomparable")
        return other

    def __lt__(self, other: object) -> bool:
        checked = self._check_comparable(other)
        return self.as_tuple() < checked.as_tuple()

    def __le__(self, other: object) -> bool:
        checked = self._check_comparable(other)
        return self.as_tuple() <= checked.as_tuple()

    def __gt__(self, other: object) -> bool:
        checked = self._check_comparable(other)
        return self.as_tuple() > checked.as_tuple()

    def __ge__(self, other: object) -> bool:
        checked = self._check_comparable(other)
        return self.as_tuple() >= checked.as_tuple()


@dataclass(frozen=True, slots=True)
class RestartRecord:
    """! @brief 一次可复现尝试的完整、自包含审计记录。"""

    attempt_index: int
    attempt_kind: RestartAttemptKind
    seed: int
    objective: ObjectiveValue
    assignments: tuple[OffsetAssignment, ...]
    assignment_hash: str
    elapsed_seconds: float = field(compare=False)
    evaluation_count: int
    accepted_moves: int

    def __post_init__(self) -> None:
        if self.attempt_index < 0:
            raise ValueError("restart attempt_index must be non-negative")
        if not isinstance(self.attempt_kind, RestartAttemptKind):
            raise ValueError("restart attempt_kind is invalid")
        if not self.assignments:
            raise ValueError("restart record requires a complete assignment")
        if len({item.message_name for item in self.assignments}) != len(
            self.assignments
        ):
            raise ValueError("restart assignment message names must be unique")
        if self.assignment_hash != hash_offset_assignments(self.assignments):
            raise ValueError("restart assignment hash mismatch")
        if (
            not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
            or self.evaluation_count < 0
            or self.accepted_moves < 0
        ):
            raise ValueError("restart statistics must be finite and non-negative")


def hash_offset_assignments(assignments: tuple[OffsetAssignment, ...]) -> str:
    """Return a stable SHA-256 over the canonical assignment sequence."""
    canonical = [
        [
            item.definition_index,
            item.can_id,
            item.message_name,
            item.offset_us,
        ]
        for item in sorted(
            assignments,
            key=lambda item: (
                item.definition_index,
                item.can_id,
                item.message_name,
            ),
        )
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def steady_phase_vector(
    assignments: tuple[OffsetAssignment, ...],
    messages: tuple[CanMessage, ...],
) -> tuple[int, ...]:
    """Return canonical ``Offset mod Cycle`` values for a complete assignment."""
    cycle_by_key = {
        (message.definition_index, message.can_id, message.name): message.cycle_time_us
        for message in messages
    }
    ordered = sorted(
        assignments,
        key=lambda item: (item.definition_index, item.can_id, item.message_name),
    )
    try:
        return tuple(
            item.offset_us
            % cycle_by_key[(item.definition_index, item.can_id, item.message_name)]
            for item in ordered
        )
    except KeyError as exc:
        raise ValueError("assignment does not match the message set") from exc


def hash_steady_phases(phases: tuple[int, ...]) -> str:
    """Return a stable SHA-256 over a canonical steady-phase vector."""
    encoded = json.dumps(phases, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PeakCandidate:
    """! @brief 一个可审计的 Peak 局部最优 assignment 候选。"""

    source_attempt_index: int
    source_seed: int | None
    objective: ObjectiveValue
    assignments: tuple[OffsetAssignment, ...]
    assignment_hash: str
    steady_phases: tuple[int, ...]
    steady_phase_hash: str

    def __post_init__(self) -> None:
        if self.source_attempt_index < -1:
            raise ValueError("peak candidate source attempt must be -1 or non-negative")
        if self.objective.mode is not ObjectiveMode.PEAK:
            raise ValueError("peak candidate objective must use peak mode")
        if not self.assignments or len(self.assignments) != len(self.steady_phases):
            raise ValueError("peak candidate requires one steady phase per assignment")
        if self.assignment_hash != hash_offset_assignments(self.assignments):
            raise ValueError("peak candidate assignment hash mismatch")
        if self.steady_phase_hash != hash_steady_phases(self.steady_phases):
            raise ValueError("peak candidate steady-phase hash mismatch")


@dataclass(frozen=True, slots=True)
class TripleMoveAudit:
    """! @brief 一轮冲突导向三报文联合重定位的完整审计记录。"""

    round_index: int
    message_names: tuple[str, str, str]
    can_ids: tuple[int, int, int]
    old_offsets_us: tuple[int, int, int]
    new_offsets_us: tuple[int, int, int]
    objective_before: ObjectiveValue
    objective_after_move: ObjectiveValue
    objective_after_cleanup: ObjectiveValue
    checked_triplets: int
    checked_offset_combinations: int
    cleanup_evaluations: int
    cleanup_accepted_moves: int
    elapsed_seconds: float = field(compare=False)

    def __post_init__(self) -> None:
        if self.round_index < 0 or len(set(self.message_names)) != 3:
            raise ValueError("triple move requires one valid round and three messages")
        if any(offset < 0 for offset in self.old_offsets_us + self.new_offsets_us):
            raise ValueError("triple move Offsets must be non-negative")
        if any(
            new == old
            for old, new in zip(
                self.old_offsets_us, self.new_offsets_us, strict=True
            )
        ):
            raise ValueError("triple move must relocate all three messages")
        if not self.objective_after_move < self.objective_before:
            raise ValueError("triple move must strictly improve the active objective")
        if self.objective_after_cleanup > self.objective_after_move:
            raise ValueError("post-triple cleanup must not worsen the objective")
        if (
            self.checked_triplets <= 0
            or self.checked_offset_combinations <= 0
            or self.cleanup_evaluations < 0
            or self.cleanup_accepted_moves < 0
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("triple move audit statistics are invalid")


@dataclass(frozen=True, slots=True)
class TripleSearchTimings:
    """! @brief 三报文搜索各阶段的重叠与非重叠墙钟时间。"""

    contribution_precompute_seconds: float
    candidate_selection_seconds: float
    enumeration_seconds: float
    state_mutation_rollback_seconds: float
    objective_evaluation_seconds: float
    cleanup_seconds: float
    total_seconds: float

    def __post_init__(self) -> None:
        values = (
            self.contribution_precompute_seconds,
            self.candidate_selection_seconds,
            self.enumeration_seconds,
            self.state_mutation_rollback_seconds,
            self.objective_evaluation_seconds,
            self.cleanup_seconds,
            self.total_seconds,
        )
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("triple search phase timings must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class TripleSearchAudit:
    """! @brief 一次三报文搜索的终止原因、工作量与已接受移动。"""

    candidate_cap: int
    max_rounds: int
    hot_slot_count: int
    checked_triplets: int
    checked_offset_combinations: int
    accepted_moves: int
    elapsed_seconds: float = field(compare=False)
    stop_reason: str
    rounds: tuple[TripleMoveAudit, ...] = ()
    timings: TripleSearchTimings | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not 6 <= self.candidate_cap <= 8:
            raise ValueError("triple candidate cap must be in [6, 8]")
        if self.max_rounds <= 0 or self.hot_slot_count <= 0:
            raise ValueError("triple search round/slot limits must be positive")
        if (
            self.checked_triplets < 0
            or self.checked_offset_combinations < 0
            or self.accepted_moves != len(self.rounds)
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
            or not self.stop_reason.strip()
        ):
            raise ValueError("triple search audit summary is invalid")
        if self.checked_triplets < sum(item.checked_triplets for item in self.rounds):
            raise ValueError("triple search triplet total is inconsistent")
        if self.checked_offset_combinations < sum(
            item.checked_offset_combinations for item in self.rounds
        ):
            raise ValueError("triple search Offset total is inconsistent")
        if self.timings is not None and abs(
            self.timings.total_seconds - self.elapsed_seconds
        ) > max(0.001, self.elapsed_seconds * 0.01):
            raise ValueError("triple search total timing is inconsistent")


@dataclass(frozen=True, slots=True)
class BalancedCandidateSearchRecord:
    """! @brief 从一个 Peak 候选执行一次现有 Balanced 局部搜索的审计记录。"""

    pool_index: int
    source_attempt_index: int
    source_seed: int | None
    candidate_assignment_hash: str
    candidate_steady_phase_hash: str
    objective_before: ObjectiveValue
    objective_after: ObjectiveValue
    result_assignments: tuple[OffsetAssignment, ...]
    result_assignment_hash: str
    strictly_improved: bool
    elapsed_seconds: float = field(compare=False)
    evaluation_count: int
    accepted_moves: int
    triple_search_audit: TripleSearchAudit | None = None

    def __post_init__(self) -> None:
        if self.pool_index < 0 or self.source_attempt_index < -1:
            raise ValueError("balanced candidate search indices are invalid")
        if (
            self.objective_before.mode is not ObjectiveMode.BALANCED
            or self.objective_after.mode is not ObjectiveMode.BALANCED
            or self.objective_before.peak_budget_us
            != self.objective_after.peak_budget_us
        ):
            raise ValueError("balanced candidate objectives must share one budget")
        if self.strictly_improved != (self.objective_after < self.objective_before):
            raise ValueError("balanced candidate improvement flag is inconsistent")
        if self.result_assignment_hash != hash_offset_assignments(
            self.result_assignments
        ):
            raise ValueError("balanced candidate result hash mismatch")
        if (
            not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
            or self.evaluation_count < 0
            or self.accepted_moves < 0
        ):
            raise ValueError("balanced candidate statistics must be non-negative")


@dataclass(frozen=True, slots=True)
class RestartExecutionSummary:
    """! @brief 一次 GCLS 运行实际采用的尝试数与停止原因。"""

    mode: RestartMode
    actual_attempts: int
    stop_reason: str
    max_attempts_reached: bool = False
    saturation_verified: bool = False

    def __post_init__(self) -> None:
        if self.actual_attempts <= 0:
            raise ValueError("restart actual_attempts must be positive")
        if not self.stop_reason.strip():
            raise ValueError("restart stop_reason must be non-empty")
        if self.saturation_verified:
            raise ValueError(
                "a single GCLS run cannot claim restart saturation verification"
            )


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
    restart_execution: RestartExecutionSummary
    evaluation_count: int
    accepted_moves: int
    elapsed_seconds: float
    peak_reference_objective: ObjectiveValue | None = None
    peak_budget_us: int | None = None
    peak_reference_restart_records: tuple[RestartRecord, ...] = ()
    peak_reference_evaluation_count: int = 0
    peak_reference_elapsed_seconds: float = 0.0
    balanced_fallback_reason: str | None = None
    pre_restart_objective: ObjectiveValue | None = None
    pre_restart_assignments: tuple[OffsetAssignment, ...] = ()
    peak_candidate_archive: tuple[PeakCandidate, ...] = ()
    selected_peak_candidates: tuple[PeakCandidate, ...] = ()
    balanced_candidate_searches: tuple[BalancedCandidateSearchRecord, ...] = ()

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
            if assignment.definition_index != message.definition_index:
                raise ValueError(f"result definition index mismatch for {message.name}")
            if assignment.offset_us not in message.allowed_offsets_us:
                raise ValueError(f"result Offset is illegal for {message.name}")
        expected_names = set(message_by_name)
        for candidate in self.peak_candidate_archive + self.selected_peak_candidates:
            if {item.message_name for item in candidate.assignments} != expected_names:
                raise ValueError("Peak candidate must assign every result message")
            if candidate.steady_phases != steady_phase_vector(
                candidate.assignments, self.messages
            ):
                raise ValueError("Peak candidate steady phases do not match Offset mod Cycle")
            for item in candidate.assignments:
                message = message_by_name[item.message_name]
                if (
                    item.can_id != message.can_id
                    or item.definition_index != message.definition_index
                    or item.offset_us not in message.allowed_offsets_us
                ):
                    raise ValueError("Peak candidate contains an invalid assignment")
        for record in self.restart_records:
            if {item.message_name for item in record.assignments} != expected_names:
                raise ValueError("restart record must assign every result message")
            for item in record.assignments:
                message = message_by_name[item.message_name]
                if item.can_id != message.can_id:
                    raise ValueError("restart record CAN ID mismatch")
                if item.definition_index != message.definition_index:
                    raise ValueError("restart record definition index mismatch")
                if item.offset_us not in message.allowed_offsets_us:
                    raise ValueError("restart record contains an illegal Offset")
            if (record.objective.mode, record.objective.peak_budget_us) != (
                self.objective.mode,
                self.objective.peak_budget_us,
            ):
                raise ValueError("restart record objective policy mismatch")
        if len(self.restart_records) != self.restart_execution.actual_attempts:
            raise ValueError("restart record count disagrees with execution summary")
        if (self.pre_restart_objective is None) != (not self.pre_restart_assignments):
            raise ValueError("pre-restart objective and assignments must appear together")
        if self.pre_restart_assignments and {
            item.message_name for item in self.pre_restart_assignments
        } != expected_names:
            raise ValueError("pre-restart incumbent must assign every result message")
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
        if (
            self.objective.mode is not ObjectiveMode.BALANCED
            and (
                self.objective > self.greedy_objective
                or self.objective > self.initial_objective
            )
        ):
            raise ValueError("optimized objective must not be worse than its baselines")
        if (
            self.evaluation_count < 0
            or self.accepted_moves < 0
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("result statistics must be non-negative")
        if self.objective.mode is ObjectiveMode.BALANCED:
            if (
                self.peak_reference_objective is None
                or self.peak_reference_objective.mode is not ObjectiveMode.PEAK
                or self.peak_budget_us != self.objective.peak_budget_us
            ):
                raise ValueError("balanced result requires its peak reference and budget")
            if self.balanced_fallback_reason is not None and not (
                self.balanced_fallback_reason.strip()
            ):
                raise ValueError("balanced fallback reason must be non-empty")
            if len(self.selected_peak_candidates) != len(
                self.balanced_candidate_searches
            ):
                raise ValueError("balanced candidate pool/search count mismatch")
            for index, (candidate, search) in enumerate(
                zip(
                    self.selected_peak_candidates,
                    self.balanced_candidate_searches,
                    strict=True,
                )
            ):
                if (
                    search.pool_index != index
                    or search.candidate_assignment_hash != candidate.assignment_hash
                    or search.candidate_steady_phase_hash
                    != candidate.steady_phase_hash
                ):
                    raise ValueError("balanced candidate audit source mismatch")
                if {item.message_name for item in search.result_assignments} != expected_names:
                    raise ValueError("balanced candidate search result is incomplete")
        elif (
            self.peak_reference_objective is not None
            or self.peak_budget_us is not None
            or self.balanced_fallback_reason is not None
        ):
            raise ValueError("only balanced result may contain a peak reference")
        if self.objective.mode is not ObjectiveMode.BALANCED and (
            self.selected_peak_candidates or self.balanced_candidate_searches
        ):
            raise ValueError("only balanced results may contain candidate searches")

    def offset_by_name(self) -> dict[str, int]:
        """! @brief 返回便于查询的报文名到 Offset 映射副本。"""
        return {item.message_name: item.offset_us for item in self.assignments}

    @property
    def assignment_hash(self) -> str:
        """Return the canonical SHA-256 of the final assignment."""
        return hash_offset_assignments(self.assignments)


@dataclass(frozen=True, slots=True)
class ComparisonStageResult:
    """! @brief 一个基线或算法阶段的完整不可变状态快照。"""

    name: str
    kind: str
    assignments: tuple[OffsetAssignment, ...]
    objective: ObjectiveValue
    steady_slot_loads: tuple[int, ...]
    startup_slot_loads: tuple[int, ...]
    steady_slot_counts: tuple[int, ...]
    startup_slot_counts: tuple[int, ...]
    evaluation_count: int
    accepted_moves: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if not self.name or self.kind not in {"baseline", "algorithm"}:
            raise ValueError("comparison stage name/kind is invalid")
        if len(self.steady_slot_loads) != len(self.steady_slot_counts):
            raise ValueError("steady comparison arrays must have equal length")
        if len(self.startup_slot_loads) != len(self.startup_slot_counts):
            raise ValueError("startup comparison arrays must have equal length")
        arrays = (
            self.steady_slot_loads,
            self.startup_slot_loads,
            self.steady_slot_counts,
            self.startup_slot_counts,
        )
        if any(value < 0 for array in arrays for value in array):
            raise ValueError("comparison arrays must be non-negative")
        if (
            self.evaluation_count < 0
            or self.accepted_moves < 0
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("comparison statistics must be non-negative")

    def offset_by_name(self) -> dict[str, int]:
        """! @brief 返回该阶段报文名到 Offset 的映射副本。"""
        return {item.message_name: item.offset_us for item in self.assignments}


@dataclass(frozen=True, slots=True)
class AlgorithmComparisonResult:
    """! @brief 固定顺序的多阶段算法对比结果。"""

    messages: tuple[CanMessage, ...]
    stages: tuple[ComparisonStageResult, ...]
    restart_records: tuple[RestartRecord, ...]
    restart_execution: RestartExecutionSummary
    seed: int
    peak_reference_objective: ObjectiveValue | None = None
    peak_budget_us: int | None = None
    peak_reference_restart_records: tuple[RestartRecord, ...] = ()
    peak_reference_evaluation_count: int = 0
    peak_reference_elapsed_seconds: float = 0.0
    balanced_fallback_reason: str | None = None
    peak_candidate_archive: tuple[PeakCandidate, ...] = ()
    selected_peak_candidates: tuple[PeakCandidate, ...] = ()
    balanced_candidate_searches: tuple[BalancedCandidateSearchRecord, ...] = ()

    def __post_init__(self) -> None:
        expected = ("original", "minimum", "greedy", "greedy_1opt", "gcls")
        if tuple(stage.name for stage in self.stages) != expected:
            raise ValueError(f"comparison stages must be ordered as {expected}")
        if len(self.restart_records) != self.restart_execution.actual_attempts:
            raise ValueError("comparison restart record count is inconsistent")
        message_names = {message.name for message in self.messages}
        if len(message_names) != len(self.messages):
            raise ValueError("comparison message names must be unique")
        for stage in self.stages:
            assignments = stage.offset_by_name()
            if set(assignments) != message_names or len(stage.assignments) != len(
                self.messages
            ):
                raise ValueError(f"stage {stage.name} must assign every message once")
            for message in self.messages:
                if assignments[message.name] not in message.allowed_offsets_us:
                    raise ValueError(f"stage {stage.name} has illegal Offset for {message.name}")
        if self.stage("gcls").objective.mode is ObjectiveMode.BALANCED:
            if self.peak_reference_objective is None or self.peak_budget_us is None:
                raise ValueError("balanced comparison requires peak reference metadata")
            objective = self.stage("gcls").objective
            reference = self.peak_reference_objective
            if (
                (objective.violation_count, objective.violation_excess)
                > (reference.violation_count, reference.violation_excess)
                or objective.steady_peak > self.peak_budget_us
                or objective.sum_square_load > reference.sum_square_load
            ):
                raise ValueError("balanced comparison violates peak-reference guarantees")
            if len(self.selected_peak_candidates) != len(
                self.balanced_candidate_searches
            ):
                raise ValueError("balanced comparison candidate pool/search mismatch")
        elif (
            self.peak_reference_objective is not None
            or self.peak_budget_us is not None
            or self.peak_reference_restart_records
            or self.balanced_fallback_reason is not None
        ):
            raise ValueError("only balanced comparison may contain peak reference metadata")
        if self.stage("gcls").objective.mode is not ObjectiveMode.BALANCED and (
            self.selected_peak_candidates or self.balanced_candidate_searches
        ):
            raise ValueError("only balanced comparison may contain candidate searches")

    def stage(self, name: str) -> ComparisonStageResult:
        """! @brief 按稳定名称查询一个阶段。"""
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)


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
