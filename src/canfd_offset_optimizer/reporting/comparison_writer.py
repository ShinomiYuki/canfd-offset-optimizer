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
from .filenames import infer_report_prefix, prefixed_report_name
from .restart_writer import configuration_hash
from .summary_writer import combined_input_hash, sha256_file


def _objective_dict(value: ObjectiveValue) -> dict[str, int]:
    return {
        "violation_count": value.violation_count,
        "violation_excess": value.violation_excess,
        "steady_peak": value.steady_peak,
        "startup_peak": value.startup_peak,
        "sum_square_load": value.sum_square_load,
        "startup_sum_square_load": value.startup_sum_square_load,
        "max_release_count": value.max_release_count,
        "peak_budget_excess": value.peak_budget_excess,
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
    report_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """! @brief 写出算法、Offset 和时隙三个 UTF-8 BOM 对比表。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    algorithm_path = results_dir / prefixed_report_name(
        "algorithm_comparison.csv", report_prefix
    )
    offsets_path = results_dir / prefixed_report_name(
        "offsets_comparison.csv", report_prefix
    )
    slots_path = results_dir / prefixed_report_name(
        "slot_loads_comparison.csv", report_prefix
    )
    original = result.stage("original")
    objective_ranks = {
        objective: rank
        for rank, objective in enumerate(
            sorted({stage.objective for stage in result.stages}), start=1
        )
    }

    with algorithm_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = [
            "阶段",
            "类型",
            "词典序排名",
            "目标模式",
            "峰值预算(μs)",
            "峰值预算超出量(μs)",
            "超限时隙数",
            "超限总量",
            "稳态峰值",
            "启动峰值",
            "负载平方和",
            "启动负载平方和",
            "最大释放帧数",
            "是否优于原始方案",
            "稳态峰值改善率(%)",
            "启动峰值改善率(%)",
            "负载平方和改善率(%)",
            "评价次数",
            "接受移动次数",
            "运行时间(s)",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for stage in result.stages:
            objective = stage.objective
            writer.writerow(
                {
                    "阶段": stage.name,
                    "类型": stage.kind,
                    "词典序排名": objective_ranks[objective],
                    "目标模式": objective.mode.value,
                    "峰值预算(μs)": objective.peak_budget_us or "",
                    "峰值预算超出量(μs)": objective.peak_budget_excess,
                    "超限时隙数": objective.violation_count,
                    "超限总量": objective.violation_excess,
                    "稳态峰值": objective.steady_peak,
                    "启动峰值": objective.startup_peak,
                    "负载平方和": objective.sum_square_load,
                    "启动负载平方和": objective.startup_sum_square_load,
                    "最大释放帧数": objective.max_release_count,
                    "是否优于原始方案": objective < original.objective,
                    "稳态峰值改善率(%)": _improvement_percent(
                        original.objective.steady_peak, objective.steady_peak
                    ),
                    "启动峰值改善率(%)": _improvement_percent(
                        original.objective.startup_peak, objective.startup_peak
                    ),
                    "负载平方和改善率(%)": _improvement_percent(
                        original.objective.sum_square_load, objective.sum_square_load
                    ),
                    "评价次数": stage.evaluation_count,
                    "接受移动次数": stage.accepted_moves,
                    "运行时间(s)": f"{stage.elapsed_seconds:.9f}",
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
            "阶段",
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
                            "阶段": stage.name,
                            "窗口": "启动" if window_name == "startup" else "稳态",
                            "时隙索引": index,
                            "开始时间(μs)": start_us,
                            "结束时间(μs)": start_us + window.slot_width_us,
                            "权重模式": network.weight_mode.value,
                            "加权负载": load,
                            "加权负载(μs)": load if physical else "",
                            "负载比例": (
                                f"{load / window.slot_width_us:.6f}" if physical else ""
                            ),
                            "释放帧数": count,
                            "是否超过阈值": (
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
        "input_hash": combined_input_hash(network.input_files),
        "configuration_hash": configuration_hash(config),
        "input_files": [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in network.input_files
            if path.is_file()
        ],
        "field_sources": dict(network.field_sources),
        "cli_overrides": dict(network.cli_overrides),
        "effective_configuration": {
            "weight_mode": config.model.weight_mode.value,
            "objective_mode": config.objective.mode.value,
            "restart_policy": {
                "mode": config.optimization.restart_policy.mode.value,
                "total_attempts": config.optimization.restart_policy.total_attempts,
                "min_attempts": config.optimization.restart_policy.min_attempts,
                "check_interval": config.optimization.restart_policy.check_interval,
                "patience_attempts": config.optimization.restart_policy.patience_attempts,
                "max_attempts": config.optimization.restart_policy.max_attempts,
                "source_kind": config.optimization.restart_policy.source_kind,
                "legacy_additional_restarts": (
                    config.optimization.restart_policy.legacy_additional_restarts
                ),
            },
            "peak_tolerance_type": config.objective.peak_tolerance.type.value,
            "peak_tolerance_value": config.objective.peak_tolerance.value,
            "variance_offset_cap": config.optimization.variance_offset_cap,
        },
        "network": {
            "message_count": len(network.messages),
            "channel": network.channel.name,
            "nominal_bitrate_bit_s": network.channel.nominal_bitrate,
            "data_bitrate_bit_s": network.channel.data_bitrate,
            "brs": network.channel.brs,
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
            "objective_mode": result.stage("gcls").objective.mode.value,
            "lexicographic_order": list(result.stage("gcls").objective.priorities),
            "peak_budget_us": result.peak_budget_us,
            "peak_reference_objective": (
                _objective_dict(result.peak_reference_objective)
                if result.peak_reference_objective
                else None
            ),
            "seed": result.seed,
            "restart_mode": result.restart_execution.mode.value,
            "restart_actual_attempts": result.restart_execution.actual_attempts,
            "restart_stop_reason": result.restart_execution.stop_reason,
            "restart_max_attempts_reached": (
                result.restart_execution.max_attempts_reached
            ),
            "hot_slot_count": config.optimization.hot_slot_count,
            "conflict_candidate_cap": config.optimization.conflict_candidate_cap,
            "pair_neighbor_steps": config.optimization.pair_neighbor_steps,
            "variance_offset_cap": config.optimization.variance_offset_cap,
            "peak_tolerance": {
                "type": config.objective.peak_tolerance.type.value,
                "value": config.objective.peak_tolerance.value,
            },
            "variance_metric": config.objective.variance_metric,
            "peak_reference_restarts": [
                {
                    "attempt_index": record.attempt_index,
                    "seed": record.seed,
                    "objective": record.objective.as_tuple(),
                    "assignment_hash": record.assignment_hash,
                }
                for record in result.peak_reference_restart_records
            ],
            "peak_reference_evaluation_count": result.peak_reference_evaluation_count,
            "peak_reference_runtime_seconds": result.peak_reference_elapsed_seconds,
            "balanced_fallback_reason": result.balanced_fallback_reason,
        },
        "stages": [
            {
                "name": stage.name,
                "kind": stage.kind,
                "objective": _objective_dict(stage.objective),
                "objective_tuple": stage.objective.as_tuple(),
                "objective_metrics": stage.objective.metrics_tuple(),
                "objective_mode": stage.objective.mode.value,
                "peak_budget_us": stage.objective.peak_budget_us,
                "evaluation_count": stage.evaluation_count,
                "accepted_moves": stage.accepted_moves,
                "runtime_seconds": stage.elapsed_seconds,
            }
            for stage in result.stages
        ],
        "restarts": [
            {
                "attempt_index": record.attempt_index,
                "attempt_kind": record.attempt_kind.value,
                "seed": record.seed,
                "objective": record.objective.as_tuple(),
                "assignment_hash": record.assignment_hash,
                "assignments": [
                    {
                        "message_name": item.message_name,
                        "can_id": item.can_id,
                        "offset_us": item.offset_us,
                        "definition_index": item.definition_index,
                    }
                    for item in record.assignments
                ],
                "runtime_seconds": record.elapsed_seconds,
                "evaluation_count": record.evaluation_count,
                "accepted_moves": record.accepted_moves,
            }
            for record in result.restart_records
        ],
        "weight_mode": network.weight_mode.value,
        "weight_accuracy": (
            "conservative_iso_can_fd_estimate_with_intermission"
            if physical
            else "explicit_approximation"
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
    report_prefix: str | None = None,
) -> Path:
    """! @brief 写出 `results/comparison_summary.json`。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "comparison_summary.json"
    prefix = report_prefix or infer_report_prefix(
        network.input_files[0] if network.input_files else Path("network.dbc"),
        output_root.name,
    )
    payload = build_comparison_summary(network, config, result)
    payload["restart_audit_files"] = {
        "gcls": f"{prefix}_restart_records.jsonl",
        "peak_reference": (
            f"{prefix}_peak_reference_restart_records.jsonl"
            if result.peak_reference_restart_records
            else None
        ),
    }
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
