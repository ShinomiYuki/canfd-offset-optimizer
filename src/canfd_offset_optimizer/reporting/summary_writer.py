"""! @file summary_writer.py
@brief 生成包含输入哈希、来源、配置、种子与指标的 summary.json。

@author 篠見由紀
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ..config import ProjectConfig
from ..models import NetworkModel, ObjectiveValue, OptimizationResult, WeightMode
from ..optimization.objective import slot_load_threshold_us


def sha256_file(path: Path) -> str:
    """! @brief 流式计算输入文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_summary(
    network: NetworkModel,
    config: ProjectConfig,
    result: OptimizationResult,
) -> dict[str, object]:
    """! @brief 从不可变模型和结果构造标准 JSON 可序列化摘要。"""
    inputs = [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in network.input_files
        if path.is_file()
    ]
    physical_time_weight = network.weight_mode is WeightMode.FRAME_TIME_US

    def objective(value: ObjectiveValue) -> dict[str, int]:
        return {
            "violation_count": value.violation_count,
            "violation_excess": value.violation_excess,
            "steady_peak": value.steady_peak,
            "startup_peak": value.startup_peak,
            "sum_square_load": value.sum_square_load,
            "max_release_count": value.max_release_count,
        }

    return {
        "input_files": inputs,
        "field_sources": dict(network.field_sources),
        "yaml_overrides": {
            key: value
            for key, value in asdict(config.network).items()
            if value is not None
        },
        "network": {
            "channel": network.channel.name,
            "nominal_bitrate": network.channel.nominal_bitrate,
            "data_bitrate": network.channel.data_bitrate,
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
        "algorithm": {
            "name": "GCLS",
            "seed_count": len(result.restart_records),
            "random_restarts": config.optimization.random_restarts,
            "hot_slot_count": config.optimization.hot_slot_count,
            "conflict_candidate_cap": config.optimization.conflict_candidate_cap,
            "pair_neighbor_steps": config.optimization.pair_neighbor_steps,
            "evaluation_count": result.evaluation_count,
            "accepted_moves": result.accepted_moves,
        },
        "average_load": network.average_load if physical_time_weight else None,
        "average_weight_rate": network.average_load,
        "average_load_limit": (
            config.model.average_load_limit if physical_time_weight else None
        ),
        "average_load_constraint_applicable": physical_time_weight,
        "slot_load_threshold_us": (
            slot_load_threshold_us(
                network.steady_window.slot_width_us,
                config.model.average_load_limit,
            )
            if physical_time_weight
            else None
        ),
        "baseline_policy": "legal original Offset, otherwise minimum allowed Offset",
        "objective_before": result.initial_objective.as_tuple(),
        "objective_first_greedy": result.greedy_objective.as_tuple(),
        "objective_after": result.objective.as_tuple(),
        "objectives": {
            "before": objective(result.initial_objective),
            "first_greedy": objective(result.greedy_objective),
            "after": objective(result.objective),
            "lexicographic_order": [
                "violation_count",
                "violation_excess",
                "steady_peak",
                "startup_peak",
                "sum_square_load",
                "max_release_count",
            ],
        },
        "restarts": [
            {"seed": record.seed, "objective": record.objective.as_tuple()}
            for record in result.restart_records
        ],
        "runtime_seconds": result.elapsed_seconds,
        "warnings": list(network.warnings),
        "weight_mode": network.weight_mode.value,
        "weight_accuracy": (
            "conservative_iso_can_fd_estimate"
            if physical_time_weight
            else "explicit_approximation"
        ),
        "objective_load_unit": "microseconds" if physical_time_weight else "weight_units",
    }


def write_summary(
    output_root: Path,
    network: NetworkModel,
    config: ProjectConfig,
    result: OptimizationResult,
) -> Path:
    """! @brief 将运行摘要写入 `results/summary.json`。"""
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "summary.json"
    path.write_text(
        json.dumps(build_summary(network, config, result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
