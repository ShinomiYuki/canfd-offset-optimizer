"""! @file csv_writer.py
@brief 将已计算的优化结果写入 UTF-8 BOM CSV。

@author 篠見由紀
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import NetworkModel, OptimizationResult, WeightMode
from ..optimization.objective import slot_load_threshold_us
from .filenames import prefixed_report_name


def write_csv_reports(
    output_root: Path,
    network: NetworkModel,
    result: OptimizationResult,
    load_limit: float,
    report_prefix: str | None = None,
) -> tuple[Path, Path]:
    """! @brief 写出 offsets.csv 与 slot_loads.csv。

    @return 两个结果文件路径。
    @note 只消费结果数组，不重新运行目标计算或改变 Offset。
    """
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    offsets_path = results_dir / prefixed_report_name("offsets.csv", report_prefix)
    slot_loads_path = results_dir / prefixed_report_name(
        "slot_loads.csv", report_prefix
    )
    assignments = result.offset_by_name()
    with offsets_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "报文名称",
                "CAN_ID",
                "帧格式",
                "发送节点",
                "周期(μs)",
                "权重模式",
                "权重值",
                "保守帧时间(μs)",
                "原始Offset(μs)",
                "推荐Offset(μs)",
            ],
        )
        writer.writeheader()
        for message in result.messages:
            writer.writerow(
                {
                    "报文名称": message.name,
                    "CAN_ID": f"0x{message.can_id:X}",
                    "帧格式": message.frame_format.value,
                    "发送节点": message.sender_ecu,
                    "周期(μs)": message.cycle_time_us,
                    "权重模式": network.weight_mode.value,
                    "权重值": message.frame_time_us,
                    "保守帧时间(μs)": (
                        message.frame_time_us
                        if network.weight_mode is WeightMode.FRAME_TIME_US
                        else ""
                    ),
                    "原始Offset(μs)": message.original_offset_us,
                    "推荐Offset(μs)": assignments[message.name],
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
                "窗口",
                "时隙索引",
                "开始时间(μs)",
                "结束时间(μs)",
                "权重模式",
                "加权负载",
                "加权负载(μs)",
                "负载比例",
                "释放帧数",
                "是否超过阈值",
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
                "窗口": "启动" if label == "startup" else "稳态",
                "时隙索引": index,
                "开始时间(μs)": start,
                "结束时间(μs)": start + slot_width_us,
                "权重模式": weight_mode.value,
                "加权负载": load,
                "加权负载(μs)": (
                    load if weight_mode is WeightMode.FRAME_TIME_US else ""
                ),
                "负载比例": (
                    f"{load / slot_width_us:.6f}" if threshold_us is not None else ""
                ),
                "释放帧数": count,
                "是否超过阈值": (
                    load > threshold_us if threshold_us is not None else ""
                ),
            }
        )
