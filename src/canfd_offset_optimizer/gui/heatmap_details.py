"""Build immutable heatmap membership from the core's official slot map."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.timeline.slot_map import SlotMap

from .contracts import HeatmapMessageDetail, HeatmapSlotDetail, HeatmapWindowDetail


def build_heatmap_window_detail(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    original_offsets: Mapping[str, int],
    optimized_offsets: Mapping[str, int],
    original_loads: Sequence[int],
    optimized_loads: Sequence[int],
    original_counts: Sequence[int],
    optimized_counts: Sequence[int],
    *,
    startup: bool,
    original_messages: tuple[CanMessage, ...] | None = None,
    original_slot_map: SlotMap | None = None,
) -> HeatmapWindowDetail:
    """Expose slot members without reimplementing release or load calculation."""

    window = slot_map.startup_window if startup else slot_map.steady_window
    expected = window.slot_count
    arrays = (original_loads, optimized_loads, original_counts, optimized_counts)
    if any(len(values) != expected for values in arrays):
        raise ValueError("core heatmap arrays do not align with the selected window")
    original = _build_state_slots(
        original_messages or messages,
        original_slot_map or slot_map,
        original_offsets,
        original_loads,
        original_counts,
        startup=startup,
    )
    optimized = _build_state_slots(
        messages,
        slot_map,
        optimized_offsets,
        optimized_loads,
        optimized_counts,
        startup=startup,
    )
    return HeatmapWindowDetail(window.slot_width_us, original, optimized)


def _build_state_slots(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    offsets: Mapping[str, int],
    loads: Sequence[int],
    counts: Sequence[int],
    *,
    startup: bool,
) -> tuple[HeatmapSlotDetail, ...]:
    window = slot_map.startup_window if startup else slot_map.steady_window
    buckets: list[list[HeatmapMessageDetail]] = [
        [] for _ in range(window.slot_count)
    ]
    calculated_loads = [0] * window.slot_count
    for message in messages:
        try:
            offset_us = offsets[message.name]
        except KeyError as exc:
            raise ValueError(f"heatmap Offset missing for {message.name}") from exc
        hits = slot_map.for_candidate(message, offset_us)
        indexes = hits.startup if startup else hits.steady
        detail = HeatmapMessageDetail(
            message.name,
            message.can_id,
            message.is_extended,
            message.cycle_time_us,
            offset_us,
        )
        for slot_index in indexes:
            buckets[slot_index].append(detail)
            calculated_loads[slot_index] += message.frame_time_us
    if tuple(len(bucket) for bucket in buckets) != tuple(counts):
        raise ValueError("core slot membership disagrees with release counts")
    if tuple(calculated_loads) != tuple(loads):
        raise ValueError("core slot membership disagrees with weighted loads")
    return tuple(
        HeatmapSlotDetail(
            slot_index=index,
            start_us=index * window.slot_width_us,
            end_us=(index + 1) * window.slot_width_us,
            frame_count=int(counts[index]),
            total_load=int(loads[index]),
            messages=tuple(bucket),
        )
        for index, bucket in enumerate(buckets)
    )
