"""Independent finite checks for the theory-extension audit.

The script intentionally keeps its reference implementations local.  Production
MainFunction routines are imported only as one side of selected cross-checks;
they are never used to manufacture the corresponding reference answer.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import cache
from importlib import import_module
from itertools import product
from math import comb, gcd
from pathlib import Path
from time import perf_counter
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
MICROSECONDS_PER_SECOND = 1_000_000


@dataclass(slots=True)
class ClaimReport:
    """Machine-readable result for one independently checked claim."""

    claim_id: str
    status: str
    deterministic_cases: int
    random_cases: int
    counterexamples_found: int
    assumptions: list[str]
    elapsed_ms: int
    failure_details: list[str]


@dataclass(frozen=True, slots=True)
class TypeDpResult:
    """Result of the audit-local type-level subset DP."""

    cost: Fraction
    groups: tuple[tuple[int, ...], ...]
    states: int
    transitions: int


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _set_partitions(indices: tuple[int, ...]) -> Iterator[tuple[tuple[int, ...], ...]]:
    """Enumerate unordered set partitions without using the production DP."""

    if not indices:
        yield ()
        return
    first = indices[0]
    for partition in _set_partitions(indices[1:]):
        yield ((first,),) + partition
        for group_index in range(len(partition)):
            extended = list(partition)
            extended[group_index] = (first,) + extended[group_index]
            yield tuple(extended)


def _bell_reference(
    d_values: Sequence[int],
    rho: Fraction,
    *,
    item_costs: Sequence[int] | None = None,
    scale: int = MICROSECONDS_PER_SECOND,
) -> tuple[Fraction, tuple[tuple[int, ...], ...]]:
    """Message-level Bell oracle with optional identity-specific variable costs."""

    if not d_values:
        raise ValueError("Bell reference requires at least one item")
    variable_costs = tuple(item_costs) if item_costs is not None else (1,) * len(d_values)
    if len(variable_costs) != len(d_values):
        raise ValueError("item_costs and d_values must have equal length")

    best_key: tuple[Fraction, int, tuple[tuple[int, ...], ...]] | None = None
    for partition in _set_partitions(tuple(range(len(d_values)))):
        total = Fraction()
        group_signature: list[tuple[int, ...]] = []
        for group in partition:
            group_gcd = 0
            group_variable_cost = 0
            group_types: set[int] = set()
            for index in group:
                group_gcd = gcd(group_gcd, d_values[index])
                group_variable_cost += variable_costs[index]
                group_types.add(d_values[index])
            total += (rho + group_variable_cost) * scale / group_gcd
            group_signature.append(tuple(sorted(group_types)))
        canonical = tuple(sorted(group_signature))
        candidate = total, len(partition), canonical
        if best_key is None or candidate < best_key:
            best_key = candidate
    if best_key is None:
        raise AssertionError("Bell enumeration produced no partition")
    return best_key[0], best_key[2]


def _type_subset_dp(
    histogram: tuple[tuple[int, int], ...],
    rho: Fraction,
    *,
    scale: int = MICROSECONDS_PER_SECOND,
) -> TypeDpResult:
    """Audit-local recursive implementation of the canonical-anchor recurrence."""

    if not histogram:
        raise ValueError("type DP requires a non-empty histogram")
    d_values = tuple(item[0] for item in histogram)
    counts = tuple(item[1] for item in histogram)
    m = len(histogram)
    full_mask = (1 << m) - 1

    subset_gcd = [0] * (1 << m)
    subset_count = [0] * (1 << m)
    subset_signature: list[tuple[int, ...]] = [()] * (1 << m)
    for mask in range(1, 1 << m):
        lowbit = mask & -mask
        index = lowbit.bit_length() - 1
        previous = mask ^ lowbit
        subset_gcd[mask] = (
            d_values[index]
            if previous == 0
            else gcd(subset_gcd[previous], d_values[index])
        )
        subset_count[mask] = subset_count[previous] + counts[index]
        subset_signature[mask] = tuple(
            d_values[index] for index in range(m) if mask & (1 << index)
        )

    transitions = 0

    @cache
    def solve(mask: int) -> tuple[Fraction, tuple[tuple[int, ...], ...]]:
        nonlocal transitions
        if mask == 0:
            return Fraction(), ()
        anchor = mask & -mask
        rest = mask ^ anchor
        best: tuple[Fraction, int, tuple[tuple[int, ...], ...]] | None = None
        submask = rest
        while True:
            transitions += 1
            group_mask = submask | anchor
            remainder_cost, remainder_groups = solve(mask ^ group_mask)
            group_cost = (
                (rho + subset_count[group_mask]) * scale / subset_gcd[group_mask]
            )
            groups = tuple(
                sorted((subset_signature[group_mask],) + remainder_groups)
            )
            candidate = group_cost + remainder_cost, len(groups), groups
            if best is None or candidate < best:
                best = candidate
            if submask == 0:
                break
            submask = (submask - 1) & rest
        if best is None:
            raise AssertionError("type DP state had no transition")
        return best[0], best[2]

    cost, groups = solve(full_mask)
    # The production implementation materializes every DP state in increasing
    # mask order.  Force the same state-coverage accounting here after obtaining
    # the full optimum; memoization ensures this does not alter any recurrence.
    for mask in range(1 << m):
        solve(mask)
    return TypeDpResult(cost, groups, solve.cache_info().currsize, transitions)


def _production_api() -> tuple[Any, Any, Any]:
    """Load production routines after making the local ``src`` tree importable."""

    src_text = str(SRC_ROOT)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    module = import_module("canfd_offset_optimizer.optimization.main_function")
    return (
        module.MainFunctionMessage,
        module.solve_main_function_partition,
        module.solve_main_function_proxy_exact,
    )


def _partition_exists(weights: Sequence[int]) -> bool:
    """Independent SUBSET-SUM enumeration for PARTITION."""

    total = sum(weights)
    if total % 2:
        return False
    target = total // 2
    for mask in range(1 << len(weights)):
        subtotal = sum(weight for index, weight in enumerate(weights) if mask & (1 << index))
        if subtotal == target:
            return True
    return False


def _offset_reduction_exists(weights: Sequence[int]) -> bool:
    """Enumerate the explicit two-slot Offset instance produced by the reduction."""

    total = sum(weights)
    if total % 2:
        # Fixed explicit no-instance: weights 1 and 2, two slots, peak threshold 1.
        reduced_weights = (1, 2)
        threshold = 1
    else:
        reduced_weights = tuple(weights)
        threshold = total // 2
    for choices in product((0, 1), repeat=len(reduced_weights)):
        loads = [0, 0]
        for weight, slot in zip(reduced_weights, choices, strict=True):
            loads[slot] += weight
        if max(loads) <= threshold:
            return True
    return False


def _verify_v1(generator: random.Random, random_cases: int) -> ClaimReport:
    started = perf_counter()
    failures: list[str] = []
    deterministic = (
        (1, 1),
        (1, 2),
        (1, 2, 3),
        (1, 1, 1, 3),
        (2, 2, 3, 5),
        (3, 3, 3),
        (2, 4, 6, 8),
    )
    cases = list(deterministic)
    cases.extend(
        tuple(generator.randint(1, 20) for _ in range(generator.randint(1, 10)))
        for _ in range(random_cases)
    )
    for index, weights in enumerate(cases):
        expected = _partition_exists(weights)
        reduced = _offset_reduction_exists(weights)
        if expected != reduced:
            failures.append(
                f"case {index}: PARTITION={expected}, reduced Offset={reduced}, weights={weights}"
            )
    return ClaimReport(
        "V1_PARTITION_REDUCTION",
        "VERIFIED" if not failures else "FAILED",
        len(deterministic),
        random_cases,
        0,
        [
            "weights are arbitrary positive integers in the abstract weighted model",
            "even-sum instances use T=10 ms, offsets 15/20 ms and two explicit steady slots",
            "odd sums map to a fixed explicit no-instance",
        ],
        round((perf_counter() - started) * 1000),
        failures,
    )


def _release_slot(offset: int) -> int:
    """Return the stable slot for T=20, window [25,45), and Delta=5."""

    first = offset
    if first < 25:
        first += ((25 - first + 19) // 20) * 20
    if not 25 <= first < 45:
        raise AssertionError("constructed release is outside the stable window")
    return (first - 25) // 5


def _pareto_points(points: set[tuple[int, Fraction]]) -> set[tuple[int, Fraction]]:
    return {
        point
        for point in points
        if not any(
            other != point
            and other[0] <= point[0]
            and other[1] <= point[1]
            and (other[0] < point[0] or other[1] < point[1])
            for other in points
        )
    }


def _verify_v2() -> ClaimReport:
    started = perf_counter()
    failures: list[str] = []
    rhos = (
        Fraction(1, 10),
        Fraction(1, 2),
        Fraction(1),
        Fraction(3),
        Fraction(100),
    )
    weights = (1, 2, 7, 100)
    assignments = tuple(product((20, 25), repeat=2))
    for rho in rhos:
        for weight in weights:
            objective_image: set[tuple[int, Fraction]] = set()
            per_assignment: dict[tuple[int, int], tuple[int, Fraction]] = {}
            for assignment in assignments:
                loads = [0, 0, 0, 0]
                for offset in assignment:
                    loads[_release_slot(offset)] += weight
                qss = sum(load * load for load in loads)
                d_values = tuple(gcd(20, offset) for offset in assignment)
                pstar, _ = _bell_reference(d_values, rho, scale=1)
                point = qss, pstar
                per_assignment[assignment] = point
                objective_image.add(point)

            a = per_assignment[(20, 20)]
            b = per_assignment[(20, 25)]
            if a[0] != 4 * weight * weight or b[0] != 2 * weight * weight:
                failures.append(f"rho={rho}, w={weight}: unexpected Qss values {a[0]}, {b[0]}")
            if not (b[0] < a[0] and b[1] > a[1]):
                failures.append(f"rho={rho}, w={weight}: strict conflict failed: A={a}, B={b}")
            if per_assignment[(25, 20)] != b:
                failures.append(f"rho={rho}, w={weight}: symmetric assignments differ")
            if not (
                per_assignment[(25, 25)][0] == a[0]
                and per_assignment[(25, 25)][1] > a[1]
            ):
                failures.append(f"rho={rho}, w={weight}: (25,25) is not dominated by A")
            front = _pareto_points(objective_image)
            if front != {a, b}:
                failures.append(
                    f"rho={rho}, w={weight}: expected exactly A/B on front, got {front}"
                )
    return ClaimReport(
        "V2_STRICT_OBJECTIVE_CONFLICT",
        "VERIFIED" if not failures else "FAILED",
        len(rhos) * len(weights),
        0,
        0,
        [
            "unconstrained two-objective image, or a Peak guardrail admitting both A and B",
            "T1=T2=20 ms, offsets 20/25 ms, stable window [25,45), Delta=5 ms",
            "rho>0 and equal positive abstract communication weights",
        ],
        round((perf_counter() - started) * 1000),
        failures,
    )


def _histogram(d_values: Sequence[int]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(Counter(d_values).items()))


def _verify_histogram_instance(
    periods: Sequence[int],
    candidate_offsets: Sequence[Sequence[int]],
    rho: Fraction,
    production_proxy: Any,
) -> tuple[list[str], int, int]:
    failures: list[str] = []
    by_vector: defaultdict[tuple[int, ...], list[tuple[int, ...]]] = defaultdict(list)
    by_histogram: defaultdict[
        tuple[tuple[int, int], ...], list[tuple[tuple[int, ...], tuple[int, ...]]]
    ] = defaultdict(list)
    cost_by_histogram: dict[tuple[tuple[int, int], ...], Fraction] = {}

    for assignment in product(*candidate_offsets):
        d_vector = tuple(
            gcd(period, offset)
            for period, offset in zip(periods, assignment, strict=True)
        )
        histogram = _histogram(d_vector)
        reference, _ = _bell_reference(d_vector, rho)
        production = production_proxy(histogram, rho)
        if reference != production:
            failures.append(
                f"histogram={histogram}: Bell={reference}, production={production}"
            )
        previous = cost_by_histogram.setdefault(histogram, reference)
        if previous != reference:
            failures.append(
                f"same histogram changed reference P*: {histogram}, {previous}, {reference}"
            )
        by_vector[d_vector].append(tuple(assignment))
        by_histogram[histogram].append((tuple(assignment), d_vector))

    vector_collisions = sum(
        1
        for assignments in by_vector.values()
        if len(set(assignments)) > 1
    )
    permutation_collisions = 0
    for entries in by_histogram.values():
        vectors = {entry[1] for entry in entries}
        if len(vectors) > 1:
            permutation_collisions += 1
    return failures, vector_collisions, permutation_collisions


def _verify_v3(generator: random.Random, random_cases: int) -> ClaimReport:
    started = perf_counter()
    failures: list[str] = []
    _, _, production_proxy = _production_api()
    collisions = 0
    permutations = 0

    constructed = (
        ((12, 12), ((1, 5), (2, 10))),
        ((20, 20), ((20, 25), (20, 25))),
    )
    for periods, candidates in constructed:
        found, vector_count, permutation_count = _verify_histogram_instance(
            periods, candidates, Fraction(1), production_proxy
        )
        failures.extend(found)
        collisions += vector_count
        permutations += permutation_count

    period_pool = (4, 6, 8, 9, 10, 12, 15, 18, 20, 24)
    for case_index in range(random_cases):
        n = generator.randint(2, 4)
        periods = tuple(generator.choice(period_pool) for _ in range(n))
        candidates: list[tuple[int, ...]] = []
        for period in periods:
            population = tuple(range(0, 2 * period + 1))
            count = generator.randint(2, min(3, len(population)))
            candidates.append(tuple(sorted(generator.sample(population, count))))
        rho = generator.choice((Fraction(1, 10), Fraction(1), Fraction(3)))
        found, vector_count, permutation_count = _verify_histogram_instance(
            periods, tuple(candidates), rho, production_proxy
        )
        failures.extend(f"case {case_index}: {detail}" for detail in found)
        collisions += vector_count
        permutations += permutation_count

    # Deliberate boundary counterexample: identity-specific variable cost invalidates
    # histogram sufficiency although the two D multisets are identical.
    first, _ = _bell_reference((20, 5), Fraction(1), item_costs=(1, 10), scale=1)
    second, _ = _bell_reference((5, 20), Fraction(1), item_costs=(1, 10), scale=1)
    expected_counterexamples = int(first != second)
    if expected_counterexamples != 1:
        failures.append(
            "identity-specific cost counterexample did not separate equal histograms: "
            f"{first} versus {second}"
        )
    if collisions == 0 or permutations == 0:
        failures.append(
            f"required D-factorization witnesses missing: vectors={collisions}, "
            f"permutations={permutations}"
        )

    return ClaimReport(
        "V3_D_FACTORIZATION_AND_BOUNDARY",
        "VERIFIED" if not failures else "FAILED",
        len(constructed) + 1,
        random_cases,
        expected_counterexamples,
        [
            "current group cost depends only on common rho, group cardinality and gcd(D)",
            "no identity-specific costs or compatibility constraints in the current model",
            "the reported counterexample deliberately relaxes the identity-symmetry assumption",
        ],
        round((perf_counter() - started) * 1000),
        failures,
    )


def _verify_v4(generator: random.Random, random_cases: int) -> ClaimReport:
    started = perf_counter()
    failures: list[str] = []
    message_type, production_partition, _ = _production_api()
    fixed_histograms = (
        ((5, 1),),
        ((5, 2), (10, 1)),
        ((4, 2), (6, 1), (9, 1)),
        ((5, 1), (10, 2), (20, 2), (25, 1), (50, 1)),
    )
    cases: list[tuple[tuple[int, int], ...]] = list(fixed_histograms)
    d_pool = tuple(range(1, 61))
    for _ in range(random_cases):
        m = generator.randint(1, 7)
        d_values = sorted(generator.sample(d_pool, m))
        remaining = 7 - m
        counts = [1] * m
        for _ in range(generator.randint(0, remaining)):
            counts[generator.randrange(m)] += 1
        cases.append(tuple(zip(d_values, counts, strict=True)))

    for case_index, histogram in enumerate(cases):
        rho = generator.choice(
            (Fraction(1, 10), Fraction(1, 2), Fraction(1), Fraction(3))
        )
        expanded = tuple(d for d, count in histogram for _ in range(count))
        bell_cost, _ = _bell_reference(expanded, rho)
        audit_dp = _type_subset_dp(histogram, rho)
        expected_transitions = (3 ** len(histogram) - 1) // 2
        if audit_dp.cost != bell_cost:
            failures.append(
                f"case {case_index}: type DP={audit_dp.cost}, Bell={bell_cost}, "
                f"histogram={histogram}"
            )
        if audit_dp.states != 1 << len(histogram):
            failures.append(
                f"case {case_index}: states={audit_dp.states}, expected={1 << len(histogram)}"
            )
        if audit_dp.transitions != expected_transitions:
            failures.append(
                f"case {case_index}: transitions={audit_dp.transitions}, "
                f"expected={expected_transitions}"
            )

        messages = tuple(
            message_type(f"M{index:02d}", d, 0) for index, d in enumerate(expanded)
        )
        production = production_partition(messages, rho)
        production_groups = tuple(sorted(group.d_types_us for group in production.groups))
        if production.cpu_proxy != audit_dp.cost:
            failures.append(
                f"case {case_index}: production={production.cpu_proxy}, "
                f"audit DP={audit_dp.cost}"
            )
        if production_groups != audit_dp.groups:
            failures.append(
                f"case {case_index}: canonical groups differ: "
                f"production={production_groups}, audit={audit_dp.groups}"
            )

    return ClaimReport(
        "V4_TYPE_DP_VERSUS_BELL",
        "VERIFIED" if not failures else "FAILED",
        len(fixed_histograms),
        random_cases,
        0,
        [
            "rho is a positive exact Fraction",
            "the current identity-symmetric linear group cost is used",
            "message-level Bell enumeration is limited to n<=7",
        ],
        round((perf_counter() - started) * 1000),
        failures,
    )


def _divisor_count(value: int) -> int:
    count = 0
    for candidate in range(1, value + 1):
        if value % candidate == 0:
            count += 1
    return count


def _verify_v5(generator: random.Random, random_cases: int) -> ClaimReport:
    started = perf_counter()
    failures: list[str] = []
    deterministic_cases = (
        ((20, 20), ((20, 25), (20, 25)), (1, 1)),
        ((12, 18, 20), ((0, 1, 6), (0, 3, 9), (0, 5, 10)), (2, 3, 5)),
    )
    cases: list[
        tuple[tuple[int, ...], tuple[tuple[int, ...], ...], tuple[int, ...]]
    ] = list(deterministic_cases)
    period_pool = (4, 6, 8, 9, 10, 12, 15, 18, 20, 24)
    for _ in range(random_cases):
        n = generator.randint(2, 5)
        periods = tuple(generator.choice(period_pool) for _ in range(n))
        candidates: list[tuple[int, ...]] = []
        for period in periods:
            population = tuple(range(0, 2 * period + 1))
            count = generator.randint(1, min(3, len(population)))
            candidates.append(tuple(sorted(generator.sample(population, count))))
        weights = tuple(generator.randint(1, 7) for _ in range(n))
        cases.append((periods, tuple(candidates), weights))

    for case_index, (periods, candidates, weights) in enumerate(cases):
        dsets = tuple(
            {gcd(period, offset) for offset in offsets}
            for period, offsets in zip(periods, candidates, strict=True)
        )
        vector_upper = 1
        divisor_upper = 1
        for period, dset in zip(periods, dsets, strict=True):
            vector_upper *= len(dset)
            divisor_upper *= _divisor_count(period)
        union = set().union(*dsets)
        histogram_upper = min(
            vector_upper,
            comb(len(periods) + len(union) - 1, len(union) - 1),
        )

        vectors: set[tuple[int, ...]] = set()
        histograms: set[tuple[tuple[int, int], ...]] = set()
        pstar_values: set[Fraction] = set()
        pstar_cache: dict[tuple[tuple[int, int], ...], Fraction] = {}
        objective_points: set[tuple[int, Fraction]] = set()
        for assignment in product(*candidates):
            d_vector = tuple(
                gcd(period, offset)
                for period, offset in zip(periods, assignment, strict=True)
            )
            histogram = _histogram(d_vector)
            pstar = pstar_cache.get(histogram)
            if pstar is None:
                pstar = _type_subset_dp(histogram, Fraction(1), scale=1).cost
                pstar_cache[histogram] = pstar
            # A small deterministic communication image is sufficient for the
            # cardinality corollary: offsets select one of four abstract slots.
            loads = [0, 0, 0, 0]
            for offset, weight in zip(assignment, weights, strict=True):
                loads[offset % len(loads)] += weight
            qss = sum(load * load for load in loads)
            vectors.add(d_vector)
            histograms.add(histogram)
            pstar_values.add(pstar)
            objective_points.add((qss, pstar))

        pareto = _pareto_points(objective_points)
        checks = (
            (len(vectors) <= vector_upper, "D-vector count exceeds product Dset bound"),
            (vector_upper <= divisor_upper, "product Dset bound exceeds divisor bound"),
            (len(histograms) <= histogram_upper, "histogram count exceeds combined bound"),
            (len(pstar_values) <= len(histograms), "P* levels exceed reachable histograms"),
            (len(pareto) <= len(pstar_values), "Pareto points exceed P* levels"),
        )
        failures.extend(
            f"case {case_index}: {message}"
            for passed, message in checks
            if not passed
        )

    return ClaimReport(
        "V5_PSTAR_AND_PARETO_CARDINALITY_BOUNDS",
        "VERIFIED" if not failures else "FAILED",
        len(deterministic_cases),
        random_cases,
        0,
        [
            "P* factors through the D histogram under the current symmetric cost model",
            "Pareto cardinality counts distinct objective vectors, not assignments",
            "stars-and-bars is only an upper bound; not every histogram need be reachable",
        ],
        round((perf_counter() - started) * 1000),
        failures,
    )


def _markdown_report(
    seed: int,
    requested_random_cases: int,
    reports: Sequence[ClaimReport],
) -> str:
    lines = [
        "# Theory claim finite verification",
        "",
        f"- seed: `{seed}`",
        f"- requested random cases per randomized verifier: `{requested_random_cases}`",
        f"- Python: `{sys.version.split()[0]}`",
        "- Scope: independent finite enumeration and implementation cross-checks; "
        "**not a mathematical proof**.",
        "",
        "| claim_id | status | deterministic | random | expected boundary "
        "counterexamples | elapsed_ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        lines.append(
            f"| {report.claim_id} | {report.status} | {report.deterministic_cases} | "
            f"{report.random_cases} | {report.counterexamples_found} | "
            f"{report.elapsed_ms} |"
        )
    lines.extend(["", "## Assumptions and failures", ""])
    for report in reports:
        lines.append(f"### {report.claim_id}")
        lines.append("")
        lines.append(f"- status: **{report.status}**")
        lines.append("- assumptions:")
        lines.extend(f"  - {item}" for item in report.assumptions)
        if report.failure_details:
            lines.append("- failures:")
            lines.extend(f"  - {item}" for item in report.failure_details)
        else:
            lines.append("- failures: none")
        lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently enumerate finite instances for theory audit claims."
    )
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--random-cases", type=int, default=1000)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/diagnostics/theory_claims"),
    )
    args = parser.parse_args()
    if args.random_cases < 0:
        parser.error("--random-cases must be non-negative")
    return args


def main() -> int:
    args = _parse_args()
    generator = random.Random(args.seed)
    reports = [
        _verify_v1(generator, args.random_cases),
        _verify_v2(),
        _verify_v3(generator, args.random_cases),
        _verify_v4(generator, max(100, args.random_cases)),
        _verify_v5(generator, args.random_cases),
    ]
    payload = {
        "schema_version": 1,
        "seed": args.seed,
        "requested_random_cases": args.random_cases,
        "python_version": sys.version,
        "scope": (
            "Independent finite enumeration and implementation cross-checks; "
            "not a mathematical proof."
        ),
        "all_verified": all(report.status == "VERIFIED" for report in reports),
        "claims": [asdict(report) for report in reports],
    }

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "theory_claim_verification.json"
    markdown_path = output_dir / "theory_claim_verification.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        _markdown_report(args.seed, args.random_cases, reports) + "\n",
        encoding="utf-8",
    )

    print(markdown_path.read_text(encoding="utf-8"))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if payload["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
