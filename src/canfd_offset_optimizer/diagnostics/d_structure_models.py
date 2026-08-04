"""Immutable data transfer objects for read-only D-structure diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

ExactnessStatus = Literal["exact", "bounded_only", "capped", "invalid_input"]
StructureClassification = Literal[
    "fixed_d_vector",
    "proven_constant_pstar",
    "multiple_reachable_pstar_levels",
    "incomplete_due_to_cap",
    "observed_single_level_only",
]


@dataclass(frozen=True, slots=True)
class DStructureLimits:
    """Fail-closed resource limits for one network."""

    max_histogram_states: int = 1_000_000
    max_exact_pstar_evaluations: int = 1_000_000
    timeout_s: float = 300.0

    def __post_init__(self) -> None:
        if self.max_histogram_states <= 0:
            raise ValueError("max_histogram_states must be positive")
        if self.max_exact_pstar_evaluations <= 0:
            raise ValueError("max_exact_pstar_evaluations must be positive")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")


@dataclass(frozen=True, slots=True)
class MessageDStructure:
    """Reachable D values and exact gcd fibers for one message."""

    message_key: str
    name: str
    can_id: int
    definition_index: int
    period_us: int
    is_fixed: bool
    allowed_offsets_us: tuple[int, ...]
    d_values_us: tuple[int, ...]
    fibers: tuple[tuple[int, tuple[int, ...]], ...]


@dataclass(frozen=True, slots=True)
class HistogramLayerStat:
    """One exact histogram-DP layer audit record."""

    message_index: int
    message_key: str
    input_state_count: int
    expansion_count: int
    output_state_count: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class ArchiveObservation:
    """One validated joint-archive solution projected to D/P*."""

    assignment_hash: str
    histogram: tuple[tuple[int, int], ...]
    pstar: Fraction
    exact_match: bool | None
    comparison_status: str


@dataclass(frozen=True, slots=True)
class DStructureResult:
    """Complete immutable result for one network."""

    network: str
    rho: Fraction
    messages: tuple[MessageDStructure, ...]
    reachable_d_union_us: tuple[int, ...]
    histograms: tuple[tuple[int, ...], ...]
    pstar_by_histogram: tuple[tuple[tuple[int, ...], Fraction], ...]
    pstar_levels: tuple[Fraction, ...]
    layer_stats: tuple[HistogramLayerStat, ...]
    archive_observations: tuple[ArchiveObservation, ...]
    product_dset_upper_bound: int
    stars_and_bars_upper_bound: int
    combined_histogram_upper_bound: int
    reachable_histogram_lower_bound: int
    histogram_enumeration_complete: bool
    pstar_evaluation_count: int
    exactness_status: ExactnessStatus
    structure_classification: StructureClassification
    stop_reason: str | None
    stop_message_index: int | None
    archive_histogram_count: int
    archive_pstar_level_count: int
    histogram_coverage: Fraction | None
    level_coverage: Fraction | None
    provenance_comparable: bool
    provenance_reasons: tuple[str, ...]
    manifest_path: Path
    manifest_sha256: str
    archive_path: Path | None
    archive_sha256: str | None
    archive_source_commit: str | None
    archive_source_worktree_status: str | None
    diagnostic_commit: str
    source_worktree_status: str
    eligible_set_sha256: str
    input_hashes: tuple[tuple[str, str], ...]
    configuration_hash: str
    decision_message_count: int
    fixed_message_count: int
    elapsed_seconds: float

    @property
    def reachable_histogram_count(self) -> int | None:
        return len(self.histograms) if self.histogram_enumeration_complete else None


def fraction_payload(value: Fraction) -> dict[str, int | float | str]:
    """Serialize an exact Fraction; float is display-only."""

    return {
        "exact": f"{value.numerator}/{value.denominator}",
        "numerator": value.numerator,
        "denominator": value.denominator,
        "display_value": float(value),
    }
