"""Exact D-set, histogram-DP, classification and report tests."""

from __future__ import annotations

import csv
import json
from collections import Counter
from fractions import Fraction
from itertools import product
from pathlib import Path

import pytest

from canfd_offset_optimizer.cli import build_parser, main
from canfd_offset_optimizer.config import OptimizationConfig, RestartPolicy
from canfd_offset_optimizer.diagnostics.d_structure import (
    classify_structure,
    DStructureInputError,
    _archive_observations,
    enumerate_reachable_histograms,
    evaluate_pstar_histograms,
    message_d_structures,
    reachable_d_union,
    theoretical_bounds,
)
from canfd_offset_optimizer.diagnostics.d_structure_models import (
    ArchiveObservation,
    DStructureLimits,
    DStructureResult,
    HistogramLayerStat,
    MessageDStructure,
    fraction_payload,
)
from canfd_offset_optimizer.diagnostics.d_structure_report import write_network_result
from canfd_offset_optimizer.models import CanMessage, OffsetAssignment, hash_offset_assignments
from canfd_offset_optimizer.optimization.joint import build_joint_domain


def _message(
    name: str,
    index: int,
    period_us: int,
    offsets: tuple[int, ...],
) -> CanMessage:
    return CanMessage(
        name=name,
        can_id=0x100 + index,
        is_extended=False,
        cycle_time_us=period_us,
        frame_time_us=100,
        allowed_offsets_us=offsets,
        original_offset_us=offsets[0],
        sender_ecu="ECU",
        definition_index=index,
    )


def _config(offset_max_us: int = 20_000) -> OptimizationConfig:
    return OptimizationConfig(
        slot_width_us=1_000,
        offset_min_us=0,
        offset_max_us=offset_max_us,
        offset_step_us=1_000,
        hyperperiod_cap_us=1_000_000,
        restart_policy=RestartPolicy.fixed(1),
        conflict_candidate_cap=4,
        variance_offset_cap=2,
    )


def _structure(name: str, index: int, d_values: tuple[int, ...]) -> MessageDStructure:
    return MessageDStructure(
        message_key=f"{index}:{0x100 + index}:{name}",
        name=name,
        can_id=0x100 + index,
        definition_index=index,
        period_us=60,
        is_fixed=False,
        allowed_offsets_us=d_values,
        d_values_us=d_values,
        fibers=tuple((value, (value,)) for value in d_values),
    )


def test_dset_gcd_fibers_and_offset_zero_are_exact() -> None:
    domain = build_joint_domain((_message("m", 0, 12_000, (0, 6_000, 10_000)),), _config())
    message = message_d_structures(domain)[0]
    assert message.d_values_us == (2_000, 6_000, 12_000)
    assert message.fibers == (
        (2_000, (10_000,)),
        (6_000, (6_000,)),
        (12_000, (0,)),
    )


def test_fixed_message_uses_only_zero_and_period_as_d() -> None:
    domain = build_joint_domain((_message("slow", 0, 60_000, (5_000, 10_000)),), _config(20_000))
    message = message_d_structures(domain)[0]
    assert message.is_fixed
    assert message.allowed_offsets_us == (0,)
    assert message.d_values_us == (60_000,)


def test_reachable_dset_is_not_completed_to_all_positive_divisors() -> None:
    domain = build_joint_domain((_message("m", 0, 12_000, (5_000, 6_000)),), _config())
    assert message_d_structures(domain)[0].d_values_us == (1_000, 6_000)


def test_histogram_dp_matches_small_cartesian_oracle_and_is_order_stable() -> None:
    messages = (
        _structure("a", 0, (1, 2)),
        _structure("b", 1, (1, 3)),
        _structure("c", 2, (2, 3)),
    )
    union = reachable_d_union(messages)
    limits = DStructureLimits(100, 100, 10)
    forward = enumerate_reachable_histograms(messages, union, limits)
    reverse = enumerate_reachable_histograms(tuple(reversed(messages)), union, limits)
    oracle = {
        tuple(Counter(choice).get(value, 0) for value in union)
        for choice in product(*(message.d_values_us for message in messages))
    }
    assert forward.complete
    assert set(forward.histograms) == oracle
    assert forward.histograms == reverse.histograms
    assert all(item.output_state_count <= item.expansion_count for item in forward.layer_stats)


def test_histogram_dp_caps_at_cap_plus_one_fail_closed() -> None:
    messages = tuple(_structure(str(index), index, (1, 2, 3)) for index in range(3))
    result = enumerate_reachable_histograms(
        messages,
        (1, 2, 3),
        DStructureLimits(3, 100, 10),
    )
    assert not result.complete
    assert result.stop_reason == "max_histogram_states"
    assert result.stop_message_index == 2
    assert result.lower_bound == 3


def test_histogram_dp_timeout_is_fail_closed() -> None:
    values = iter((0.0, 0.0, 2.0))
    result = enumerate_reachable_histograms(
        (_structure("a", 0, (1, 2)),),
        (1, 2),
        DStructureLimits(100, 100, 1.0),
        clock=lambda: next(values),
    )
    assert not result.complete
    assert result.stop_reason == "timeout"
    assert result.lower_bound == 1


def test_each_unique_histogram_calls_exact_solver_once_and_uses_fraction() -> None:
    calls: list[tuple[tuple[int, int], ...]] = []

    def solver(histogram: tuple[tuple[int, int], ...], rho: Fraction) -> Fraction:
        calls.append(histogram)
        return Fraction(sum(d_us * count for d_us, count in histogram), 1) * rho

    histograms = ((1, 1), (2, 0), (1, 1))
    result = evaluate_pstar_histograms(
        histograms,
        (5, 10),
        Fraction(1, 3),
        DStructureLimits(100, 100, 10),
        solver=solver,
    )
    assert result.complete
    assert len(calls) == 2
    assert all(isinstance(value, Fraction) for _, value in result.values)
    assert len({value for _, value in result.values}) <= len(result.values)


def test_pstar_cap_stops_before_extra_solver_call() -> None:
    calls = 0

    def solver(histogram: tuple[tuple[int, int], ...], rho: Fraction) -> Fraction:
        nonlocal calls
        calls += 1
        return rho

    result = evaluate_pstar_histograms(
        ((1, 0), (0, 1)),
        (5, 10),
        Fraction(1),
        DStructureLimits(100, 1, 10),
        solver=solver,
    )
    assert not result.complete
    assert result.stop_reason == "max_exact_pstar_evaluations"
    assert calls == 1


def test_archive_comparison_is_fraction_exact_and_fail_closed(tmp_path: Path) -> None:
    domain = build_joint_domain((_message("m", 0, 12_000, (6_000, 10_000)),), _config())
    assignment = OffsetAssignment("m", 0x100, 6_000, 0)
    assignment_hash = hash_offset_assignments((assignment,))
    archive = tmp_path / "archive.json"
    archive.write_text(
        json.dumps(
            {
                "candidate_archive": {
                    "solutions": [
                        {
                            "assignment_hash": assignment_hash,
                            "assignments": [
                                {
                                    "message_name": "m",
                                    "CAN_ID": 0x100,
                                    "Offset_us": 6_000,
                                    "definition_index": 0,
                                }
                            ],
                            "metrics": {
                                "CPU_proxy": {
                                    "exact": "2/3",
                                    "numerator": 2,
                                    "denominator": 3,
                                }
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    not_comparable = _archive_observations(archive, domain, (2_000, 6_000), {}, False)
    assert not_comparable[0].comparison_status == "not_comparable"
    assert not_comparable[0].exact_match is None
    comparable = _archive_observations(
        archive,
        domain,
        (2_000, 6_000),
        {(0, 1): Fraction(3, 4)},
        True,
    )
    assert comparable[0].comparison_status == "pstar_mismatch"
    assert comparable[0].exact_match is False

    raw = json.loads(archive.read_text(encoding="utf-8"))
    raw["candidate_archive"]["solutions"][0]["assignment_hash"] = "wrong"
    archive.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DStructureInputError, match="hash mismatch"):
        _archive_observations(archive, domain, (2_000, 6_000), {}, False)


def test_theoretical_bounds_cover_reachable_histograms() -> None:
    messages = (_structure("a", 0, (1, 2)), _structure("b", 1, (1, 2, 3)))
    union = reachable_d_union(messages)
    product_bound, stars_bound, combined = theoretical_bounds(messages, union)
    count = len(
        enumerate_reachable_histograms(messages, union, DStructureLimits(100, 100, 10)).histograms
    )
    assert count <= product_bound
    assert count <= stars_bound
    assert combined == min(product_bound, stars_bound)


def test_classification_never_promotes_observed_single_level_to_constant() -> None:
    assert (
        classify_structure(
            complete=True,
            histogram_count=2,
            pstar_levels=(),
            observed_pstar_levels=(Fraction(1),),
        )
        == "observed_single_level_only"
    )
    assert (
        classify_structure(
            complete=False,
            histogram_count=2,
            pstar_levels=(Fraction(1),),
            observed_pstar_levels=(Fraction(1),),
        )
        == "incomplete_due_to_cap"
    )
    assert (
        classify_structure(complete=True, histogram_count=1, pstar_levels=(Fraction(1),))
        == "fixed_d_vector"
    )
    assert (
        classify_structure(complete=True, histogram_count=2, pstar_levels=(Fraction(1),))
        == "proven_constant_pstar"
    )
    assert (
        classify_structure(
            complete=True, histogram_count=2, pstar_levels=(Fraction(1), Fraction(2))
        )
        == "multiple_reachable_pstar_levels"
    )


def _report_result(tmp_path: Path) -> DStructureResult:
    message = _structure("a", 0, (5,))
    return DStructureResult(
        network="CH",
        rho=Fraction(1, 3),
        messages=(message,),
        reachable_d_union_us=(5,),
        histograms=((1,),),
        pstar_by_histogram=(((1,), Fraction(2, 3)),),
        pstar_levels=(Fraction(2, 3),),
        layer_stats=(HistogramLayerStat(1, message.message_key, 1, 1, 1, 0.1),),
        archive_observations=(
            ArchiveObservation("abc", ((5, 1),), Fraction(2, 3), True, "exact_match"),
        ),
        product_dset_upper_bound=1,
        stars_and_bars_upper_bound=1,
        combined_histogram_upper_bound=1,
        reachable_histogram_lower_bound=1,
        histogram_enumeration_complete=True,
        pstar_evaluation_count=1,
        exactness_status="exact",
        structure_classification="fixed_d_vector",
        stop_reason=None,
        stop_message_index=None,
        archive_histogram_count=1,
        archive_pstar_level_count=1,
        histogram_coverage=Fraction(1),
        level_coverage=Fraction(1),
        provenance_comparable=True,
        provenance_reasons=("hashes match",),
        manifest_path=tmp_path / "manifest.yaml",
        manifest_sha256="m",
        archive_path=tmp_path / "archive.json",
        archive_sha256="a",
        archive_source_commit="old",
        archive_source_worktree_status="M old-source",
        diagnostic_commit="new",
        source_worktree_status="",
        eligible_set_sha256="e",
        input_hashes=(("dbc", "d"),),
        configuration_hash="c",
        decision_message_count=1,
        fixed_message_count=0,
        elapsed_seconds=0.2,
    )


def test_reports_use_utf8_bom_exact_fraction_and_stable_compound_json(tmp_path: Path) -> None:
    limits = DStructureLimits(10, 10, 5)
    write_network_result(_report_result(tmp_path), tmp_path, limits, command="cmd")
    directory = tmp_path / "CH" / "d_structure"
    for name in (
        "d_structure_messages.csv",
        "reachable_histograms.csv",
        "pstar_levels.csv",
        "archive_comparison.csv",
    ):
        assert (directory / name).read_bytes().startswith(b"\xef\xbb\xbf")
    summary = json.loads((directory / "d_structure_summary.json").read_text(encoding="utf-8"))
    assert summary["provenance"]["rho"] == fraction_payload(Fraction(1, 3))
    with (directory / "reachable_histograms.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert json.loads(row["histogram_json"]) == [[5, 1]]


def test_cli_help_and_invalid_input_status(tmp_path: Path) -> None:
    args = build_parser().parse_args(("analyze-d-structure", "--network", "CH"))
    assert args.max_histogram_states == 1_000_000
    assert (
        main(
            (
                "analyze-d-structure",
                "--manifest",
                str(tmp_path / "missing.yaml"),
                "--network",
                "CH",
                "--output-root",
                str(tmp_path / "out"),
            )
        )
        == 2
    )
    failure = json.loads(
        (tmp_path / "out" / "d_structure_invalid_input.json").read_text(encoding="utf-8")
    )
    assert failure["exactness_status"] == "invalid_input"
