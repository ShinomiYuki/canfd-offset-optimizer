"""Pure display ViewModel for one network and one heatmap window."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache

from canfd_offset_optimizer.models import FrameProtocol as CoreFrameProtocol
from canfd_offset_optimizer.timing.conservative_service import (
    CONSERVATIVE_ESTIMATOR_VERSION,
    ConservativeEstimateStatus,
    ConservativeFrameEstimate,
    estimate_conservative_bus_service_time,
)

from .contracts import (
    GuiOptimizationResult,
    HeatmapMessageDetail,
    HeatmapWindowDetail,
    NetworkTimingConfig,
    WeightMode,
)


class HeatmapState(str, Enum):
    ORIGINAL = "original"
    OPTIMIZED = "optimized"

    @property
    def label(self) -> str:
        return "原始" if self is HeatmapState.ORIGINAL else "优化后"

    @property
    def sort_order(self) -> int:
        return 0 if self is HeatmapState.ORIGINAL else 1


class HeatmapWindowKind(str, Enum):
    STEADY = "steady"
    STARTUP = "startup"

    @property
    def label(self) -> str:
        return "稳态窗口" if self is HeatmapWindowKind.STEADY else "启动窗口"


class CongestionTableMode(str, Enum):
    """Explicit detail-table state; table contents never imply the mode."""

    ALL_CONGESTED = "all_congested"
    SELECTED_SLOT = "selected_slot"


@dataclass(frozen=True, slots=True)
class HeatmapCellSelection:
    """Stable identity for one selectable cell in one bound result view."""

    network_id: str
    window_kind: HeatmapWindowKind
    state: HeatmapState
    slot_index: int

    def __post_init__(self) -> None:
        if not self.network_id.strip():
            raise ValueError("heatmap cell selection requires a network identity")
        if not isinstance(self.window_kind, HeatmapWindowKind):
            raise ValueError("heatmap cell selection window is invalid")
        if not isinstance(self.state, HeatmapState):
            raise ValueError("heatmap cell selection state is invalid")
        if self.slot_index < 0:
            raise ValueError("heatmap cell selection slot is invalid")


@dataclass(frozen=True, slots=True)
class HeatmapCellView:
    state: HeatmapState
    slot_index: int
    start_us: int
    end_us: int
    frame_count: int
    total_load: int
    messages: tuple[HeatmapMessageDetail, ...]
    load_unit: str
    conservative_total_time_us: int | None
    conservative_complete_count: int
    conservative_total_count: int
    conservative_unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.slot_index < 0 or self.start_us < 0 or self.end_us <= self.start_us:
            raise ValueError("heatmap cell coordinates are invalid")
        if self.frame_count < 0 or self.total_load < 0:
            raise ValueError("heatmap cell count/load must be non-negative")
        if len(self.messages) != self.frame_count:
            raise ValueError(
                "presentation/result data inconsistency: heatmap members do not "
                "match frame_count"
            )
        if not (
            0
            <= self.conservative_complete_count
            <= self.conservative_total_count
            == self.frame_count
        ):
            raise ValueError("heatmap conservative completeness is invalid")
        if self.frame_count == 0 and self.conservative_total_time_us != 0:
            raise ValueError("empty heatmap cell conservative total must be zero")
        if self.frame_count > 0 and self.conservative_complete_count == 0:
            if self.conservative_total_time_us is not None:
                raise ValueError("unavailable heatmap cell must not report zero time")
        elif self.conservative_total_time_us is None:
            raise ValueError("known heatmap conservative total is missing")

    @property
    def start_ms(self) -> float:
        return self.start_us / 1_000

    @property
    def end_ms(self) -> float:
        return self.end_us / 1_000

    @property
    def conservative_text(self) -> str:
        if self.frame_count == 0:
            return "保守 0 μs"
        if self.conservative_complete_count == 0:
            return "保守 —"
        assert self.conservative_total_time_us is not None
        if self.conservative_complete_count < self.conservative_total_count:
            return f"保守 ≥{self.conservative_total_time_us} μs*"
        return f"保守 {self.conservative_total_time_us} μs"

    @property
    def text(self) -> str:
        if self.frame_count == 0:
            return ""
        return (
            f"{self.frame_count} 帧\n"
            f"{self.total_load} {self.load_unit}\n"
            f"{self.conservative_text}"
        )

    @property
    def tooltip(self) -> str:
        lines = [
            f"状态：{self.state.label}",
            f"时间：[{_format_ms(self.start_ms)}, {_format_ms(self.end_ms)}) ms",
            f"帧数：{self.frame_count}",
            f"当前权重负载：{self.total_load} {self.load_unit}",
        ]
        if self.frame_count == 0:
            lines.extend(("保守占用时间：0 μs", "计算完整度：0/0"))
        elif self.conservative_complete_count == 0:
            lines.extend(
                (
                    "保守占用时间：—",
                    f"计算完整度：0/{self.conservative_total_count}",
                    "原因：" + _reasons_text(self.conservative_unavailable_reasons),
                )
            )
        elif self.conservative_complete_count < self.conservative_total_count:
            assert self.conservative_total_time_us is not None
            lines.extend(
                (
                    f"保守已知占用：≥{self.conservative_total_time_us} μs",
                    "计算完整度："
                    f"{self.conservative_complete_count}/{self.conservative_total_count}",
                    "缺失："
                    f"{self.conservative_total_count - self.conservative_complete_count} 帧",
                    "原因：" + _reasons_text(self.conservative_unavailable_reasons),
                )
            )
        else:
            assert self.conservative_total_time_us is not None
            lines.extend(
                (
                    f"保守占用时间：{self.conservative_total_time_us} μs",
                    "计算完整度："
                    f"{self.conservative_complete_count}/{self.conservative_total_count}",
                )
            )
        lines.append("CAN FD 保守值整帧按 nominal bitrate 计时，不是实际帧时间。")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class CongestedMessageRow:
    state: HeatmapState
    slot_index: int
    start_us: int
    end_us: int
    frame_count: int
    total_load: int
    load_unit: str
    message: HeatmapMessageDetail

    @property
    def time_text(self) -> str:
        return f"{_format_ms(self.start_us / 1_000)}～{_format_ms(self.end_us / 1_000)} ms"

    @property
    def total_load_text(self) -> str:
        return f"{self.total_load} {self.load_unit}"

    @property
    def can_id_text(self) -> str:
        return f"0x{self.message.can_id:X}"

    @property
    def period_text(self) -> str:
        return f"{_format_ms(self.message.cycle_time_us / 1_000)} ms"

    @property
    def offset_text(self) -> str:
        return f"{_format_ms(self.message.offset_us / 1_000)} ms"

    @property
    def payload_text(self) -> str:
        return "—" if self.message.payload_bytes is None else str(self.message.payload_bytes)

    @property
    def conservative_time_text(self) -> str:
        value = self.message.conservative_service_time_us
        return "—" if value is None else str(value)

    @property
    def conservative_tooltip(self) -> str:
        if self.message.conservative_service_time_us is not None:
            return "协议级保守占用时间；包含正常 3-bit Intermission。"
        return _reason_label(self.message.conservative_unavailable_reason)


@dataclass(frozen=True, slots=True)
class HeatmapViewModel:
    network_id: str
    display_name: str
    source_file: str
    window_kind: HeatmapWindowKind
    slot_width_us: int
    load_unit: str
    timing_config: NetworkTimingConfig
    original_cells: tuple[HeatmapCellView, ...]
    optimized_cells: tuple[HeatmapCellView, ...]
    congested_rows: tuple[CongestedMessageRow, ...]

    @property
    def slot_count(self) -> int:
        return len(self.original_cells)

    @property
    def duration_ms(self) -> float:
        return self.slot_count * self.slot_width_us / 1_000

    def cells_for(self, state: HeatmapState) -> tuple[HeatmapCellView, ...]:
        return self.original_cells if state is HeatmapState.ORIGINAL else self.optimized_cells

    def cell_for(self, selection: HeatmapCellSelection) -> HeatmapCellView:
        if selection.network_id != self.network_id:
            raise ValueError("selected heatmap cell belongs to another network")
        if selection.window_kind is not self.window_kind:
            raise ValueError("selected heatmap cell belongs to another window")
        cells = self.cells_for(selection.state)
        if not 0 <= selection.slot_index < len(cells):
            raise ValueError("selected heatmap cell slot is outside the current window")
        return cells[selection.slot_index]

    def selection_for(
        self, state: HeatmapState, slot_index: int
    ) -> HeatmapCellSelection:
        selection = HeatmapCellSelection(
            self.network_id, self.window_kind, state, slot_index
        )
        self.cell_for(selection)
        return selection


def build_heatmap_view_model(
    result: GuiOptimizationResult,
    window_kind: HeatmapWindowKind,
    timing_config: NetworkTimingConfig | None = None,
) -> HeatmapViewModel:
    """Build diagnostics from immutable slot members without rerunning GCLS."""

    load_unit = "B" if result.weight_mode is WeightMode.PAYLOAD_BYTES else "μs"
    config = timing_config or result.network_timing_config or NetworkTimingConfig(
        result.network_id
    )
    if config.network_id != result.network_id:
        raise ValueError("timing config belongs to another network")
    if window_kind is HeatmapWindowKind.STEADY:
        detail = result.steady_heatmap
        before_loads = result.original_steady_load
        after_loads = result.optimized_steady_load
        before_counts = result.original_steady_count
        after_counts = result.optimized_steady_count
    else:
        detail = result.startup_heatmap
        before_loads = result.original_startup_load
        after_loads = result.optimized_startup_load
        before_counts = result.original_startup_count
        after_counts = result.optimized_startup_count
    slot_width_us = result.load_window_metadata.slot_width_us
    original = _state_cells(
        result.network_id,
        HeatmapState.ORIGINAL,
        detail,
        before_loads,
        before_counts,
        slot_width_us,
        load_unit,
        config,
    )
    optimized = _state_cells(
        result.network_id,
        HeatmapState.OPTIMIZED,
        detail,
        after_loads,
        after_counts,
        slot_width_us,
        load_unit,
        config,
    )
    congested = tuple(
        row
        for cells in (original, optimized)
        for cell in cells
        if cell.frame_count >= 4
        for row in message_rows_for_cell(cell)
    )
    return HeatmapViewModel(
        result.network_id,
        result.display_name,
        result.source_file,
        window_kind,
        slot_width_us,
        load_unit,
        config,
        original,
        optimized,
        congested,
    )


def _state_cells(
    network_id: str,
    state: HeatmapState,
    detail: HeatmapWindowDetail | None,
    loads: tuple[int, ...],
    counts: tuple[int, ...],
    slot_width_us: int,
    load_unit: str,
    timing_config: NetworkTimingConfig,
) -> tuple[HeatmapCellView, ...]:
    if len(loads) != len(counts):
        raise ValueError("heatmap load/count arrays do not share one time axis")
    slots = None
    if detail is not None:
        slots = (
            detail.original_slots
            if state is HeatmapState.ORIGINAL
            else detail.optimized_slots
        )
        if len(slots) != len(loads):
            raise ValueError(
                "presentation/result data inconsistency: heatmap member slots do "
                "not align with load arrays"
            )
        for index, (slot, load, count) in enumerate(
            zip(slots, loads, counts, strict=True)
        ):
            if (
                slot.slot_index != index
                or slot.start_us != index * slot_width_us
                or slot.end_us != (index + 1) * slot_width_us
                or slot.frame_count != count
                or slot.total_load != load
            ):
                raise ValueError(
                    "presentation/result data inconsistency: heatmap slot "
                    "aggregate or axis mismatch"
                )
    cells: list[HeatmapCellView] = []
    for index, (load, count) in enumerate(zip(loads, counts, strict=True)):
        raw_messages = slots[index].messages if slots is not None else ()
        messages = tuple(
            _enrich_message(network_id, message, timing_config)
            for message in raw_messages
        )
        known_times = tuple(
            message.conservative_service_time_us
            for message in messages
            if message.conservative_status is ConservativeEstimateStatus.COMPLETE
            and message.conservative_service_time_us is not None
        )
        reasons = tuple(
            dict.fromkeys(
                message.conservative_unavailable_reason or "unknown_reason"
                for message in messages
                if message.conservative_status is ConservativeEstimateStatus.UNAVAILABLE
            )
        )
        complete_count = len(known_times)
        total_count = len(messages)
        conservative_total = (
            0
            if total_count == 0
            else (sum(known_times) if complete_count > 0 else None)
        )
        cells.append(
            HeatmapCellView(
                state,
                index,
                index * slot_width_us,
                (index + 1) * slot_width_us,
                count,
                load,
                messages,
                load_unit,
                conservative_total,
                complete_count,
                total_count,
                reasons,
            )
        )
    return tuple(cells)


def _enrich_message(
    network_id: str,
    message: HeatmapMessageDetail,
    timing_config: NetworkTimingConfig,
) -> HeatmapMessageDetail:
    protocol_value = (
        message.frame_protocol.value if message.frame_protocol is not None else None
    )
    estimate = _cached_estimate(
        network_id,
        message.message_name,
        message.can_id,
        protocol_value,
        message.is_extended,
        message.payload_bytes,
        timing_config.nominal_bitrate_bps,
        CONSERVATIVE_ESTIMATOR_VERSION,
    )
    return replace(
        message,
        conservative_service_time_us=estimate.conservative_bus_service_time_us,
        conservative_total_bits_upper_bound=estimate.total_bits_upper_bound,
        conservative_status=estimate.status,
        conservative_unavailable_reason=estimate.unavailable_reason,
    )


@lru_cache(maxsize=16_384)
def _cached_estimate(
    network_id: str,
    message_name: str,
    can_id: int,
    protocol_value: str | None,
    is_extended: bool,
    payload_bytes: int | None,
    nominal_bitrate_bps: int | None,
    estimator_version: str,
) -> ConservativeFrameEstimate:
    # Identity, network, bitrate and estimator revision are deliberately all in
    # the cache key so a bitrate change cannot reuse stale presentation values.
    del network_id, message_name, can_id, estimator_version
    protocol = (
        CoreFrameProtocol(protocol_value) if protocol_value is not None else None
    )
    return estimate_conservative_bus_service_time(
        protocol=protocol,
        is_extended=is_extended,
        payload_bytes=payload_bytes,
        nominal_bitrate_bps=nominal_bitrate_bps,
    )


def conservative_estimate_cache_info() -> object:
    """Expose cache statistics for focused presentation regression tests."""

    return _cached_estimate.cache_info()


def filter_congested_rows(
    rows: tuple[CongestedMessageRow, ...], mode: str
) -> tuple[CongestedMessageRow, ...]:
    if mode == "all":
        return rows
    if mode == "four":
        return tuple(row for row in rows if row.frame_count == 4)
    if mode == "five_plus":
        return tuple(row for row in rows if row.frame_count >= 5)
    raise ValueError("unsupported congestion filter")


def message_rows_for_cell(
    cell: HeatmapCellView,
) -> tuple[CongestedMessageRow, ...]:
    """Expose exactly the formal member list already attached to one slot."""

    if len(cell.messages) != cell.frame_count:
        raise ValueError(
            "presentation/result data inconsistency: selected slot member count "
            f"{len(cell.messages)} != frame_count {cell.frame_count}"
        )
    return tuple(
        CongestedMessageRow(
            cell.state,
            cell.slot_index,
            cell.start_us,
            cell.end_us,
            cell.frame_count,
            cell.total_load,
            cell.load_unit,
            message,
        )
        for message in cell.messages
    )


def _reason_label(reason: str | None) -> str:
    if reason is None:
        return "无法计算保守占用时间"
    return {
        "missing_nominal_bitrate": "缺少 Nominal Bitrate",
        "invalid_payload_length": "Payload Length 缺失或非法",
        "unknown_protocol": "报文协议类型未知",
        "invalid_frame_metadata": "报文帧格式元数据非法",
    }.get(reason, reason)

def _reasons_text(reasons: tuple[str, ...]) -> str:
    return "；".join(_reason_label(reason) for reason in reasons) or "必要参数缺失"


def _format_ms(value: float) -> str:
    return f"{value:g}"
