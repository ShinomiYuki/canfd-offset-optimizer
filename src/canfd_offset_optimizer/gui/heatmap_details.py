"""Build immutable heatmap membership from the core's official slot map."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.timeline.slot_map import SlotMap
from canfd_offset_optimizer.timing.conservative_service import (
    ConservativeEstimateStatus,
    estimate_conservative_bus_service_time,
)

from .contracts import (
    FrameProtocol,
    HeatmapMessageDetail,
    HeatmapSlotDetail,
    HeatmapWindowDetail,
    NetworkTimingConfig,
)
from .timing_resolution import resolve_effective_brs


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
    network_timing_config: NetworkTimingConfig | None = None,
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
        network_timing_config=network_timing_config,
    )
    optimized = _build_state_slots(
        messages,
        slot_map,
        optimized_offsets,
        optimized_loads,
        optimized_counts,
        startup=startup,
        network_timing_config=network_timing_config,
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
    network_timing_config: NetworkTimingConfig | None,
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
        nominal_bitrate_bps = (
            network_timing_config.nominal_bitrate_bps
            if network_timing_config is not None
            else None
        )
        effective_brs, effective_brs_source = resolve_effective_brs(
            message.dbc_brs,
            message.dbc_brs_source,
            network_timing_config,
        )
        estimate = estimate_conservative_bus_service_time(
            protocol=message.frame_protocol,
            is_extended=message.is_extended,
            payload_bytes=message.payload_bytes,
            nominal_bitrate_bps=nominal_bitrate_bps,
            data_bitrate_bps=(
                network_timing_config.data_bitrate_bps
                if network_timing_config is not None
                else None
            ),
            effective_brs=effective_brs,
        )
        detail = HeatmapMessageDetail(
            message.name,
            message.can_id,
            message.is_extended,
            message.cycle_time_us,
            offset_us,
            payload_bytes=message.payload_bytes,
            frame_protocol=FrameProtocol(message.frame_protocol.value),
            conservative_service_time_us=(
                estimate.conservative_bus_service_time_us
            ),
            conservative_total_bits_upper_bound=estimate.total_bits_upper_bound,
            conservative_status=estimate.status,
            conservative_unavailable_reason=estimate.unavailable_reason,
            dbc_brs=message.dbc_brs,
            dbc_brs_source=message.dbc_brs_source,
            effective_brs=effective_brs,
            effective_brs_source=effective_brs_source,
            conservative_nominal_bits_upper_bound=(
                estimate.nominal_bits_upper_bound
            ),
            conservative_data_bits_upper_bound=estimate.data_bits_upper_bound,
        )
        for slot_index in indexes:
            buckets[slot_index].append(detail)
            calculated_loads[slot_index] += message.frame_time_us
    if tuple(len(bucket) for bucket in buckets) != tuple(counts):
        raise ValueError("core slot membership disagrees with release counts")
    if tuple(calculated_loads) != tuple(loads):
        raise ValueError("core slot membership disagrees with weighted loads")
    slots: list[HeatmapSlotDetail] = []
    for index, bucket in enumerate(buckets):
        known_times = tuple(
            message.conservative_service_time_us
            for message in bucket
            if message.conservative_status is ConservativeEstimateStatus.COMPLETE
            and message.conservative_service_time_us is not None
        )
        complete_count = len(known_times)
        total_count = len(bucket)
        conservative_total = (
            0
            if total_count == 0
            else (sum(known_times) if complete_count > 0 else None)
        )
        slots.append(
            HeatmapSlotDetail(
                slot_index=index,
                start_us=index * window.slot_width_us,
                end_us=(index + 1) * window.slot_width_us,
                frame_count=int(counts[index]),
                total_load=int(loads[index]),
                messages=tuple(bucket),
                conservative_total_time_us=conservative_total,
                conservative_complete_count=complete_count,
                conservative_total_count=total_count,
            )
        )
    return tuple(slots)
