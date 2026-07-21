"""Automatic GUI batch artifacts with a stable directory layout."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import struct
from typing import TypeAlias
import zlib

from .contracts import (
    BatchOptimizationResult,
    GuiBatchOptimizationRequest,
    GuiOptimizationResult,
    NetworkBatchResult,
    RoutingExclusionReport,
)
from .load_presentation import (
    CONGESTION_COLORS,
    DEFAULT_DISPLAY_DURATION_MS,
    SLOT_WIDTH_MS,
    STEADY_HYPERPERIOD_MS,
    repeat_for_display,
    congestion_level,
    steady_repeat_count,
)
from .theme import ACCENT_COLOR


Rgb: TypeAlias = tuple[int, int, int]
_accent_bytes = bytes.fromhex(ACCENT_COLOR.removeprefix("#"))
_ACCENT_RGB: Rgb = (_accent_bytes[0], _accent_bytes[1], _accent_bytes[2])


class _Raster:
    """Small dependency-free RGB canvas safe to use inside a backend QThread."""

    def __init__(self, width: int, height: int, color: Rgb) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(color * (width * height))

    def pixel(self, x: int, y: int, color: Rgb) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = (y * self.width + x) * 3
        self.pixels[index : index + 3] = bytes(color)

    def rectangle(
        self, left: int, top: int, right: int, bottom: int, color: Rgb
    ) -> None:
        left = max(0, left)
        right = min(self.width, right)
        top = max(0, top)
        bottom = min(self.height, bottom)
        row = bytes(color) * max(0, right - left)
        for y in range(top, bottom):
            start = (y * self.width + left) * 3
            self.pixels[start : start + len(row)] = row

    def line(
        self, x0: int, y0: int, x1: int, y1: int, color: Rgb
    ) -> None:
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                return
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    def save_png(self, path: Path) -> Path:
        def chunk(kind: bytes, data: bytes) -> bytes:
            payload = kind + data
            return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

        scanlines = b"".join(
            b"\x00" + self.pixels[y * self.width * 3 : (y + 1) * self.width * 3]
            for y in range(self.height)
        )
        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0),
            )
            + chunk(b"IDAT", zlib.compress(scanlines, level=9))
            + chunk(b"IEND", b"")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return path


@dataclass(frozen=True, slots=True)
class OutputLayout:
    root: Path
    logs: Path
    plots: Path
    results: Path
    dbc: Path


def create_output_layout(root: Path) -> OutputLayout:
    layout = OutputLayout(
        root=root,
        logs=root / "logs",
        plots=root / "plots",
        results=root / "results",
        dbc=root / "dbc",
    )
    for directory in (layout.logs, layout.plots, layout.results, layout.dbc):
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def write_run_config_json(request: GuiBatchOptimizationRequest, path: Path) -> Path:
    routing = request.inspection.routing_exclusion
    payload = {
        "mode": request.mode.value,
        "classic_can_weight": request.classic_can_weight.value,
        "can_fd_weight": request.can_fd_weight.value,
        "offset_search": request.offset_search.as_metadata(),
        "routing_table_count": routing.table_count,
        "routing_record_count": routing.record_count,
        "routing_matched_count": routing.matched_count,
        "routing_not_found_count": routing.not_found_count,
        "routing_ambiguous_count": routing.ambiguous_count,
        "routing_duplicate_count": routing.duplicate_count,
        "routing_excluded_message_count": routing.excluded_message_count,
        "final_optimized_message_count": (
            request.inspection.final_eligible_message_count
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def write_routing_exclusion_csv(
    report: RoutingExclusionReport, path: Path
) -> Path:
    """Write every source row, including unmatched and duplicate audit rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "target_network",
                "target_network_id",
                "can_id",
                "can_id_raw",
                "excel_message_name",
                "dbc_message_name",
                "match_status",
                "exclusion_status",
                "excel_source",
                "sheet_name",
                "row_number",
                "note",
            )
        )
        for record in report.records:
            issues = "、".join(issue.value for issue in record.issues)
            writer.writerow(
                (
                    record.route.target_network_raw,
                    record.target_network_id or "",
                    (
                        f"0x{record.route.can_id:X}"
                        if record.route.can_id is not None
                        else ""
                    ),
                    record.route.can_id_raw,
                    record.route.message_name or "",
                    record.dbc_message_name or "",
                    record.match_status.value,
                    record.exclusion_status.value,
                    record.route.source_file,
                    record.route.sheet_name,
                    record.route.row_number,
                    "；".join(filter(None, (record.note, issues))),
                )
            )
    return path


def write_load_curve_png(
    result: GuiOptimizationResult,
    path: Path,
    *,
    display_duration_ms: int = DEFAULT_DISPLAY_DURATION_MS,
) -> Path:
    repeat_count = steady_repeat_count(display_duration_ms)
    before = repeat_for_display(result.original_steady_load, repeat_count)
    after = repeat_for_display(result.optimized_steady_load, repeat_count)
    width, height = 1_200, 520
    left, top, right, bottom = 60, 30, 1_175, 465
    canvas = _Raster(width, height, (255, 255, 255))
    grid = (218, 218, 218)
    border = (110, 110, 110)
    for level in range(6):
        y = top + (bottom - top) * level // 5
        canvas.line(left, y, right, y, grid)
    for boundary in range(0, display_duration_ms + 1, STEADY_HYPERPERIOD_MS):
        x = left + (right - left) * boundary // display_duration_ms
        canvas.line(x, top, x, bottom, grid)
    canvas.line(left, top, right, top, border)
    canvas.line(left, bottom, right, bottom, border)
    canvas.line(left, top, left, bottom, border)
    canvas.line(right, top, right, bottom, border)
    maximum = max(max(before), max(after), 1)

    def point(index: int, value: int) -> tuple[int, int]:
        time_ms = index * SLOT_WIDTH_MS
        x = left + (right - left) * time_ms // display_duration_ms
        y = bottom - (bottom - top) * value // maximum
        return x, y

    for values, color, dashed in (
        (before, (122, 122, 122), True),
        (after, _ACCENT_RGB, False),
    ):
        previous = point(0, values[0])
        for index, value in enumerate(values[1:], start=1):
            current = point(index, value)
            if not dashed or index % 8 < 5:
                canvas.line(*previous, *current, color)
            previous = current
    return canvas.save_png(path)


def write_load_heatmap_png(
    result: GuiOptimizationResult,
    path: Path,
) -> Path:
    counts_before = result.original_steady_count
    counts_after = result.optimized_steady_count
    width, height = 1_200, 340
    left, top, right, row_height = 60, 35, 1_175, 115
    canvas = _Raster(width, height, (255, 255, 255))
    colors: tuple[Rgb, ...] = tuple(
        (raw[0], raw[1], raw[2])
        for raw in (bytes.fromhex(value.removeprefix("#")) for value in CONGESTION_COLORS)
    )
    for row, counts in enumerate((counts_before, counts_after)):
        y0 = top + row * row_height
        for index, count in enumerate(counts):
            x0 = left + (right - left) * index // len(counts)
            x1 = left + (right - left) * (index + 1) // len(counts)
            canvas.rectangle(
                x0,
                y0,
                max(x0 + 1, x1),
                y0 + row_height,
                colors[congestion_level(count)],
            )
            canvas.line(x0, y0, x0, y0 + row_height, (208, 208, 208))
    canvas.line(left, top, right, top, (100, 100, 100))
    canvas.line(left, top + row_height, right, top + row_height, (100, 100, 100))
    canvas.line(left, top + 2 * row_height, right, top + 2 * row_height, (100, 100, 100))
    return canvas.save_png(path)


def write_network_log(item: NetworkBatchResult, path: Path) -> Path:
    lines = (
        f"network={item.display_name}",
        f"network_id={item.network_id}",
        f"source_dbc={item.source_file}",
        f"status={item.status.value}",
        f"weight_mode={item.weight_mode.value}",
        f"objective_mode={item.mode.value}",
        f"base_eligible_message_count={item.base_eligible_message_count}",
        f"routing_excluded_count={item.routing_excluded_count}",
        f"final_eligible_message_count={item.final_eligible_message_count}",
    )
    content = list(lines)
    if item.result:
        content.append(f"bus_type={item.result.frame_protocol.value}")
        dbc_status = (
            "failed"
            if item.result.dbc_write_error
            else (
                "succeeded"
                if "dbc_write_status=succeeded" in item.result.logs
                else "not_applicable"
            )
        )
        content.append(f"dbc_write_status={dbc_status}")
        if item.result.dbc_write_error:
            content.append(f"dbc_write_error={item.result.dbc_write_error}")
    if item.result and item.result.classic_weight_model:
        content.append(
            f'classic_weight_model = "{item.result.classic_weight_model}"'
        )
        content.append("load_unit=Byte/slot")
        content.append("physical_bus_load_metrics=not_applicable")
    if item.error:
        content.append(f"error={item.error}")
    content.extend(f"warning={warning}" for warning in item.warnings)
    content.extend(item.logs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return path


def write_batch_log(batch: BatchOptimizationResult, path: Path) -> Path:
    lines = [
        f"project={batch.project_name}",
        f"status={batch.status.value}",
        f"elapsed_seconds={batch.elapsed_seconds:.6f}",
        f"succeeded={batch.succeeded_count}",
        f"failed={batch.failed_count}",
        f"skipped={batch.skipped_count}",
        f"cancelled={batch.cancelled_count}",
        f"dbc_write_failed={batch.dbc_write_failed_count}",
    ]
    lines.extend(f"warning={warning}" for warning in batch.warnings)
    lines.extend(f"error={error}" for error in batch.errors)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
