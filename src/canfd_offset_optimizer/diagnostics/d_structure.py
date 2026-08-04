"""Exact, read-only D-structure analysis over the production Joint domain."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from typing import cast

import yaml

from ..exact import normalize_rho
from ..final_experiment import FinalExperimentInput, load_final_experiment_project
from ..models import OffsetAssignment, hash_offset_assignments
from ..optimization.joint import JointDomain, build_joint_domain
from ..optimization.main_function import solve_main_function_proxy_exact
from ..parsers.project_loader import LoadedProject
from ..parsers.routing_parser import normalize_target_network
from .d_structure_models import (
    ArchiveObservation,
    DStructureLimits,
    DStructureResult,
    ExactnessStatus,
    HistogramLayerStat,
    MessageDStructure,
    StructureClassification,
)

NETWORK_ORDER = ("CH", "DA", "DK", "EP", "GL", "IC", "LC", "PT", "SU")
ExactSolver = Callable[[tuple[tuple[int, int], ...], Fraction], Fraction]
Clock = Callable[[], float]


class DStructureInputError(ValueError):
    """Raised when the locked diagnostic input cannot be validated."""


@dataclass(frozen=True, slots=True)
class HistogramEnumeration:
    """Result of the rolling exact histogram DP."""

    histograms: tuple[tuple[int, ...], ...]
    layer_stats: tuple[HistogramLayerStat, ...]
    complete: bool
    lower_bound: int
    stop_reason: str | None
    stop_message_index: int | None


@dataclass(frozen=True, slots=True)
class PstarEvaluation:
    """Bounded exact P* evaluation result."""

    values: tuple[tuple[tuple[int, ...], Fraction], ...]
    complete: bool
    stop_reason: str | None


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 for a regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _git(project_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ("git", *args),
            cwd=project_root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DStructureInputError(f"{field} must be a mapping with string keys")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise DStructureInputError(f"{field} must be a sequence")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DStructureInputError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DStructureInputError(f"{field} must be an integer")
    return value


def load_diagnostic_manifest(path: Path) -> dict[str, object]:
    """Load and minimally validate the locked nine-network manifest schema."""

    if not path.is_file():
        raise DStructureInputError(f"manifest does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = _mapping(loaded, "manifest")
    if _integer(manifest.get("schema_version"), "schema_version") != 1:
        raise DStructureInputError("unsupported manifest schema_version")
    if manifest.get("paper_ready_preflight") is not True:
        raise DStructureInputError("manifest paper_ready_preflight is not true")
    networks = _sequence(manifest.get("networks"), "networks")
    ids = tuple(
        _string(_mapping(item, "network entry").get("network"), "network") for item in networks
    )
    if ids != NETWORK_ORDER:
        raise DStructureInputError(f"manifest network order must be {NETWORK_ORDER}, got {ids}")
    _mapping(manifest.get("shared_inputs"), "shared_inputs")
    _mapping(manifest.get("optimization"), "optimization")
    return manifest


def _project_root(manifest_path: Path) -> Path:
    parent = manifest_path.resolve().parent
    return parent.parent if parent.name == "docs" else parent


def _resolve_input(project_root: Path, raw_path: object, field: str) -> Path:
    value = Path(_string(raw_path, field))
    return value if value.is_absolute() else project_root / value


def _network_entry(manifest: Mapping[str, object], network: str) -> dict[str, object]:
    for raw in _sequence(manifest.get("networks"), "networks"):
        item = _mapping(raw, "network entry")
        if item.get("network") == network:
            return item
    raise DStructureInputError(f"network {network!r} is absent from manifest")


def _spec_from_manifest(
    manifest_path: Path,
    manifest: Mapping[str, object],
    network: str,
) -> FinalExperimentInput:
    root = _project_root(manifest_path)
    shared = _mapping(manifest.get("shared_inputs"), "shared_inputs")
    item = _network_entry(manifest, network)
    protocol = _string(item.get("protocol"), f"{network}.protocol")
    return FinalExperimentInput(
        network_id=network,
        dbc_path=_resolve_input(root, item.get("dbc_path"), f"{network}.dbc_path"),
        selected_sender=_string(item.get("sender"), f"{network}.sender"),
        protocol=protocol,
        routing_excel_path=_resolve_input(
            root,
            shared.get("routing_excel_path"),
            "shared_inputs.routing_excel_path",
        ),
        routing_target_network=_string(
            item.get("routing_target_network"), f"{network}.routing_target_network"
        ),
        arxml_dir=_resolve_input(root, shared.get("arxml_dir"), "shared_inputs.arxml_dir"),
        config_path=_resolve_input(root, shared.get("config_path"), "shared_inputs.config_path"),
        channel=_string(item.get("channel"), f"{network}.channel"),
    )


def canonical_message_rows(loaded: LoadedProject) -> list[dict[str, object]]:
    """Reproduce the locked eligible-set hash without reading paper tables."""

    return [
        {
            "name": item.name,
            "can_id": item.can_id,
            "is_extended": item.is_extended,
            "cycle_time_us": item.cycle_time_us,
            "frame_time_us": item.frame_time_us,
            "definition_index": item.definition_index,
            "start_delay_us": item.original_offset_us,
        }
        for item in sorted(
            loaded.network.messages,
            key=lambda message: (message.definition_index, message.can_id, message.name),
        )
    ]


def eligible_set_hash(loaded: LoadedProject) -> str:
    return _canonical_hash(canonical_message_rows(loaded))


def _validate_file_hash(path: Path, expected: object, field: str) -> str:
    if not path.is_file():
        raise DStructureInputError(f"{field} does not exist: {path}")
    actual = sha256_file(path)
    if actual != _string(expected, f"{field}.sha256"):
        raise DStructureInputError(f"{field} SHA-256 mismatch")
    return actual


def validate_locked_inputs(
    manifest_path: Path,
    manifest: Mapping[str, object],
    network: str,
    spec: FinalExperimentInput,
    loaded: LoadedProject,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Validate file hashes, selected sender, routing, eligible set and domain facts."""

    item = _network_entry(manifest, network)
    shared = _mapping(manifest.get("shared_inputs"), "shared_inputs")
    hashes: list[tuple[str, str]] = []
    hashes.append(("dbc", _validate_file_hash(spec.dbc_path, item.get("dbc_sha256"), "dbc")))
    hashes.append(
        (
            "routing",
            _validate_file_hash(
                spec.routing_excel_path,
                shared.get("routing_excel_sha256"),
                "routing_excel",
            ),
        )
    )
    hashes.append(
        (
            "config",
            _validate_file_hash(spec.config_path, shared.get("config_sha256"), "config"),
        )
    )
    arxml_entries = _sequence(shared.get("arxml_files"), "shared_inputs.arxml_files")
    root = _project_root(manifest_path)
    for index, raw in enumerate(arxml_entries):
        entry = _mapping(raw, f"arxml_files[{index}]")
        path = _resolve_input(root, entry.get("path"), f"arxml_files[{index}].path")
        hashes.append(
            (
                f"arxml:{path.name}",
                _validate_file_hash(path, entry.get("sha256"), f"arxml_files[{index}]"),
            )
        )
    parsed = loaded.dbc_parse_result
    if parsed is None or parsed.selected_sender != spec.selected_sender:
        raise DStructureInputError(f"{network}: selected sender mismatch")
    if loaded.routing_table is None or loaded.routing_target_network != normalize_target_network(
        spec.routing_target_network
    ):
        raise DStructureInputError(f"{network}: routing provenance mismatch")
    if loaded.eligible_start_delay_unknown_count:
        raise DStructureInputError(f"{network}: eligible Offset contains unknown values")
    eligible = eligible_set_hash(loaded)
    if eligible != _string(item.get("eligible_set_sha256"), f"{network}.eligible_set_sha256"):
        raise DStructureInputError(f"{network}: eligible-set SHA-256 mismatch")
    names = [message.name for message in loaded.network.messages]
    keys = [
        (message.definition_index, message.can_id, message.name)
        for message in loaded.network.messages
    ]
    if len(names) != len(set(names)) or len(keys) != len(set(keys)):
        raise DStructureInputError(f"{network}: message keys are not unique")
    return eligible, tuple(sorted(hashes))


def message_d_structures(domain: JointDomain) -> tuple[MessageDStructure, ...]:
    """Compute exact reachable D sets and gcd fibers for the Joint domain."""

    fixed_names = {message.name for message in domain.fixed_messages}
    structures: list[MessageDStructure] = []
    for message in domain.all_messages:
        offsets = (0,) if message.name in fixed_names else message.allowed_offsets_us
        fibers: defaultdict[int, list[int]] = defaultdict(list)
        for offset in offsets:
            fibers[math.gcd(message.cycle_time_us, offset)].append(offset)
        canonical_fibers = tuple((d_us, tuple(fibers[d_us])) for d_us in sorted(fibers))
        structures.append(
            MessageDStructure(
                message_key=f"{message.definition_index}:{message.can_id}:{message.name}",
                name=message.name,
                can_id=message.can_id,
                definition_index=message.definition_index,
                period_us=message.cycle_time_us,
                is_fixed=message.name in fixed_names,
                allowed_offsets_us=offsets,
                d_values_us=tuple(d_us for d_us, _ in canonical_fibers),
                fibers=canonical_fibers,
            )
        )
    return tuple(structures)


def reachable_d_union(messages: Sequence[MessageDStructure]) -> tuple[int, ...]:
    return tuple(sorted({d_us for message in messages for d_us in message.d_values_us}))


def histogram_pairs(
    histogram: tuple[int, ...], d_union_us: tuple[int, ...]
) -> tuple[tuple[int, int], ...]:
    return tuple((d_us, count) for d_us, count in zip(d_union_us, histogram, strict=True) if count)


def enumerate_reachable_histograms(
    messages: Sequence[MessageDStructure],
    d_union_us: tuple[int, ...],
    limits: DStructureLimits,
    *,
    clock: Clock = perf_counter,
) -> HistogramEnumeration:
    """Run the rolling exact DP; never enumerate the Offset Cartesian product."""

    index_by_d = {d_us: index for index, d_us in enumerate(d_union_us)}
    previous: set[tuple[int, ...]] = {(0,) * len(d_union_us)}
    layer_stats: list[HistogramLayerStat] = []
    deadline = clock() + limits.timeout_s
    for message_index, message in enumerate(messages, start=1):
        layer_started = clock()
        next_states: set[tuple[int, ...]] = set()
        expansion_count = 0
        for state in sorted(previous):
            for d_us in message.d_values_us:
                if clock() >= deadline:
                    return HistogramEnumeration(
                        tuple(sorted(previous)),
                        tuple(layer_stats),
                        False,
                        len(previous),
                        "timeout",
                        message_index,
                    )
                expansion_count += 1
                values = list(state)
                values[index_by_d[d_us]] += 1
                next_states.add(tuple(values))
                if len(next_states) > limits.max_histogram_states:
                    return HistogramEnumeration(
                        tuple(sorted(previous)),
                        tuple(layer_stats),
                        False,
                        len(previous),
                        "max_histogram_states",
                        message_index,
                    )
        layer_stats.append(
            HistogramLayerStat(
                message_index,
                message.message_key,
                len(previous),
                expansion_count,
                len(next_states),
                clock() - layer_started,
            )
        )
        previous = next_states
    return HistogramEnumeration(
        tuple(sorted(previous)), tuple(layer_stats), True, len(previous), None, None
    )


def theoretical_bounds(
    messages: Sequence[MessageDStructure], d_union_us: tuple[int, ...]
) -> tuple[int, int, int]:
    product = math.prod(len(message.d_values_us) for message in messages)
    n = len(messages)
    r = len(d_union_us)
    stars = math.comb(n + r - 1, r - 1) if n and r else 0
    return product, stars, min(product, stars)


def classify_structure(
    *,
    complete: bool,
    histogram_count: int,
    pstar_levels: Sequence[Fraction],
    observed_pstar_levels: Sequence[Fraction] = (),
) -> StructureClassification:
    """Apply the fail-closed classification from the frozen design."""

    if not complete:
        return "incomplete_due_to_cap"
    if histogram_count == 1:
        return "fixed_d_vector"
    if len(pstar_levels) == 1:
        return "proven_constant_pstar"
    if len(pstar_levels) > 1:
        return "multiple_reachable_pstar_levels"
    if len(set(observed_pstar_levels)) == 1:
        return "observed_single_level_only"
    return "observed_single_level_only"


def evaluate_pstar_histograms(
    histograms: Sequence[tuple[int, ...]],
    d_union_us: tuple[int, ...],
    rho: Fraction,
    limits: DStructureLimits,
    *,
    solver: ExactSolver = solve_main_function_proxy_exact,
    deadline: float | None = None,
    clock: Clock = perf_counter,
) -> PstarEvaluation:
    """Call the production exact inner solver exactly once per unique histogram."""

    unique_histograms = tuple(sorted(set(histograms)))
    values: list[tuple[tuple[int, ...], Fraction]] = []
    for histogram in unique_histograms:
        if len(values) >= limits.max_exact_pstar_evaluations:
            return PstarEvaluation(tuple(values), False, "max_exact_pstar_evaluations")
        if deadline is not None and clock() >= deadline:
            return PstarEvaluation(tuple(values), False, "timeout")
        pairs = histogram_pairs(histogram, d_union_us)
        cache_key = (rho.numerator, rho.denominator, pairs)
        del cache_key  # Documents the required diagnostic cache key.
        values.append((histogram, solver(pairs, rho)))
    return PstarEvaluation(tuple(values), True, None)


def _fraction_from_payload(value: object, field: str) -> Fraction:
    if isinstance(value, dict):
        item = _mapping(value, field)
        exact = item.get("exact")
        if isinstance(exact, str):
            return Fraction(exact)
        numerator = _integer(item.get("numerator"), f"{field}.numerator")
        denominator = _integer(item.get("denominator"), f"{field}.denominator")
        return Fraction(numerator, denominator)
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return Fraction(value)
    raise DStructureInputError(f"{field} is not an exact Fraction payload")


def _archive_observations(
    archive_path: Path | None,
    domain: JointDomain,
    d_union_us: tuple[int, ...],
    pstar_map: Mapping[tuple[int, ...], Fraction],
    provenance_comparable: bool,
) -> tuple[ArchiveObservation, ...]:
    if archive_path is None or not archive_path.is_file():
        return ()
    raw = json.loads(archive_path.read_text(encoding="utf-8"))
    root = _mapping(raw, "archive")
    candidate_archive = _mapping(root.get("candidate_archive"), "candidate_archive")
    solutions = _sequence(candidate_archive.get("solutions"), "candidate_archive.solutions")
    messages_by_name = {message.name: message for message in domain.all_messages}
    expected_names = set(messages_by_name)
    observations: list[ArchiveObservation] = []
    for index, raw_solution in enumerate(solutions):
        solution = _mapping(raw_solution, f"solutions[{index}]")
        assignments = _sequence(solution.get("assignments"), f"solutions[{index}].assignments")
        offset_by_name: dict[str, int] = {}
        for raw_assignment in assignments:
            assignment = _mapping(raw_assignment, "archive assignment")
            name = _string(assignment.get("message_name"), "message_name")
            offset = _integer(assignment.get("Offset_us"), "Offset_us")
            if name in offset_by_name:
                raise DStructureInputError(f"archive has duplicate assignment for {name}")
            message = messages_by_name.get(name)
            if message is None:
                raise DStructureInputError(f"archive contains unknown message {name}")
            if _integer(assignment.get("CAN_ID"), "CAN_ID") != message.can_id:
                raise DStructureInputError(f"archive CAN ID mismatch for {name}")
            if (
                _integer(assignment.get("definition_index"), "definition_index")
                != message.definition_index
            ):
                raise DStructureInputError(f"archive definition index mismatch for {name}")
            offset_by_name[name] = offset
        if set(offset_by_name) != expected_names:
            raise DStructureInputError("archive assignment is incomplete")
        counter: Counter[int] = Counter()
        fixed_names = {message.name for message in domain.fixed_messages}
        for name, message in messages_by_name.items():
            offset = offset_by_name[name]
            allowed = (0,) if name in fixed_names else message.allowed_offsets_us
            if offset not in allowed:
                raise DStructureInputError(f"archive Offset {offset} is illegal for message {name}")
            counter[math.gcd(message.cycle_time_us, offset)] += 1
        assignment_hash = _string(solution.get("assignment_hash"), "assignment_hash")
        canonical_assignments = tuple(
            OffsetAssignment(
                message.name,
                message.can_id,
                offset_by_name[message.name],
                message.definition_index,
            )
            for message in domain.all_messages
        )
        if assignment_hash != hash_offset_assignments(canonical_assignments):
            raise DStructureInputError("archive assignment hash mismatch")
        histogram = tuple(counter.get(d_us, 0) for d_us in d_union_us)
        metrics = _mapping(solution.get("metrics"), f"solutions[{index}].metrics")
        pstar = _fraction_from_payload(
            metrics.get("CPU_proxy"), f"solutions[{index}].metrics.CPU_proxy"
        )
        expected = pstar_map.get(histogram)
        exact_match = expected == pstar if expected is not None else None
        if not provenance_comparable:
            comparison_status = "not_comparable"
        elif expected is None:
            comparison_status = "not_evaluated"
        elif exact_match:
            comparison_status = "exact_match"
        else:
            comparison_status = "pstar_mismatch"
        observations.append(
            ArchiveObservation(
                assignment_hash,
                histogram_pairs(histogram, d_union_us),
                pstar,
                exact_match,
                comparison_status,
            )
        )
    return tuple(sorted(observations, key=lambda item: item.assignment_hash))


def _archive_metadata_matches(
    archive_path: Path,
    network: str,
    rho: Fraction,
    domain: JointDomain,
) -> tuple[bool, tuple[str, ...]]:
    """Validate archive network, rho, and domain facts before coverage."""

    raw = json.loads(archive_path.read_text(encoding="utf-8"))
    root = _mapping(raw, "archive")
    reasons: list[str] = []
    if root.get("network") != network:
        reasons.append("archive network differs")
    configuration = root.get("configuration")
    if isinstance(configuration, dict):
        config = _mapping(configuration, "archive.configuration")
        try:
            archive_rho = _fraction_from_payload(config.get("rho"), "archive.configuration.rho")
        except DStructureInputError:
            reasons.append("archive rho is unavailable")
        else:
            if archive_rho != rho:
                reasons.append("archive rho differs")
    else:
        reasons.append("archive configuration is unavailable")
    domain_payload = root.get("domain")
    if isinstance(domain_payload, dict):
        archive_domain = _mapping(domain_payload, "archive.domain")
        if archive_domain.get("decision_message_count") != len(domain.decision_messages):
            reasons.append("archive decision-message count differs")
        if archive_domain.get("fixed_message_count") != len(domain.fixed_messages):
            reasons.append("archive fixed-message count differs")
    else:
        reasons.append("archive domain facts are unavailable")
    return not reasons, tuple(reasons)


def _archive_path_for(project_root: Path, network: str, override: Path | None) -> Path | None:
    if override is not None:
        if override.suffix.lower() == ".json":
            return override
        return override / network / "results" / f"{network}_joint_summary.json"
    default = (
        project_root
        / "output"
        / "final_paper_nine_network"
        / "joint"
        / network
        / "results"
        / f"{network}_joint_summary.json"
    )
    return default if default.is_file() else None


def analyze_network(
    manifest_path: Path,
    network: str,
    rho: Fraction | str | int,
    limits: DStructureLimits,
    *,
    archive: Path | None = None,
    solver: ExactSolver = solve_main_function_proxy_exact,
    clock: Clock = perf_counter,
) -> DStructureResult:
    """Analyze one locked network without mutating production inputs or configuration."""

    started = clock()
    normalized_rho = normalize_rho(rho)
    if network not in NETWORK_ORDER:
        raise DStructureInputError(f"unsupported network: {network}")
    manifest = load_diagnostic_manifest(manifest_path)
    root = _project_root(manifest_path)
    spec = _spec_from_manifest(manifest_path, manifest, network)
    loaded = load_final_experiment_project(spec)
    eligible_hash, input_hashes = validate_locked_inputs(
        manifest_path, manifest, network, spec, loaded
    )
    domain = build_joint_domain(loaded.network.messages, loaded.config.optimization)
    item = _network_entry(manifest, network)
    if len(domain.decision_messages) != _integer(item.get("joint_decision"), "joint_decision"):
        raise DStructureInputError(f"{network}: joint decision count mismatch")
    if len(domain.fixed_messages) != _integer(item.get("joint_fixed"), "joint_fixed"):
        raise DStructureInputError(f"{network}: joint fixed count mismatch")
    if any(message.allowed_offsets_us != (0,) for message in domain.fixed_messages):
        raise DStructureInputError(f"{network}: fixed message domain is not {{0}}")

    messages = message_d_structures(domain)
    d_union = reachable_d_union(messages)
    product_bound, stars_bound, combined_bound = theoretical_bounds(messages, d_union)
    enumeration = enumerate_reachable_histograms(messages, d_union, limits, clock=clock)
    stop_reason = enumeration.stop_reason
    stop_message_index = enumeration.stop_message_index
    complete = enumeration.complete
    pstar_evaluation = PstarEvaluation((), False, enumeration.stop_reason)
    if complete:
        pstar_evaluation = evaluate_pstar_histograms(
            enumeration.histograms,
            d_union,
            normalized_rho,
            limits,
            solver=solver,
            deadline=started + limits.timeout_s,
            clock=clock,
        )
        complete = pstar_evaluation.complete
        if not complete:
            stop_reason = pstar_evaluation.stop_reason
            stop_message_index = len(messages)
    pstar_items = list(pstar_evaluation.values)
    pstar_map = dict(pstar_items)
    pstar_levels = tuple(sorted(set(pstar_map.values())))

    archive_path = _archive_path_for(root, network, archive)
    archive_exists = archive_path is not None and archive_path.is_file()
    provenance_reasons: list[str] = []
    source_commit_raw = manifest.get("source_head_commit")
    source_worktree_raw = manifest.get("source_worktree_status")
    default_archive = _archive_path_for(root, network, None)
    archive_is_locked_default = bool(
        archive_exists
        and archive_path is not None
        and default_archive is not None
        and archive_path.resolve() == default_archive.resolve()
    )
    archive_source_commit = (
        source_commit_raw
        if archive_is_locked_default and isinstance(source_commit_raw, str)
        else None
    )
    archive_source_worktree_status = (
        source_worktree_raw
        if archive_is_locked_default and isinstance(source_worktree_raw, str)
        else None
    )
    diagnostic_commit = _git(root, "rev-parse", "HEAD")
    provenance_comparable = False
    preliminary_observations: tuple[ArchiveObservation, ...] = ()
    if archive_exists and archive_path is not None:
        provenance_reasons.extend(
            (
                "locked input hashes match manifest",
                "eligible-set hash matches manifest",
                "joint decision/fixed model facts match manifest",
            )
        )
        metadata_match, metadata_reasons = _archive_metadata_matches(
            archive_path, network, normalized_rho, domain
        )
        provenance_reasons.extend(metadata_reasons)
        preliminary_observations = _archive_observations(
            archive_path, domain, d_union, pstar_map, False
        )
        all_observations_recomputed = all(
            item.exact_match is True for item in preliminary_observations
        )
        if not archive_is_locked_default:
            provenance_reasons.append(
                "archive is outside the locked manifest output and has no trusted source binding"
            )
        if not complete:
            provenance_reasons.append(
                "current P* enumeration is incomplete; archive model facts cannot be fully checked"
            )
        if preliminary_observations and not all_observations_recomputed:
            provenance_reasons.append("archive P* facts do not all exactly recompute")
        provenance_comparable = (
            archive_is_locked_default
            and metadata_match
            and complete
            and all_observations_recomputed
        )
        if provenance_comparable:
            provenance_reasons.append("all archived P* facts exactly recompute")
        if archive_source_commit is not None and archive_source_commit != diagnostic_commit:
            provenance_reasons.append(
                (
                    "source commits differ; comparability established by hashes and exact model facts"
                    if provenance_comparable
                    else "source commits differ; comparability is not established"
                )
            )
    else:
        provenance_reasons.append("archive is absent")
    observations = tuple(
        ArchiveObservation(
            item.assignment_hash,
            item.histogram,
            item.pstar,
            item.exact_match,
            (
                "exact_match"
                if provenance_comparable and item.exact_match is True
                else "pstar_mismatch"
                if provenance_comparable and item.exact_match is False
                else "not_evaluated"
                if provenance_comparable
                else "not_comparable"
            ),
        )
        for item in preliminary_observations
    )
    observed_histograms = {item.histogram for item in observations}
    observed_levels = {item.pstar for item in observations}
    histogram_coverage = (
        Fraction(len(observed_histograms), len(enumeration.histograms))
        if complete and provenance_comparable and enumeration.histograms
        else None
    )
    level_coverage = (
        Fraction(len(observed_levels & set(pstar_levels)), len(pstar_levels))
        if complete and provenance_comparable and pstar_levels
        else None
    )
    classification = classify_structure(
        complete=complete,
        histogram_count=len(enumeration.histograms),
        pstar_levels=pstar_levels,
        observed_pstar_levels=tuple(observed_levels),
    )
    exactness: ExactnessStatus = "exact" if complete else "capped"
    configuration_hash = _canonical_hash(
        {
            "rho": f"{normalized_rho.numerator}/{normalized_rho.denominator}",
            "limits": asdict(limits),
            "manifest_optimization": manifest.get("optimization"),
            "network": network,
            "eligible_set_sha256": eligible_hash,
        }
    )
    return DStructureResult(
        network=network,
        rho=normalized_rho,
        messages=messages,
        reachable_d_union_us=d_union,
        histograms=enumeration.histograms,
        pstar_by_histogram=tuple(pstar_items),
        pstar_levels=pstar_levels,
        layer_stats=enumeration.layer_stats,
        archive_observations=observations,
        product_dset_upper_bound=product_bound,
        stars_and_bars_upper_bound=stars_bound,
        combined_histogram_upper_bound=combined_bound,
        reachable_histogram_lower_bound=enumeration.lower_bound,
        histogram_enumeration_complete=enumeration.complete,
        pstar_evaluation_count=len(pstar_items),
        exactness_status=exactness,
        structure_classification=classification,
        stop_reason=stop_reason,
        stop_message_index=stop_message_index,
        archive_histogram_count=len(observed_histograms),
        archive_pstar_level_count=len(observed_levels),
        histogram_coverage=histogram_coverage,
        level_coverage=level_coverage,
        provenance_comparable=provenance_comparable,
        provenance_reasons=tuple(provenance_reasons),
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        archive_path=archive_path.resolve() if archive_path is not None else None,
        archive_sha256=sha256_file(archive_path) if archive_exists and archive_path else None,
        archive_source_commit=archive_source_commit,
        archive_source_worktree_status=archive_source_worktree_status,
        diagnostic_commit=diagnostic_commit,
        source_worktree_status=_git(root, "status", "--short"),
        eligible_set_sha256=eligible_hash,
        input_hashes=input_hashes,
        configuration_hash=configuration_hash,
        decision_message_count=len(domain.decision_messages),
        fixed_message_count=len(domain.fixed_messages),
        elapsed_seconds=clock() - started,
    )


def analyze_manifest(
    manifest_path: Path,
    networks: Sequence[str],
    rho: Fraction | str | int,
    limits: DStructureLimits,
    *,
    archive: Path | None = None,
) -> tuple[DStructureResult, ...]:
    """Analyze networks in the fixed manifest order, with a timeout per network."""

    requested = set(networks)
    unknown = requested - set(NETWORK_ORDER)
    if unknown:
        raise DStructureInputError(f"unsupported networks: {sorted(unknown)}")
    return tuple(
        analyze_network(manifest_path, network, rho, limits, archive=archive)
        for network in NETWORK_ORDER
        if network in requested
    )
