"""! @file comparison_writer.py
@brief 输出多算法对比 CSV 与 JSON，不重新评分或修改阶段快照。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..config import ProjectConfig
from ..models import (
    AlgorithmComparisonResult,
    NetworkModel,
    ObjectiveValue,
    WeightMode,
)
from ..optimization.objective import slot_load_threshold_us
from .summary_writer import sha256_file


def _objective_dict(value: ObjectiveValue) -> dict[str, int]:
    return {
        "violation_count": value.violation_count,
        "violation_excess": value.violation_excess,
        "steady_peak": value.steady_peak,
        "startup_peak": value.startup_peak,
        "sum_square_load": value.sum_square_load,
        "max_release_count": value.max_release_count,
    }


def _improvement_percent(baseline: int, candidate: int) -> str:
    if baseline == 0:
        return ""
    return f"{(baseline - candidate) * 100 / baseline:.6f}"


def _format_milliseconds(value_us: int | None) -> str:
    """! @brief 将整数微秒转换为最多三位小数的毫秒文本。"""
    if value_us is None:
        return ""
    return f"{value_us / 1_000:.3f}".rstrip("0").rstrip(".")


def write_comparison_csv_reports(
    output_root: Path,
    network: NetworkModel,
    result: AlgorithmComparisonResult,
    load_limit: float,
) -> tuple[Path, Path, Path]:
    """! @brief 写出算法、Offset 和时隙三个 UTF-8 BOM 对比表。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    algorithm_path = results_dir / "algorithm_comparison.csv"
    offsets_path = results_dir / "offsets_comparison.csv"
    slots_path = results_dir / "slot_loads_comparison.csv"
    original = result.stage("original")
    objective_ranks = {
        objective: rank
        for rank, objective in enumerate(
            sorted({stage.objective for stage in result.stages}), start=1
        )
    }

    with algorithm_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = [
            "stage",
            "kind",
            "lexicographic_rank",
            "violation_count",
            "violation_excess",
            "steady_peak",
            "startup_peak",
            "sum_square_load",
            "max_release_count",
            "better_than_original",
            "steady_peak_improvement_pct",
            "startup_peak_improvement_pct",
            "sum_square_improvement_pct",
            "evaluation_count",
            "accepted_moves",
            "runtime_seconds",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for stage in result.stages:
            objective = stage.objective
            writer.writerow(
                {
                    "stage": stage.name,
                    "kind": stage.kind,
                    "lexicographic_rank": objective_ranks[objective],
                    **_objective_dict(objective),
                    "better_than_original": objective < original.objective,
                    "steady_peak_improvement_pct": _improvement_percent(
                        original.objective.steady_peak, objective.steady_peak
                    ),
                    "startup_peak_improvement_pct": _improvement_percent(
                        original.objective.startup_peak, objective.startup_peak
                    ),
                    "sum_square_improvement_pct": _improvement_percent(
                        original.objective.sum_square_load, objective.sum_square_load
                    ),
                    "evaluation_count": stage.evaluation_count,
                    "accepted_moves": stage.accepted_moves,
                    "runtime_seconds": f"{stage.elapsed_seconds:.9f}",
                }
            )

    stage_offsets = {stage.name: stage.offset_by_name() for stage in result.stages}
    with offsets_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = [
            "报文名称",
            "CAN_ID",
            "帧格式",
            "发送节点",
            "周期(ms)",
            "载荷长度(Byte)",
            "DBC原始Offset(ms)",
            "原始方案Offset(ms)",
            "最小Offset方案(ms)",
            "Greedy推荐Offset(ms)",
            "Greedy+1-opt推荐Offset(ms)",
            "GCLS推荐Offset(ms)",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for message in result.messages:
            writer.writerow(
                {
                    "报文名称": message.name,
                    "CAN_ID": f"0x{message.can_id:X}",
                    "帧格式": "扩展帧" if message.is_extended else "标准帧",
                    "发送节点": message.sender_ecu,
                    "周期(ms)": _format_milliseconds(message.cycle_time_us),
                    "载荷长度(Byte)": message.payload_bytes,
                    "DBC原始Offset(ms)": _format_milliseconds(
                        message.original_offset_us
                    ),
                    "原始方案Offset(ms)": _format_milliseconds(
                        stage_offsets["original"][message.name]
                    ),
                    "最小Offset方案(ms)": _format_milliseconds(
                        stage_offsets["minimum"][message.name]
                    ),
                    "Greedy推荐Offset(ms)": _format_milliseconds(
                        stage_offsets["greedy"][message.name]
                    ),
                    "Greedy+1-opt推荐Offset(ms)": _format_milliseconds(
                        stage_offsets["greedy_1opt"][message.name]
                    ),
                    "GCLS推荐Offset(ms)": _format_milliseconds(
                        stage_offsets["gcls"][message.name]
                    ),
                }
            )

    physical = network.weight_mode is WeightMode.FRAME_TIME_US
    with slots_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = [
            "stage",
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
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for stage in result.stages:
            for window_name, window, loads, counts in (
                (
                    "startup",
                    network.startup_window,
                    stage.startup_slot_loads,
                    stage.startup_slot_counts,
                ),
                (
                    "steady",
                    network.steady_window,
                    stage.steady_slot_loads,
                    stage.steady_slot_counts,
                ),
            ):
                for index, (load, count) in enumerate(zip(loads, counts, strict=True)):
                    start_us = window.start_us + index * window.slot_width_us
                    writer.writerow(
                        {
                            "stage": stage.name,
                            "window": window_name,
                            "slot_index": index,
                            "start_us": start_us,
                            "end_us": start_us + window.slot_width_us,
                            "weight_mode": network.weight_mode.value,
                            "weighted_load": load,
                            "weighted_load_us": load if physical else "",
                            "load_ratio": (
                                f"{load / window.slot_width_us:.6f}" if physical else ""
                            ),
                            "release_count": count,
                            "threshold_violation": (
                                load
                                > slot_load_threshold_us(window.slot_width_us, load_limit)
                                if physical
                                else ""
                            ),
                        }
                    )
    return algorithm_path, offsets_path, slots_path


def build_comparison_summary(
    network: NetworkModel,
    config: ProjectConfig,
    result: AlgorithmComparisonResult,
) -> dict[str, object]:
    """! @brief 构造可由标准 JSON 编码器直接序列化的比较摘要。"""
    physical = network.weight_mode is WeightMode.FRAME_TIME_US
    return {
        "input_files": [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in network.input_files
            if path.is_file()
        ],
        "field_sources": dict(network.field_sources),
        "network": {
            "message_count": len(network.messages),
            "channel": network.channel.name,
            "hyperperiod_us": network.hyperperiod_us,
            "slot_width_us": network.steady_window.slot_width_us,
            "startup_window": {
                "start_us": network.startup_window.start_us,
                "end_us": network.startup_window.end_us,
                "interval": "[start, end)",
            },
            "steady_window": {
                "start_us": network.steady_window.start_us,
                "end_us": network.steady_window.end_us,
                "interval": "[start, end)",
            },
        },
        "comparison": {
            "stage_order": [stage.name for stage in result.stages],
            "lexicographic_order": [
                "violation_count",
                "violation_excess",
                "steady_peak",
                "startup_peak",
                "sum_square_load",
                "max_release_count",
            ],
            "seed": result.seed,
            "random_restarts": config.optimization.random_restarts,
            "hot_slot_count": config.optimization.hot_slot_count,
            "conflict_candidate_cap": config.optimization.conflict_candidate_cap,
            "pair_neighbor_steps": config.optimization.pair_neighbor_steps,
        },
        "stages": [
            {
                "name": stage.name,
                "kind": stage.kind,
                "objective": _objective_dict(stage.objective),
                "objective_tuple": stage.objective.as_tuple(),
                "evaluation_count": stage.evaluation_count,
                "accepted_moves": stage.accepted_moves,
                "runtime_seconds": stage.elapsed_seconds,
            }
            for stage in result.stages
        ],
        "restarts": [
            {"seed": record.seed, "objective": record.objective.as_tuple()}
            for record in result.restart_records
        ],
        "weight_mode": network.weight_mode.value,
        "weight_accuracy": (
            "conservative_iso_can_fd_estimate" if physical else "explicit_approximation"
        ),
        "objective_load_unit": "microseconds" if physical else "payload-byte weight",
        "average_load": network.average_load if physical else None,
        "average_load_limit": config.model.average_load_limit if physical else None,
        "slot_load_threshold_us": (
            slot_load_threshold_us(
                network.steady_window.slot_width_us,
                config.model.average_load_limit,
            )
            if physical
            else None
        ),
        "warnings": list(network.warnings),
    }


def write_comparison_summary(
    output_root: Path,
    network: NetworkModel,
    config: ProjectConfig,
    result: AlgorithmComparisonResult,
) -> Path:
    """! @brief 写出 `results/comparison_summary.json`。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "comparison_summary.json"
    path.write_text(
        json.dumps(
            build_comparison_summary(network, config, result),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
