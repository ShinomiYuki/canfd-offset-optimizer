"""Presentation formatting and explicit workspace output writers."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import (
    BatchOptimizationResult,
    GuiOptimizationResult,
    NetworkBatchResult,
    ObjectiveMetrics,
    WeightMode,
)


def format_can_id(can_id: int) -> str:
    width = 3 if can_id <= 0x7FF else 8
    return f"0x{can_id:0{width}X}"


def format_milliseconds(microseconds: int) -> str:
    return f"{microseconds / 1_000:.3f}"


def format_integer(value: int) -> str:
    return f"{value:,}"


def format_weight_mode(mode: WeightMode) -> str:
    if mode is WeightMode.FRAME_TIME_US:
        return "帧时间（frame_time_us）"
    return "Payload 长度（payload_bytes）"


def metrics_dict(metrics: ObjectiveMetrics) -> dict[str, int | float]:
    return {
        "Zss": metrics.zss,
        "Qss": metrics.qss,
        "standard_deviation": metrics.standard_deviation,
        "Zst": metrics.zst,
        "Qst": metrics.qst,
        "Nvio": metrics.nvio,
        "Vvio": metrics.vvio,
    }


def export_assignments_csv(result: GuiOptimizationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("报文", "CAN ID", "周期(ms)", "原Offset(ms)", "新Offset(ms)", "变化(ms)"))
        for row in result.assignments:
            writer.writerow(
                (
                    row.message_name,
                    format_can_id(row.can_id),
                    format_milliseconds(row.cycle_time_us),
                    format_milliseconds(row.original_offset_us),
                    format_milliseconds(row.optimized_offset_us),
                    format_milliseconds(row.change_us),
                )
            )
    return path


def _network_dict(item: NetworkBatchResult) -> dict[str, Any]:
    result = item.result
    return {
        "network_id": item.network_id,
        "network": item.network_name,
        "display_name": item.display_name,
        "source_file": item.source_file,
        "status": item.status.value,
        "weight_mode": item.weight_mode.value,
        "mode": item.mode.value,
        "original_metrics": metrics_dict(result.original_metrics) if result else None,
        "optimized_metrics": metrics_dict(result.optimized_metrics) if result else None,
        "zss_improvement": item.zss_improvement,
        "actual_attempts": result.actual_attempts if result else None,
        "stop_reason": result.stop_reason if result else None,
        "elapsed_seconds": result.elapsed_seconds if result else None,
        "warnings": list(item.warnings),
        "error": item.error,
        "logs": list(item.logs),
        "output_directory": str(result.output_directory) if result and result.output_directory else None,
        "exported_files": [str(path) for path in result.exported_files] if result else [],
    }


def export_network_summary_json(result: GuiOptimizationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "network_id": result.network_id,
        "network": result.network_name,
        "display_name": result.display_name,
        "source_file": result.source_file,
        "weight_mode": result.weight_mode.value,
        "mode": result.mode.value,
        "original_metrics": metrics_dict(result.original_metrics),
        "optimized_metrics": metrics_dict(result.optimized_metrics),
        "actual_attempts": result.actual_attempts,
        "stop_reason": result.stop_reason,
        "elapsed_seconds": result.elapsed_seconds,
        "warnings": list(result.warnings),
        "assignments": [asdict(row) for row in result.assignments],
        "steady_loads_before": list(result.steady_loads_before),
        "steady_loads_after": list(result.steady_loads_after),
        "startup_loads_before": list(result.startup_loads_before),
        "startup_loads_after": list(result.startup_loads_after),
        "logs": list(result.logs),
        "exported_files": [str(item) for item in result.exported_files],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_batch_summary_csv(batch: BatchOptimizationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "network_id",
                "网段",
                "显示名称",
                "来源DBC",
                "状态",
                "权重",
                "模式",
                "原始Zss",
                "优化后Zss",
                "Zss改善",
                "原始Qss",
                "优化后Qss",
                "标准差",
                "attempts",
                "停止原因",
                "耗时(s)",
                "警告数量",
                "错误",
            )
        )
        for item in batch.network_results:
            result = item.result
            writer.writerow(
                (
                    item.network_id,
                    item.network_name,
                    item.display_name,
                    item.source_file,
                    item.status.value,
                    item.weight_mode.value,
                    item.mode.value,
                    result.original_metrics.zss if result else "",
                    result.optimized_metrics.zss if result else "",
                    item.zss_improvement if item.zss_improvement is not None else "",
                    result.original_metrics.qss if result else "",
                    result.optimized_metrics.qss if result else "",
                    result.optimized_metrics.standard_deviation if result else "",
                    result.actual_attempts if result else "",
                    result.stop_reason if result else "",
                    f"{result.elapsed_seconds:.6f}" if result else "",
                    len(item.warnings),
                    item.error or "",
                )
            )
    return path


def export_batch_summary_json(batch: BatchOptimizationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "project_name": batch.project_name,
        "status": batch.status.value,
        "import_session_directory": str(batch.import_session_directory),
        "import_manifest": str(batch.import_manifest_path),
        "output_directory": str(batch.output_directory),
        "elapsed_seconds": batch.elapsed_seconds,
        "cancelled": batch.cancelled,
        "counts": {
            "succeeded": batch.succeeded_count,
            "failed": batch.failed_count,
            "skipped": batch.skipped_count,
            "cancelled": batch.cancelled_count,
        },
        "warnings": list(batch.warnings),
        "errors": list(batch.errors),
        "networks": [_network_dict(item) for item in batch.network_results],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# Backward-compatible name used by callers exporting one selected network.
export_summary_json = export_network_summary_json
