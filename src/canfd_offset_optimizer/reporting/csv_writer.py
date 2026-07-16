"""! @file csv_writer.py
@brief 将已计算的优化结果写入 UTF-8 BOM CSV。

@author 篠見由紀
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import NetworkModel, OptimizationResult, WeightMode
from ..optimization.objective import slot_load_threshold_us


def write_csv_reports(
    output_root: Path,
    network: NetworkModel,
    result: OptimizationResult,
    load_limit: float,
) -> tuple[Path, Path]:
    """! @brief 写出 offsets.csv 与 slot_loads.csv。

    @return 两个结果文件路径。
    @note 只消费结果数组，不重新运行目标计算或改变 Offset。
    """
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    offsets_path = results_dir / "offsets.csv"
    slot_loads_path = results_dir / "slot_loads.csv"
    assignments = result.offset_by_name()
    with offsets_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "message_name",
                "can_id",
                "frame_format",
                "sender_ecu",
                "cycle_time_us",
                "weight_mode",
                "weight_value",
                "frame_weight_us",
                "original_offset_us",
                "recommended_offset_us",
            ],
        )
        writer.writeheader()
        for message in result.messages:
            writer.writerow(
                {
                    "message_name": message.name,
                    "can_id": f"0x{message.can_id:X}",
                    "frame_format": message.frame_format.value,
                    "sender_ecu": message.sender_ecu,
                    "cycle_time_us": message.cycle_time_us,
                    "weight_mode": network.weight_mode.value,
                    "weight_value": message.frame_time_us,
                    "frame_weight_us": (
                        message.frame_time_us
                        if network.weight_mode is WeightMode.FRAME_TIME_US
                        else ""
                    ),
                    "original_offset_us": message.original_offset_us,
                    "recommended_offset_us": assignments[message.name],
                }
            )
    physical_time_weight = network.weight_mode is WeightMode.FRAME_TIME_US
    threshold_us = (
        slot_load_threshold_us(network.steady_window.slot_width_us, load_limit)
        if physical_time_weight
        else None
    )
    with slot_loads_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "window",
                "slot_index",
                "start_us",
                "end_us",
                "weight_mode",
                "weighted_load",
                "weighted_load_us",
                "load_ratio",
                "release_count",
                "threshold_violation",
            ],
        )
        writer.writeheader()
        _write_window_rows(
            writer,
            "startup",
            network.startup_window.start_us,
            network.startup_window.slot_width_us,
            result.startup_slot_loads,
            result.startup_slot_counts,
            threshold_us,
            network.weight_mode,
        )
        _write_window_rows(
            writer,
            "steady",
            network.steady_window.start_us,
            network.steady_window.slot_width_us,
            result.steady_slot_loads,
            result.steady_slot_counts,
            threshold_us,
            network.weight_mode,
        )
    return offsets_path, slot_loads_path


def _write_window_rows(
    writer: csv.DictWriter[str],
    label: str,
    window_start_us: int,
    slot_width_us: int,
    loads: tuple[int, ...],
    counts: tuple[int, ...],
    threshold_us: int | None,
    weight_mode: WeightMode,
) -> None:
    """! @brief 写出一个窗口中一一对应的负载与计数行。"""
    for index, (load, count) in enumerate(zip(loads, counts, strict=True)):
        start = window_start_us + index * slot_width_us
        writer.writerow(
            {
                "window": label,
                "slot_index": index,
                "start_us": start,
                "end_us": start + slot_width_us,
                "weight_mode": weight_mode.value,
                "weighted_load": load,
                "weighted_load_us": (
                    load if weight_mode is WeightMode.FRAME_TIME_US else ""
                ),
                "load_ratio": (
                    f"{load / slot_width_us:.6f}" if threshold_us is not None else ""
                ),
                "release_count": count,
                "threshold_violation": (
                    load > threshold_us if threshold_us is not None else ""
                ),
            }
        )
