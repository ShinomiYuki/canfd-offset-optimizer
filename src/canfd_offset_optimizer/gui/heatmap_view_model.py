"""Pure display ViewModel for one network and one heatmap window."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import (
    GuiOptimizationResult,
    HeatmapMessageDetail,
    HeatmapWindowDetail,
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

    @property
    def start_ms(self) -> float:
        return self.start_us / 1_000

    @property
    def end_ms(self) -> float:
        return self.end_us / 1_000

    @property
    def text(self) -> str:
        if self.frame_count == 0:
            return ""
        return f"{self.frame_count} 帧\n{self.total_load} {self.load_unit}"

    @property
    def tooltip(self) -> str:
        return (
            f"状态：{self.state.label}\n"
            f"时间：[{_format_ms(self.start_ms)}, {_format_ms(self.end_ms)}) ms\n"
            f"帧数：{self.frame_count}\n"
            f"负载：{self.total_load} {self.load_unit}"
        )


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


@dataclass(frozen=True, slots=True)
class HeatmapViewModel:
    network_id: str
    display_name: str
    source_file: str
    window_kind: HeatmapWindowKind
    slot_width_us: int
    load_unit: str
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


def build_heatmap_view_model(
    result: GuiOptimizationResult,
    window_kind: HeatmapWindowKind,
) -> HeatmapViewModel:
    """Select one immutable result window; never recompute loads or releases."""

    load_unit = "B" if result.weight_mode is WeightMode.PAYLOAD_BYTES else "μs"
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
    slot_width_us = detail.slot_width_us if detail is not None else 5_000
    original = _state_cells(
        HeatmapState.ORIGINAL,
        detail,
        before_loads,
        before_counts,
        slot_width_us,
        load_unit,
    )
    optimized = _state_cells(
        HeatmapState.OPTIMIZED,
        detail,
        after_loads,
        after_counts,
        slot_width_us,
        load_unit,
    )
    congested = tuple(
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
        for cells in (original, optimized)
        for cell in cells
        if cell.frame_count >= 4
        for message in cell.messages
    )
    return HeatmapViewModel(
        result.network_id,
        result.display_name,
        result.source_file,
        window_kind,
        slot_width_us,
        load_unit,
        original,
        optimized,
        congested,
    )


def _state_cells(
    state: HeatmapState,
    detail: HeatmapWindowDetail | None,
    loads: tuple[int, ...],
    counts: tuple[int, ...],
    slot_width_us: int,
    load_unit: str,
) -> tuple[HeatmapCellView, ...]:
    slots = None
    if detail is not None:
        slots = (
            detail.original_slots
            if state is HeatmapState.ORIGINAL
            else detail.optimized_slots
        )
    return tuple(
        HeatmapCellView(
            state,
            index,
            index * slot_width_us,
            (index + 1) * slot_width_us,
            count,
            load,
            slots[index].messages if slots is not None else (),
            load_unit,
        )
        for index, (load, count) in enumerate(zip(loads, counts, strict=True))
    )


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


def _format_ms(value: float) -> str:
    return f"{value:g}"
