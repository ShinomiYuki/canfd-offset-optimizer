"""Stable UTF-8/BOM CSV and exact JSON reports for D-structure diagnostics."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from .d_structure import histogram_pairs
from .d_structure_models import (
    DStructureLimits,
    DStructureResult,
    fraction_payload,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fraction_or_none(value: Fraction | None) -> dict[str, int | float | str] | None:
    return fraction_payload(value) if value is not None else None


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def result_summary_payload(
    result: DStructureResult,
    limits: DStructureLimits,
    *,
    command: str,
) -> dict[str, object]:
    """Build the versioned summary object with exact integers/Fractions."""

    return {
        "schema_version": 1,
        "network": result.network,
        "status": {
            "exactness_status": result.exactness_status,
            "structure_classification": result.structure_classification,
            "stop_reason": result.stop_reason,
            "stop_message_index": result.stop_message_index,
        },
        "domain": {
            "n": len(result.messages),
            "decision_message_count": result.decision_message_count,
            "fixed_message_count": result.fixed_message_count,
            "reachable_d_union_us": list(result.reachable_d_union_us),
            "r": len(result.reachable_d_union_us),
            "product_i_dset_size": result.product_dset_upper_bound,
            "stars_and_bars_upper_bound": result.stars_and_bars_upper_bound,
            "combined_histogram_upper_bound": result.combined_histogram_upper_bound,
        },
        "enumeration": {
            "histogram_enumeration_complete": result.histogram_enumeration_complete,
            "reachable_histogram_count": result.reachable_histogram_count,
            "reachable_histogram_lower_bound": result.reachable_histogram_lower_bound,
            "pstar_evaluation_count": result.pstar_evaluation_count,
            "reachable_pstar_level_count": len(result.pstar_levels),
            "pstar_levels": [fraction_payload(value) for value in result.pstar_levels],
            "layers": [asdict(item) for item in result.layer_stats],
        },
        "archive": {
            "path": str(result.archive_path) if result.archive_path is not None else None,
            "sha256": result.archive_sha256,
            "source_commit": result.archive_source_commit,
            "source_worktree_status": result.archive_source_worktree_status,
            "source_commit_matches_diagnostic": (
                result.archive_source_commit == result.diagnostic_commit
                if result.archive_source_commit is not None
                else None
            ),
            "observed_assignment_count": len(result.archive_observations),
            "observed_histogram_count": result.archive_histogram_count,
            "observed_pstar_level_count": result.archive_pstar_level_count,
            "histogram_coverage": _fraction_or_none(result.histogram_coverage),
            "level_coverage": _fraction_or_none(result.level_coverage),
            "provenance_comparable": result.provenance_comparable,
            "provenance_reasons": list(result.provenance_reasons),
        },
        "provenance": {
            "diagnostic_commit": result.diagnostic_commit,
            "source_worktree_status": result.source_worktree_status,
            "manifest_path": str(result.manifest_path),
            "manifest_sha256": result.manifest_sha256,
            "eligible_set_sha256": result.eligible_set_sha256,
            "input_hashes": dict(result.input_hashes),
            "configuration_hash": result.configuration_hash,
            "rho": fraction_payload(result.rho),
            "limits": asdict(limits),
            "command": command,
        },
        "elapsed_seconds": result.elapsed_seconds,
    }


def write_network_result(
    result: DStructureResult,
    output_root: Path,
    limits: DStructureLimits,
    *,
    command: str,
) -> Path:
    """Write all five per-network diagnostic artifacts."""

    directory = output_root / result.network / "d_structure"
    directory.mkdir(parents=True, exist_ok=True)
    _write_csv(
        directory / "d_structure_messages.csv",
        (
            "message_index",
            "message_key",
            "message_name",
            "CAN_ID",
            "definition_index",
            "period_us",
            "is_fixed",
            "allowed_offsets_us_json",
            "dset_us_json",
            "gcd_fibers_json",
        ),
        [
            {
                "message_index": index,
                "message_key": message.message_key,
                "message_name": message.name,
                "CAN_ID": message.can_id,
                "definition_index": message.definition_index,
                "period_us": message.period_us,
                "is_fixed": message.is_fixed,
                "allowed_offsets_us_json": _canonical_json(message.allowed_offsets_us),
                "dset_us_json": _canonical_json(message.d_values_us),
                "gcd_fibers_json": _canonical_json(
                    [
                        {"D_us": d_us, "offsets_us": list(offsets)}
                        for d_us, offsets in message.fibers
                    ]
                ),
            }
            for index, message in enumerate(result.messages, start=1)
        ],
    )
    pstar_map = dict(result.pstar_by_histogram)
    _write_csv(
        directory / "reachable_histograms.csv",
        (
            "histogram_index",
            "histogram_json",
            "pstar_exact",
            "pstar_numerator",
            "pstar_denominator",
        ),
        [
            {
                "histogram_index": index,
                "histogram_json": _canonical_json(
                    histogram_pairs(histogram, result.reachable_d_union_us)
                ),
                "pstar_exact": (
                    f"{pstar_map[histogram].numerator}/{pstar_map[histogram].denominator}"
                    if histogram in pstar_map
                    else ""
                ),
                "pstar_numerator": pstar_map[histogram].numerator if histogram in pstar_map else "",
                "pstar_denominator": (
                    pstar_map[histogram].denominator if histogram in pstar_map else ""
                ),
            }
            for index, histogram in enumerate(result.histograms, start=1)
        ],
    )
    pstar_counts = {
        value: sum(1 for _, pstar in result.pstar_by_histogram if pstar == value)
        for value in result.pstar_levels
    }
    _write_csv(
        directory / "pstar_levels.csv",
        ("level_index", "pstar_exact", "pstar_numerator", "pstar_denominator", "histogram_count"),
        [
            {
                "level_index": index,
                "pstar_exact": f"{value.numerator}/{value.denominator}",
                "pstar_numerator": value.numerator,
                "pstar_denominator": value.denominator,
                "histogram_count": pstar_counts[value],
            }
            for index, value in enumerate(result.pstar_levels, start=1)
        ],
    )
    _write_csv(
        directory / "archive_comparison.csv",
        (
            "assignment_hash",
            "histogram_json",
            "pstar_exact",
            "pstar_numerator",
            "pstar_denominator",
            "comparison_status",
            "exact_match",
        ),
        [
            {
                "assignment_hash": item.assignment_hash,
                "histogram_json": _canonical_json(item.histogram),
                "pstar_exact": f"{item.pstar.numerator}/{item.pstar.denominator}",
                "pstar_numerator": item.pstar.numerator,
                "pstar_denominator": item.pstar.denominator,
                "comparison_status": item.comparison_status,
                "exact_match": item.exact_match if item.exact_match is not None else "",
            }
            for item in result.archive_observations
        ],
    )
    summary_path = directory / "d_structure_summary.json"
    summary_path.write_text(
        json.dumps(
            result_summary_payload(result, limits, command=command),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path


def _batch_row(result: DStructureResult) -> dict[str, object]:
    return {
        "network": result.network,
        "n": len(result.messages),
        "decision_messages": result.decision_message_count,
        "fixed_messages": result.fixed_message_count,
        "reachable_d_union_json": _canonical_json(result.reachable_d_union_us),
        "r": len(result.reachable_d_union_us),
        "product_i_dset_size": result.product_dset_upper_bound,
        "stars_and_bars_upper_bound": result.stars_and_bars_upper_bound,
        "combined_histogram_upper_bound": result.combined_histogram_upper_bound,
        "reachable_histogram_count": (
            result.reachable_histogram_count if result.reachable_histogram_count is not None else ""
        ),
        "reachable_histogram_lower_bound": result.reachable_histogram_lower_bound,
        "reachable_pstar_level_count": len(result.pstar_levels),
        "archive_observed_histogram_count": result.archive_histogram_count,
        "archive_observed_pstar_level_count": result.archive_pstar_level_count,
        "histogram_coverage_exact": (
            fraction_payload(result.histogram_coverage)["exact"]
            if result.histogram_coverage is not None
            else ""
        ),
        "level_coverage_exact": (
            fraction_payload(result.level_coverage)["exact"]
            if result.level_coverage is not None
            else ""
        ),
        "exactness_status": result.exactness_status,
        "structure_classification": result.structure_classification,
        "provenance_comparable": result.provenance_comparable,
        "elapsed_seconds": result.elapsed_seconds,
    }


def write_batch_summary(
    results: tuple[DStructureResult, ...],
    output_root: Path,
    limits: DStructureLimits,
    *,
    command: str,
) -> tuple[Path, Path]:
    """Write deterministic fixed-order nine-network summary files."""

    rows = [_batch_row(result) for result in results]
    csv_path = output_root / "d_structure_nine_network_summary.csv"
    fields = tuple(rows[0]) if rows else ("network",)
    _write_csv(csv_path, fields, rows)
    json_path = output_root / "d_structure_nine_network_summary.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": command,
                "limits": asdict(limits),
                "networks": rows,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path
