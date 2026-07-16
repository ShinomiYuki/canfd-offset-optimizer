"""! @file weight_mode_writer.py
@brief Write cross-weight summaries without comparing objectives expressed in different units.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..config import ProjectConfig
from ..models import AlgorithmComparisonResult, NetworkModel, ObjectiveValue, WeightMode
from .comparison_writer import build_comparison_summary
from .filenames import prefixed_report_name


def _objective_columns(prefix: str, value: ObjectiveValue) -> dict[str, int]:
    return {
        f"{prefix}_超限时隙数": value.violation_count,
        f"{prefix}_超限总量": value.violation_excess,
        f"{prefix}_稳态峰值": value.steady_peak,
        f"{prefix}_启动峰值": value.startup_peak,
        f"{prefix}_负载平方和": value.sum_square_load,
        f"{prefix}_最大释放帧数": value.max_release_count,
    }


def _improvement_percent(baseline: int, candidate: int) -> str:
    if baseline == 0:
        return ""
    return f"{(baseline - candidate) * 100 / baseline:.6f}"


def _milliseconds(value_us: int | None) -> str:
    if value_us is None:
        return ""
    return f"{value_us / 1_000:.3f}".rstrip("0").rstrip(".")


def _message_key(name: str, can_id: int) -> tuple[str, int]:
    return name, can_id


def write_weight_mode_reports(
    output_root: Path,
    payload_network: NetworkModel,
    payload_config: ProjectConfig,
    payload_result: AlgorithmComparisonResult,
    physical_network: NetworkModel,
    physical_config: ProjectConfig,
    physical_result: AlgorithmComparisonResult,
    report_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """! @brief Write two within-mode summaries and a read-only GCLS Offset diff."""
    if payload_network.weight_mode is not WeightMode.PAYLOAD_BYTES:
        raise ValueError("payload_network must use payload_bytes weights")
    if physical_network.weight_mode is not WeightMode.FRAME_TIME_US:
        raise ValueError("physical_network must use frame_time_us weights")
    results_dir = output_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = results_dir / prefixed_report_name(
        "weight_mode_comparison.csv", report_prefix
    )
    offsets_path = results_dir / prefixed_report_name(
        "offsets_weight_mode_comparison.csv", report_prefix
    )
    summary_path = results_dir / "weight_mode_summary.json"

    rows: list[dict[str, object]] = []
    mode_inputs = (
        ("payload_bytes", "payload-byte weight", payload_network, payload_result),
        ("frame_time_us", "microseconds", physical_network, physical_result),
    )
    for mode, unit, network, result in mode_inputs:
        original = result.stage("original")
        gcls = result.stage("gcls")
        rows.append(
            {
                "权重模式": mode,
                "目标负载单位": unit,
                "ARXML Controller": network.channel.name,
                "Nominal Bitrate(bit/s)": network.channel.nominal_bitrate or "",
                "Data Bitrate(bit/s)": network.channel.data_bitrate or "",
                "BRS": network.channel.brs,
                **_objective_columns("原始方案", original.objective),
                **_objective_columns("GCLS", gcls.objective),
                "稳态峰值改善率(%)": _improvement_percent(
                    original.objective.steady_peak, gcls.objective.steady_peak
                ),
                "启动峰值改善率(%)": _improvement_percent(
                    original.objective.startup_peak, gcls.objective.startup_peak
                ),
                "负载平方和改善率(%)": _improvement_percent(
                    original.objective.sum_square_load,
                    gcls.objective.sum_square_load,
                ),
                "评价次数": gcls.evaluation_count,
                "接受移动次数": gcls.accepted_moves,
                "运行时间(s)": f"{gcls.elapsed_seconds:.9f}",
            }
        )
    with comparison_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    physical_by_key = {
        _message_key(message.name, message.can_id): message
        for message in physical_result.messages
    }
    payload_keys = {
        _message_key(message.name, message.can_id) for message in payload_result.messages
    }
    if set(physical_by_key) != payload_keys:
        raise ValueError("weight modes must contain the same messages")
    payload_offsets = payload_result.stage("gcls").offset_by_name()
    physical_offsets = physical_result.stage("gcls").offset_by_name()
    offset_rows: list[dict[str, object]] = []
    for message in payload_result.messages:
        key = _message_key(message.name, message.can_id)
        physical_message = physical_by_key.get(key)
        if physical_message is None:
            raise ValueError(f"physical result is missing message {message.name!r}")
        if (
            physical_message.cycle_time_us != message.cycle_time_us
            or physical_message.payload_bytes != message.payload_bytes
        ):
            raise ValueError(f"weight modes disagree on metadata for {message.name!r}")
        payload_offset = payload_offsets[message.name]
        physical_offset = physical_offsets[message.name]
        offset_rows.append(
            {
                "报文名称": message.name,
                "CAN_ID": f"0x{message.can_id:X}",
                "周期(ms)": _milliseconds(message.cycle_time_us),
                "载荷长度(Byte)": message.payload_bytes,
                "保守帧占用时间(μs)": physical_message.frame_time_us,
                "DBC原始Offset(ms)": _milliseconds(message.original_offset_us),
                "payload_bytes_GCLS_Offset(ms)": _milliseconds(payload_offset),
                "frame_time_us_GCLS_Offset(ms)": _milliseconds(physical_offset),
                "是否变化": payload_offset != physical_offset,
            }
        )
    with offsets_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(offset_rows[0]))
        writer.writeheader()
        writer.writerows(offset_rows)

    changed_count = sum(row["是否变化"] is True for row in offset_rows)
    summary = {
        "comparison_semantics": (
            "Each mode is compared only with its own original assignment; raw Byte and "
            "microsecond objectives are not ranked against each other."
        ),
        "recommended_production_mode": "frame_time_us",
        "frame_time_boundary": (
            "Conservative ISO CAN FD estimate including 3 nominal-rate intermission bits; "
            "excludes arbitration loss, error frames, retransmission, queuing and ECU jitter."
        ),
        "changed_gcls_offset_count": changed_count,
        "message_count": len(offset_rows),
        "modes": {
            "payload_bytes": build_comparison_summary(
                payload_network, payload_config, payload_result
            ),
            "frame_time_us": build_comparison_summary(
                physical_network, physical_config, physical_result
            ),
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return comparison_path, offsets_path, summary_path


def write_all_network_offsets_report(dual_weight_root: Path) -> Path:
    """! @brief Aggregate every completed network's per-message dual-weight table."""
    required_fields = (
        "报文名称",
        "CAN_ID",
        "周期(ms)",
        "载荷长度(Byte)",
        "保守帧占用时间(μs)",
        "DBC原始Offset(ms)",
        "payload_bytes_GCLS_Offset(ms)",
        "frame_time_us_GCLS_Offset(ms)",
    )
    rows: list[dict[str, str]] = []
    for network_dir in sorted(
        (path for path in dual_weight_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        results_dir = network_dir / "results"
        if not (results_dir / "weight_mode_summary.json").is_file():
            continue
        preferred = results_dir / f"{network_dir.name}_offsets_weight_mode_comparison.csv"
        fallback = results_dir / "offsets_weight_mode_comparison.csv"
        source = preferred if preferred.is_file() else fallback
        if not source.is_file():
            continue
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = tuple(reader.fieldnames or ())
            missing = [field for field in required_fields if field not in fieldnames]
            if missing:
                raise ValueError(
                    f"{source} is missing required fields: {', '.join(missing)}"
                )
            for row in reader:
                rows.append(
                    {"网段": network_dir.name, **{field: row[field] for field in required_fields}}
                )
    if not rows:
        raise ValueError(f"no completed dual-weight network reports under {dual_weight_root}")
    path = dual_weight_root / "ALL_offsets_weight_mode_comparison.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path
