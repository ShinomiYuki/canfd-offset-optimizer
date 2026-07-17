"""Presentation formatting and explicit user exports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import GuiOptimizationResult, ObjectiveMetrics, WeightMode


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


def export_summary_json(result: GuiOptimizationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "network": result.network_name,
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
        "exported_files": [str(item) for item in result.exported_files],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
