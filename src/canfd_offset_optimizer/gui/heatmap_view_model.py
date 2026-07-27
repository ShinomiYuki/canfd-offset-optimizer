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

    def cell_for(self, selection: HeatmapCellSelection) -> HeatmapCellView:
        """Resolve a full cell identity without falling back to slot index alone."""

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
    slot_width_us = result.load_window_metadata.slot_width_us
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


def _format_ms(value: float) -> str:
    return f"{value:g}"
