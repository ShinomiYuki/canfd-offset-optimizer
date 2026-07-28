"""Exact knee recommendation and observed-front distance tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from canfd_offset_optimizer.optimization.joint_analysis import (
    normalized_symmetric_hausdorff_distance,
    select_joint_recommendation,
)


@dataclass(frozen=True)
class _Point:
    qss: int
    cpu_proxy: Fraction
    peak: int
    assignment_hash: str
    main_function_count: int = 1


def _point(
    qss: int,
    cpu_proxy: int | Fraction,
    name: str,
    *,
    peak: int = 10,
) -> _Point:
    return _Point(qss, Fraction(cpu_proxy), peak, name)


def test_geometric_knee_uses_maximum_exact_chord_score() -> None:
    front = (
        _point(0, 100, "can"),
        _point(20, 45, "knee"),
        _point(50, 25, "other"),
        _point(100, 0, "cpu"),
    )
    result = select_joint_recommendation(front)

    assert result.method == "geometric_knee"
    assert result.solution_hash == "knee"
    assert result.normalized_q == Fraction(1, 5)
    assert result.normalized_cpu == Fraction(9, 20)
    assert result.knee_score == Fraction(7, 20)


def test_straight_chord_uses_ideal_point_fallback() -> None:
    front = tuple(_point(qss, 100 - qss, f"p{qss}") for qss in (0, 25, 50, 75, 100))
    result = select_joint_recommendation(front)

    assert result.method == "ideal_point_fallback"
    assert result.solution_hash == "p50"
    assert result.knee_score == 0


def test_all_negative_internal_chord_scores_use_ideal_point_fallback() -> None:
    front = (
        _point(0, 100, "can"),
        _point(40, 80, "above-chord-1"),
        _point(60, 60, "above-chord-2"),
        _point(100, 0, "cpu"),
    )

    result = select_joint_recommendation(front)

    assert result.method == "ideal_point_fallback"
    assert result.knee_score is not None
    assert result.knee_score < 0


def test_unique_and_two_point_fronts_have_strict_defined_behavior() -> None:
    unique = select_joint_recommendation((_point(10, 20, "only"),))
    assert unique.method == "unique_solution"
    assert unique.solution_hash == "only"

    endpoints = select_joint_recommendation((_point(10, 20, "can"), _point(20, 10, "cpu")))
    assert endpoints.method == "no_interior_knee"
    assert endpoints.solution_hash is None
    assert endpoints.pareto_index is None


def test_knee_is_fraction_exact_order_independent_and_ignores_peak() -> None:
    front = (
        _point(0, 1, "a", peak=100),
        _point(1, Fraction(1, 3), "b", peak=900),
        _point(3, 0, "c", peak=1),
    )
    expected = select_joint_recommendation(front)
    reordered = select_joint_recommendation(tuple(reversed(front)))
    peak_changed = select_joint_recommendation(
        tuple(replace(item, peak=10_000 - item.peak) for item in front)
    )

    assert expected.method == "geometric_knee"
    assert expected.solution_hash == "b"
    assert reordered.solution_hash == expected.solution_hash
    assert peak_changed.solution_hash == expected.solution_hash
    assert expected.knee_score == Fraction(1, 3)


def test_empty_front_is_explicitly_not_recommended() -> None:
    result = select_joint_recommendation(())
    assert result.method == "invalid_empty_front"
    assert not result.has_recommendation


def test_normalized_symmetric_hausdorff_identity_and_reordering() -> None:
    front = ((10, Fraction(30)), (20, Fraction(20)), (30, Fraction(10)))
    assert normalized_symmetric_hausdorff_distance(front, front) == 0.0
    assert normalized_symmetric_hausdorff_distance(front, tuple(reversed(front))) == 0.0


def test_normalized_symmetric_hausdorff_shift_and_degenerate_axis() -> None:
    first = ((10, Fraction(30)), (20, Fraction(20)), (30, Fraction(10)))
    shifted = ((10, Fraction(30)), (25, Fraction(18)), (30, Fraction(10)))
    assert normalized_symmetric_hausdorff_distance(first, shifted) > 0

    same_q_first = ((10, Fraction(30)), (10, Fraction(20)))
    same_q_second = ((10, Fraction(30)), (10, Fraction(10)))
    distance = normalized_symmetric_hausdorff_distance(
        same_q_first,
        same_q_second,
    )
    assert 0 < distance <= 1


def test_hausdorff_rejects_empty_front() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        normalized_symmetric_hausdorff_distance((), ((1, Fraction(1)),))
