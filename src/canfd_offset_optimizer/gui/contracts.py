"""Immutable GUI DTOs for workspace import and all-network optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from pathlib import Path
from threading import Event
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, runtime_checkable

from ..config import OffsetSearchConfig


class InputKind(str, Enum):
    """File classifications exposed by an import backend."""

    DBC = "dbc"
    CONFIG = "config"
    ARXML = "arxml"
    ROUTING_TABLE = "routing_table"
    OTHER_SUPPORTED = "other_supported"
    UNRECOGNIZED = "unrecognized"
    INVALID = "invalid"


class ImportRecordStatus(str, Enum):
    """Stable status for one source file or invalid source path."""

    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    CONFLICT_RENAMED = "conflict_renamed"
    INVALID = "invalid"


class OptimizationMode(str, Enum):
    PEAK = "peak"
    BALANCED = "balanced"
    VARIANCE = "variance"


class WeightMode(str, Enum):
    PAYLOAD_BYTES = "payload_bytes"
    FRAME_TIME_US = "frame_time_us"


class FrameProtocol(str, Enum):
    CLASSIC_CAN = "classic_can"
    CAN_FD = "can_fd"


class RouteMatchStatus(str, Enum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    INVALID_CAN_ID = "invalid_can_id"


class RouteExclusionStatus(str, Enum):
    EXCLUDED = "routing_excluded"
    ALREADY_EXCLUDED = "duplicate_routing_excluded"
    NOT_EXCLUDED = "not_excluded"


class RouteRecordIssue(str, Enum):
    NAME_MISMATCH_WARNING = "name_mismatch_warning"
    DUPLICATE = "duplicate"
    DUPLICATE_CONFLICT_WARNING = "duplicate_conflict_warning"


class SenderSelectionDbcStatus(str, Enum):
    UNPROCESSED = "unprocessed"
    SELECTED = "selected"
    EXCLUDED_BY_USER = "excluded_by_user"
    NO_IDENTIFIABLE_TRANSMITTER = "no_identifiable_transmitter"
    INPUT_ERROR = "input_error"


class MessageEligibilityStatus(str, Enum):
    FINAL_ELIGIBLE = "final_eligible"
    BASE_ELIGIBLE = "base_eligible"
    EXCLUDED_UNSELECTED_TRANSMITTER = "excluded_unselected_transmitter"
    EXCLUDED_BY_USER = "excluded_by_user"
    NON_PERIODIC = "non_periodic"
    UNSUPPORTED_SEND_TYPE = "unsupported_send_type"
    ROUTING_EXCLUDED = "routing_excluded"
    NO_VALID_TRANSMITTER = "no_valid_transmitter"
    INPUT_ERROR = "input_error"


CLASSIC_WEIGHT_MODEL = "payload_bytes_approximation"


class RestartMode(str, Enum):
    ADAPTIVE = "adaptive"
    FIXED = "fixed"


class ProgressPhase(str, Enum):
    IMPORTING = "importing"
    INSPECTING = "inspecting"
    PREPARING = "preparing"
    NETWORK_RUNNING = "network_running"
    FINALIZING = "finalizing"


class NetworkRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class BatchRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class BackendAvailability:
    """Whether a backend can create real engineering optimization results."""

    can_optimize: bool
    backend_name: str
    message: str = ""

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("backend_name must not be empty")
        if not self.can_optimize and not self.message.strip():
            raise ValueError("unavailable backend requires an explanatory message")


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """Manifest record for one discovered source file or invalid source path."""

    original_path: Path
    workspace_relative_path: Path | None
    kind: InputKind
    status: ImportRecordStatus
    size_bytes: int | None
    sha256: str | None
    imported_at: str
    used_by_parser: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if not self.original_path.is_absolute():
            raise ValueError("manifest original_path must be absolute")
        if self.status is ImportRecordStatus.INVALID:
            if self.workspace_relative_path is not None:
                raise ValueError("invalid source must not have a workspace path")
        elif self.workspace_relative_path is None:
            raise ValueError("copied or duplicate source requires a workspace path")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("manifest size must be non-negative")
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ValueError("manifest sha256 must use 64 hexadecimal characters")
        if not self.imported_at:
            raise ValueError("manifest import time must not be empty")


@dataclass(frozen=True, slots=True)
class ImportSession:
    """One immutable user_input workspace session."""

    session_id: str
    project_name: str
    workspace_root: Path
    session_directory: Path
    manifest_path: Path
    created_at: str
    records: tuple[ImportRecord, ...]

    def __post_init__(self) -> None:
        if not self.session_id or not self.project_name:
            raise ValueError("import session identity must not be empty")
        if not self.session_directory.is_absolute() or not self.manifest_path.is_absolute():
            raise ValueError("import session paths must be absolute")
        if not self.records:
            raise ValueError("import session must contain at least one record")

    def records_of_kind(self, kind: InputKind) -> tuple[ImportRecord, ...]:
        return tuple(record for record in self.records if record.kind is kind)


@dataclass(frozen=True, slots=True)
class RouteMessageKey:
    """Stable routing exclusion key: imported network identity plus CAN ID."""

    target_network_id: str
    can_id: int

    def __post_init__(self) -> None:
        if not self.target_network_id.strip():
            raise ValueError("routing target_network_id must not be empty")
        if not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("routing CAN ID is outside the CAN identifier range")


@dataclass(frozen=True, slots=True)
class RouteMessageRecord:
    """One normalized source row read from a routing exclusion workbook."""

    target_network_raw: str
    can_id_raw: str
    can_id: int | None
    message_name: str | None
    source_file: str
    sheet_name: str
    row_number: int
    target_network_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_file.strip() or not self.sheet_name.strip():
            raise ValueError("routing source file and sheet must not be empty")
        if self.row_number <= 0:
            raise ValueError("routing row_number must be positive")
        if self.can_id is not None and not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("routing CAN ID is outside the CAN identifier range")
        if self.target_network_id is not None and not self.target_network_id.strip():
            raise ValueError("routing target_network_id must not be blank")


@dataclass(frozen=True, slots=True)
class RouteMatchRecord:
    """Auditable result of matching one Excel row against parsed DBC messages."""

    route: RouteMessageRecord
    target_network_id: str | None
    dbc_message_name: str | None
    match_status: RouteMatchStatus
    exclusion_status: RouteExclusionStatus
    issues: tuple[RouteRecordIssue, ...] = ()
    note: str = ""
    dbc_is_extended: bool | None = None

    def __post_init__(self) -> None:
        if len(set(self.issues)) != len(self.issues):
            raise ValueError("routing record issues must be unique")
        if self.match_status is RouteMatchStatus.MATCHED:
            if self.target_network_id is None or self.route.can_id is None:
                raise ValueError("matched routing row requires a normalized key")
            if self.dbc_message_name is None:
                raise ValueError("matched routing row requires a DBC message")
            if self.exclusion_status is RouteExclusionStatus.NOT_EXCLUDED:
                raise ValueError("matched routing row must describe its exclusion")
        elif self.exclusion_status is not RouteExclusionStatus.NOT_EXCLUDED:
            raise ValueError("unmatched routing row must not exclude a message")

    @property
    def key(self) -> RouteMessageKey | None:
        if self.target_network_id is None or self.route.can_id is None:
            return None
        return RouteMessageKey(self.target_network_id, self.route.can_id)


@dataclass(frozen=True, slots=True)
class RoutingExclusionReport:
    """Project-level immutable routing exclusion audit."""

    table_count: int = 0
    records: tuple[RouteMatchRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.table_count < 0:
            raise ValueError("routing table_count must be non-negative")

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def matched_count(self) -> int:
        return sum(
            record.match_status is RouteMatchStatus.MATCHED
            for record in self.records
        )

    @property
    def not_found_count(self) -> int:
        return sum(
            record.match_status is RouteMatchStatus.NOT_FOUND for record in self.records
        )

    @property
    def ambiguous_count(self) -> int:
        return sum(
            record.match_status is RouteMatchStatus.AMBIGUOUS for record in self.records
        )

    @property
    def invalid_can_id_count(self) -> int:
        return sum(
            record.match_status is RouteMatchStatus.INVALID_CAN_ID
            for record in self.records
        )

    @property
    def duplicate_count(self) -> int:
        return sum(
            RouteRecordIssue.DUPLICATE in record.issues for record in self.records
        )

    @property
    def excluded_keys(self) -> frozenset[RouteMessageKey]:
        return frozenset(
            record.key
            for record in self.records
            if record.match_status is RouteMatchStatus.MATCHED and record.key is not None
        )

    @property
    def excluded_message_count(self) -> int:
        return len(self.excluded_keys)

    def excluded_can_ids(self, network_id: str) -> frozenset[int]:
        return frozenset(
            key.can_id for key in self.excluded_keys if key.target_network_id == network_id
        )


@dataclass(frozen=True, slots=True)
class SenderNodeStats:
    node_name: str
    message_count: int
    valid_periodic_count: int
    classic_can_count: int
    can_fd_count: int
    base_candidate_count: int
    note: str = ""
    selectable: bool = True

    def __post_init__(self) -> None:
        if not self.node_name.strip():
            raise ValueError("sender node name must not be empty")
        counts = (
            self.message_count,
            self.valid_periodic_count,
            self.classic_can_count,
            self.can_fd_count,
            self.base_candidate_count,
        )
        if min(counts) < 0 or self.classic_can_count + self.can_fd_count != self.message_count:
            raise ValueError("sender node counts are inconsistent")


@dataclass(frozen=True, slots=True)
class MessageEligibilityRecord:
    dbc_id: str
    dbc_file: str
    network_id: str
    network_name: str
    can_id: int | None
    is_extended: bool
    message_name: str
    transmitter_nodes: tuple[str, ...]
    selected_transmitter_match: bool
    cycle_time_us: int | None
    frame_protocol: FrameProtocol | None
    base_eligible: bool
    routing_match: bool
    final_status: MessageEligibilityStatus
    exclusion_reason: str = ""

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.dbc_id, self.dbc_file, self.network_id, self.message_name)):
            raise ValueError("message eligibility identity must not be empty")
        if self.can_id is not None and not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("message eligibility CAN ID is invalid")
        normalized = tuple(name.strip() for name in self.transmitter_nodes)
        if any(not name for name in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("transmitter nodes must be unique non-empty names")
        object.__setattr__(self, "transmitter_nodes", normalized)
        if self.cycle_time_us is not None and self.cycle_time_us <= 0:
            raise ValueError("cycle time must be positive when present")


@dataclass(frozen=True, slots=True)
class DbcSenderSelectionSummary:
    dbc_id: str
    dbc_file: str
    network_id: str
    network_name: str
    source_workspace_path: Path
    sha256: str
    node_stats: tuple[SenderNodeStats, ...]
    messages: tuple[MessageEligibilityRecord, ...]
    status: SenderSelectionDbcStatus = SenderSelectionDbcStatus.UNPROCESSED
    selected_transmitters: tuple[str, ...] = ()
    excluded_by_user: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.dbc_id, self.dbc_file, self.network_id, self.sha256)):
            raise ValueError("DBC sender selection identity must not be empty")
        if self.source_workspace_path.is_absolute():
            raise ValueError("DBC sender selection path must be workspace-relative")
        if len(self.sha256) != 64:
            raise ValueError("DBC sender selection SHA-256 is invalid")
        names = tuple(item.node_name for item in self.node_stats)
        if len(set(names)) != len(names):
            raise ValueError("DBC sender node names must be unique")
        selected = tuple(name.strip() for name in self.selected_transmitters)
        if any(name not in names for name in selected) or len(set(selected)) != len(selected):
            raise ValueError("selected transmitters must exist in the DBC inventory")
        object.__setattr__(self, "selected_transmitters", selected)
        if self.excluded_by_user and selected:
            raise ValueError("excluded DBC must not retain selected transmitters")

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def selected_sender_message_count(self) -> int:
        return sum(record.selected_transmitter_match for record in self.messages)

    @property
    def base_eligible_count(self) -> int:
        return sum(
            record.base_eligible
            and record.selected_transmitter_match
            and record.final_status is not MessageEligibilityStatus.INPUT_ERROR
            for record in self.messages
        )

    @property
    def unselected_transmitter_count(self) -> int:
        return sum(
            record.final_status is MessageEligibilityStatus.EXCLUDED_UNSELECTED_TRANSMITTER
            for record in self.messages
        )

    @property
    def routing_excluded_count(self) -> int:
        return sum(record.final_status is MessageEligibilityStatus.ROUTING_EXCLUDED for record in self.messages)

    @property
    def final_eligible_count(self) -> int:
        return sum(record.final_status is MessageEligibilityStatus.FINAL_ELIGIBLE for record in self.messages)


@dataclass(frozen=True, slots=True)
class SenderNodeSelectionConfig:
    selected_transmitters_by_dbc: Mapping[str, frozenset[str]] = field(default_factory=dict)
    excluded_dbc_ids: frozenset[str] = frozenset()
    confirmed: bool = False
    dbc_revision: str = ""

    def __post_init__(self) -> None:
        normalized: dict[str, frozenset[str]] = {}
        for dbc_id, names in self.selected_transmitters_by_dbc.items():
            key = dbc_id.strip()
            values = frozenset(name.strip() for name in names if name.strip())
            if not key or not values:
                raise ValueError("sender selection entries require a DBC ID and node names")
            normalized[key] = values
        excluded = frozenset(value.strip() for value in self.excluded_dbc_ids if value.strip())
        if set(normalized).intersection(excluded):
            raise ValueError("a DBC cannot be both selected and excluded")
        if self.confirmed and not self.dbc_revision.strip():
            raise ValueError("confirmed sender selection requires a DBC revision")
        object.__setattr__(self, "selected_transmitters_by_dbc", MappingProxyType(normalized))
        object.__setattr__(self, "excluded_dbc_ids", excluded)

    def selected_for(self, dbc_id: str) -> frozenset[str]:
        return self.selected_transmitters_by_dbc.get(dbc_id, frozenset())

    def is_complete_for(self, dbc_ids: frozenset[str]) -> bool:
        handled = frozenset(self.selected_transmitters_by_dbc).union(self.excluded_dbc_ids)
        return handled == dbc_ids


@dataclass(frozen=True, slots=True)
class NetworkSummary:
    """One discovered network with stable identity and explicit source metadata."""

    network_id: str
    network_name: str
    display_name: str
    source_file: str
    source_workspace_path: Path
    is_optimizable: bool
    message_count: int
    available_weight_modes: tuple[WeightMode, ...]
    frame_protocol: FrameProtocol = FrameProtocol.CAN_FD
    automatic_weight_mode: WeightMode | None = None
    classic_weight_model: str | None = None
    base_eligible_message_count: int | None = None
    routing_excluded_count: int = 0
    final_eligible_message_count: int | None = None
    warnings: tuple[str, ...] = ()
    unoptimizable_reason: str | None = None
    dbc_id: str | None = None
    dbc_message_count: int = 0
    selected_transmitters: tuple[str, ...] = ()
    selected_transmitter_message_count: int = 0
    unselected_transmitter_excluded_count: int = 0
    excluded_by_user: bool = False

    def __post_init__(self) -> None:
        identity = (self.network_id, self.network_name, self.display_name, self.source_file)
        if any(not value.strip() for value in identity):
            raise ValueError("network identity and source fields must not be empty")
        if self.source_workspace_path.is_absolute():
            raise ValueError("network source_workspace_path must be relative")
        if self.message_count < 0:
            raise ValueError("network message_count must be non-negative")
        sender_counts = (
            self.dbc_message_count,
            self.selected_transmitter_message_count,
            self.unselected_transmitter_excluded_count,
        )
        if min(sender_counts) < 0:
            raise ValueError("network sender selection counts must be non-negative")
        if self.dbc_id is not None and not self.dbc_id.strip():
            raise ValueError("network dbc_id must not be blank")
        if len(set(self.selected_transmitters)) != len(self.selected_transmitters):
            raise ValueError("selected transmitter names must be unique")
        base_count = (
            self.message_count
            if self.base_eligible_message_count is None
            else self.base_eligible_message_count
        )
        final_count = (
            self.message_count
            if self.final_eligible_message_count is None
            else self.final_eligible_message_count
        )
        if min(base_count, self.routing_excluded_count, final_count) < 0:
            raise ValueError("network routing eligibility counts must be non-negative")
        if base_count - self.routing_excluded_count != final_count:
            raise ValueError("network routing eligibility counts are inconsistent")
        if self.message_count != final_count:
            raise ValueError("network message_count must equal final eligible count")
        if self.is_optimizable and self.message_count <= 0:
            raise ValueError("optimizable network message_count must be positive")
        if self.is_optimizable and not self.available_weight_modes:
            raise ValueError("optimizable network must provide at least one weight mode")
        if not self.is_optimizable and not self.unoptimizable_reason:
            raise ValueError("non-optimizable network requires a reason")
        if any(not isinstance(mode, WeightMode) for mode in self.available_weight_modes):
            raise ValueError("network weight mode is unsupported")
        if len(set(self.available_weight_modes)) != len(self.available_weight_modes):
            raise ValueError("network weight modes must be unique")
        if not isinstance(self.frame_protocol, FrameProtocol):
            raise ValueError("network frame protocol is unsupported")
        if self.automatic_weight_mode is not None and (
            self.automatic_weight_mode not in self.available_weight_modes
        ):
            raise ValueError("automatic weight must be a concrete available mode")
        if self.frame_protocol is FrameProtocol.CLASSIC_CAN:
            if self.is_optimizable and self.effective_weight_mode is not WeightMode.PAYLOAD_BYTES:
                raise ValueError("Classic CAN must use payload_bytes")
            if self.classic_weight_model != CLASSIC_WEIGHT_MODEL:
                raise ValueError("Classic CAN must declare its approximation model")

    @property
    def effective_weight_mode(self) -> WeightMode:
        if self.automatic_weight_mode is not None:
            return self.automatic_weight_mode
        if WeightMode.FRAME_TIME_US in self.available_weight_modes:
            return WeightMode.FRAME_TIME_US
        if self.available_weight_modes:
            return self.available_weight_modes[0]
        raise ValueError("non-optimizable network has no effective weight")


@dataclass(frozen=True, slots=True)
class WorkspaceInspection:
    """Workspace-only inspection result used to gate batch optimization."""

    session: ImportSession
    networks: tuple[NetworkSummary, ...]
    missing_required: tuple[InputKind, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    routing_exclusion: RoutingExclusionReport = field(
        default_factory=RoutingExclusionReport
    )
    sender_selection: SenderNodeSelectionConfig = field(
        default_factory=SenderNodeSelectionConfig
    )
    sender_selection_summaries: tuple[DbcSenderSelectionSummary, ...] = ()
    dbc_revision: str = ""

    def __post_init__(self) -> None:
        network_ids = tuple(network.network_id for network in self.networks)
        if len(set(network_ids)) != len(network_ids):
            raise ValueError("inspection network IDs must be unique")
        if len(set(self.missing_required)) != len(self.missing_required):
            raise ValueError("missing input kinds must be unique")
        summary_ids = tuple(summary.dbc_id for summary in self.sender_selection_summaries)
        if len(set(summary_ids)) != len(summary_ids):
            raise ValueError("sender selection DBC IDs must be unique")
        if self.sender_selection_summaries and not self.dbc_revision.strip():
            raise ValueError("sender selection inventories require a DBC revision")
        if self.sender_selection_summaries:
            network_dbc_ids = frozenset(
                network.dbc_id for network in self.networks if network.dbc_id is not None
            )
            if network_dbc_ids != frozenset(summary_ids):
                raise ValueError("sender selection inventories must match discovered DBCs")

    @property
    def can_optimize(self) -> bool:
        return (
            bool(self.optimizable_networks)
            and not self.missing_required
            and not self.errors
            and self.sender_selection_ready
        )

    @property
    def can_select_senders(self) -> bool:
        return bool(self.sender_selection_summaries) and not self.missing_required and not self.errors

    @property
    def sender_selection_ready(self) -> bool:
        if not self.sender_selection_summaries:
            return True
        dbc_ids = frozenset(item.dbc_id for item in self.sender_selection_summaries)
        if not (
            self.sender_selection.confirmed
            and self.sender_selection.dbc_revision == self.dbc_revision
            and self.sender_selection.is_complete_for(dbc_ids)
        ):
            return False
        return all(
            (
                summary.dbc_id in self.sender_selection.excluded_dbc_ids
                and summary.excluded_by_user
                and not summary.selected_transmitters
            )
            or (
                summary.dbc_id not in self.sender_selection.excluded_dbc_ids
                and frozenset(summary.selected_transmitters)
                == self.sender_selection.selected_for(summary.dbc_id)
                and bool(summary.selected_transmitters)
            )
            for summary in self.sender_selection_summaries
        )

    @property
    def optimizable_networks(self) -> tuple[NetworkSummary, ...]:
        return tuple(network for network in self.networks if network.is_optimizable)

    @property
    def base_eligible_message_count(self) -> int:
        return sum(
            network.message_count
            if network.base_eligible_message_count is None
            else network.base_eligible_message_count
            for network in self.networks
        )

    @property
    def routing_excluded_message_count(self) -> int:
        return sum(network.routing_excluded_count for network in self.networks)

    @property
    def final_eligible_message_count(self) -> int:
        return sum(
            network.message_count
            if network.final_eligible_message_count is None
            else network.final_eligible_message_count
            for network in self.networks
        )


@dataclass(frozen=True, slots=True)
class RestartSettings:
    mode: RestartMode = RestartMode.ADAPTIVE
    fixed_attempts: int = 21
    min_attempts: int = 20
    max_attempts: int = 80

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RestartMode):
            raise ValueError("restart mode is unsupported")
        values = (self.fixed_attempts, self.min_attempts, self.max_attempts)
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in values
        ):
            raise ValueError("restart attempts must be positive integers")
        if self.min_attempts > self.max_attempts:
            raise ValueError("adaptive min_attempts must not exceed max_attempts")


@dataclass(frozen=True, slots=True)
class GuiBatchOptimizationRequest:
    """One immutable request applied to every discovered network."""

    inspection: WorkspaceInspection
    can_fd_weight: WeightMode
    mode: OptimizationMode
    balanced_tolerance: float
    restart: RestartSettings
    candidate_pool_size: int
    enable_triple_search: bool
    output_root: Path
    classic_can_weight: WeightMode = WeightMode.PAYLOAD_BYTES
    offset_search: OffsetSearchConfig = field(default_factory=OffsetSearchConfig)
    sender_selection: SenderNodeSelectionConfig = field(
        default_factory=SenderNodeSelectionConfig
    )

    def __post_init__(self) -> None:
        if not self.inspection.can_optimize:
            raise ValueError("workspace inspection is not ready for optimization")
        if not isinstance(self.can_fd_weight, WeightMode):
            raise ValueError("CAN FD weight mode is unsupported")
        if self.classic_can_weight is not WeightMode.PAYLOAD_BYTES:
            raise ValueError("Classic CAN weight must be payload_bytes")
        if not isinstance(self.mode, OptimizationMode):
            raise ValueError("optimization mode is unsupported")
        if not isinstance(self.restart, RestartSettings):
            raise ValueError("restart settings are invalid")
        if not isfinite(self.balanced_tolerance) or not 0 <= self.balanced_tolerance <= 1:
            raise ValueError("balanced_tolerance must be finite and in [0, 1]")
        if self.candidate_pool_size not in {1, 4, 8, 16, 32}:
            raise ValueError("candidate_pool_size is unsupported")
        if not isinstance(self.enable_triple_search, bool):
            raise ValueError("enable_triple_search must be boolean")
        if not isinstance(self.offset_search, OffsetSearchConfig):
            raise ValueError("offset_search must be an OffsetSearchConfig")
        if self.inspection.sender_selection_summaries:
            if not self.sender_selection.confirmed:
                raise ValueError("DBC sender node selection is not confirmed")
            if self.sender_selection != self.inspection.sender_selection:
                raise ValueError("request sender selection does not match the inspection")
        if any(
            self.can_fd_weight not in network.available_weight_modes
            for network in self.inspection.optimizable_networks
            if network.frame_protocol is FrameProtocol.CAN_FD
        ):
            raise ValueError("selected weight mode is not available for every CAN FD network")
        if self.output_root.exists() and not self.output_root.is_dir():
            raise ValueError("output_root must be a directory")

    @property
    def weight_mode(self) -> WeightMode:
        """Backward-compatible alias for the CAN FD selection."""
        return self.can_fd_weight


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """Thread-safe project or per-network progress update."""

    phase: ProgressPhase
    message: str
    elapsed_seconds: float = 0.0
    network_id: str | None = None
    network_name: str | None = None
    network_index: int | None = None
    network_total: int | None = None
    network_status: NetworkRunStatus | None = None
    attempt: int | None = None
    total_attempts: int | None = None
    overall_completed: int = 0
    overall_total: int = 0

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("progress message must not be empty")
        if not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("progress elapsed_seconds must be non-negative")
        if (self.network_index is None) != (self.network_total is None):
            raise ValueError("network index and total must appear together")
        if self.network_index is not None and (
            self.network_index <= 0
            or self.network_total is None
            or self.network_total <= 0
            or self.network_index > self.network_total
            or not self.network_id
            or not self.network_name
        ):
            raise ValueError("progress network range is invalid")
        if (self.attempt is None) != (self.total_attempts is None):
            raise ValueError("attempt and total_attempts must appear together")
        if self.attempt is not None and (
            self.attempt < 0
            or self.total_attempts is None
            or self.total_attempts <= 0
            or self.attempt > self.total_attempts
        ):
            raise ValueError("progress attempt range is invalid")
        if self.overall_completed < 0 or self.overall_total < 0:
            raise ValueError("overall progress must be non-negative")
        if self.overall_total and self.overall_completed > self.overall_total:
            raise ValueError("overall completed must not exceed total")


@dataclass(frozen=True, slots=True)
class ObjectiveMetrics:
    zss: int
    qss: int
    standard_deviation: float
    zst: int
    qst: int
    nvio: int | None
    vvio: int | None

    def __post_init__(self) -> None:
        integer_values = (self.zss, self.qss, self.zst, self.qst)
        if any(value < 0 for value in integer_values):
            raise ValueError("objective metrics must be non-negative")
        if any(value is not None and value < 0 for value in (self.nvio, self.vvio)):
            raise ValueError("physical violation metrics must be non-negative or N/A")
        if not isfinite(self.standard_deviation) or self.standard_deviation < 0:
            raise ValueError("standard_deviation must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class OffsetAssignmentRow:
    message_name: str
    can_id: int
    cycle_time_us: int
    original_offset_us: int
    optimized_offset_us: int
    original_offset_attribute: str | None = "GenMsgStartDelayTime"
    original_offset_source: str = "explicit"

    def __post_init__(self) -> None:
        if not self.message_name.strip():
            raise ValueError("message_name must not be empty")
        if not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("can_id is outside the CAN identifier range")
        if self.cycle_time_us <= 0:
            raise ValueError("cycle_time_us must be positive")
        if self.original_offset_us < 0 or self.optimized_offset_us < 0:
            raise ValueError("Offsets must be non-negative")
        if self.original_offset_attribute not in (None, "GenMsgStartDelayTime"):
            raise ValueError("original_offset_attribute is unsupported")
        if self.original_offset_source not in {"explicit", "default", "unavailable"}:
            raise ValueError("original_offset_source is unsupported")

    @property
    def change_us(self) -> int:
        return self.optimized_offset_us - self.original_offset_us


@dataclass(frozen=True, slots=True)
class HeatmapMessageDetail:
    """One real message release contributing to a displayed heatmap slot."""

    message_name: str
    can_id: int
    is_extended: bool
    cycle_time_us: int
    offset_us: int

    def __post_init__(self) -> None:
        if not self.message_name.strip():
            raise ValueError("heatmap message name must not be empty")
        maximum = 0x1FFFFFFF if self.is_extended else 0x7FF
        if not 0 <= self.can_id <= maximum:
            raise ValueError("heatmap message CAN ID is invalid")
        if self.cycle_time_us <= 0 or self.offset_us < 0:
            raise ValueError("heatmap message period/Offset is invalid")


@dataclass(frozen=True, slots=True)
class HeatmapSlotDetail:
    """Read-only core-derived membership and aggregate values for one slot."""

    slot_index: int
    start_us: int
    end_us: int
    frame_count: int
    total_load: int
    messages: tuple[HeatmapMessageDetail, ...]

    def __post_init__(self) -> None:
        if self.slot_index < 0 or self.start_us < 0 or self.end_us <= self.start_us:
            raise ValueError("heatmap slot coordinates are invalid")
        if self.frame_count < 0 or self.total_load < 0:
            raise ValueError("heatmap slot count/load must be non-negative")
        if len(self.messages) != self.frame_count:
            raise ValueError("heatmap slot members must match frame_count")

    @property
    def start_ms(self) -> float:
        return self.start_us / 1_000

    @property
    def end_ms(self) -> float:
        return self.end_us / 1_000


@dataclass(frozen=True, slots=True)
class HeatmapWindowDetail:
    """Original and optimized slot details sharing one exact time axis."""

    slot_width_us: int
    original_slots: tuple[HeatmapSlotDetail, ...]
    optimized_slots: tuple[HeatmapSlotDetail, ...]

    def __post_init__(self) -> None:
        if self.slot_width_us <= 0:
            raise ValueError("heatmap slot width must be positive")
        if not self.original_slots or not self.optimized_slots:
            raise ValueError("heatmap window must contain both states")
        if len(self.original_slots) != len(self.optimized_slots):
            raise ValueError("heatmap states must share one time axis")
        for expected, (original, optimized) in enumerate(
            zip(self.original_slots, self.optimized_slots, strict=True)
        ):
            expected_start = expected * self.slot_width_us
            expected_end = expected_start + self.slot_width_us
            if (
                original.slot_index != expected
                or optimized.slot_index != expected
                or original.start_us != expected_start
                or optimized.start_us != expected_start
                or original.end_us != expected_end
                or optimized.end_us != expected_end
            ):
                raise ValueError("heatmap slot axes are not contiguous and shared")

    @property
    def slot_count(self) -> int:
        return len(self.original_slots)


@dataclass(frozen=True, slots=True)
class LoadWindowMetadata:
    """Shared presentation timing for one immutable optimization result."""

    slot_width_us: int
    steady_slot_count: int
    startup_slot_count: int

    def __post_init__(self) -> None:
        values = (self.slot_width_us, self.steady_slot_count, self.startup_slot_count)
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("load window timing values must be positive integers")

    @property
    def slot_width_ms(self) -> float:
        return self.slot_width_us / 1_000

    @property
    def steady_hyperperiod_us(self) -> int:
        return self.steady_slot_count * self.slot_width_us

    @property
    def steady_hyperperiod_ms(self) -> float:
        return self.steady_hyperperiod_us / 1_000

    @property
    def startup_duration_us(self) -> int:
        return self.startup_slot_count * self.slot_width_us

    @property
    def startup_duration_ms(self) -> float:
        return self.startup_duration_us / 1_000


@dataclass(frozen=True, slots=True)
class GuiOptimizationResult:
    """Complete immutable result for one network."""

    network_id: str
    network_name: str
    display_name: str
    source_file: str
    weight_mode: WeightMode
    mode: OptimizationMode
    original_metrics: ObjectiveMetrics
    optimized_metrics: ObjectiveMetrics
    assignments: tuple[OffsetAssignmentRow, ...]
    actual_attempts: int
    stop_reason: str
    elapsed_seconds: float
    warnings: tuple[str, ...]
    steady_loads_before: tuple[int, ...]
    steady_loads_after: tuple[int, ...]
    startup_loads_before: tuple[int, ...]
    startup_loads_after: tuple[int, ...]
    steady_counts_before: tuple[int, ...]
    steady_counts_after: tuple[int, ...]
    startup_counts_before: tuple[int, ...]
    startup_counts_after: tuple[int, ...]
    logs: tuple[str, ...] = ()
    output_directory: Path | None = None
    exported_files: tuple[Path, ...] = field(default_factory=tuple)
    frame_protocol: FrameProtocol = FrameProtocol.CAN_FD
    classic_weight_model: str | None = None
    offset_search: OffsetSearchConfig = field(default_factory=OffsetSearchConfig)
    dbc_write_error: str | None = None
    slot_width_us: int = 5_000
    steady_heatmap: HeatmapWindowDetail | None = None
    startup_heatmap: HeatmapWindowDetail | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.weight_mode, WeightMode):
            raise ValueError("result weight mode is unsupported")
        if not isinstance(self.mode, OptimizationMode):
            raise ValueError("result optimization mode is unsupported")
        if not isinstance(self.frame_protocol, FrameProtocol):
            raise ValueError("result frame protocol is unsupported")
        if not isinstance(self.offset_search, OffsetSearchConfig):
            raise ValueError("result offset_search is invalid")
        if self.dbc_write_error is not None and not self.dbc_write_error.strip():
            raise ValueError("result dbc_write_error must be non-empty when present")
        if (
            isinstance(self.slot_width_us, bool)
            or not isinstance(self.slot_width_us, int)
            or self.slot_width_us <= 0
        ):
            raise ValueError("result slot_width_us must be a positive integer")
        if self.frame_protocol is FrameProtocol.CLASSIC_CAN:
            if self.weight_mode is not WeightMode.PAYLOAD_BYTES:
                raise ValueError("Classic CAN result must use payload_bytes")
            if self.classic_weight_model != CLASSIC_WEIGHT_MODEL:
                raise ValueError("Classic CAN result must declare its approximation model")
        identity = (self.network_id, self.network_name, self.display_name, self.source_file)
        if any(not value.strip() for value in identity) or not self.stop_reason.strip():
            raise ValueError("result network identity, source and stop reason must not be empty")
        if not self.assignments:
            raise ValueError("result must contain assignments")
        if self.actual_attempts <= 0:
            raise ValueError("actual_attempts must be positive")
        if not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("result elapsed_seconds must be non-negative")
        arrays = (
            self.steady_loads_before,
            self.steady_loads_after,
            self.startup_loads_before,
            self.startup_loads_after,
        )
        if any(not array for array in arrays):
            raise ValueError("result load arrays must not be empty")
        if any(value < 0 for array in arrays for value in array):
            raise ValueError("result load arrays must be non-negative")
        if len(self.steady_loads_before) != len(self.steady_loads_after):
            raise ValueError("steady load arrays must have equal lengths")
        if len(self.startup_loads_before) != len(self.startup_loads_after):
            raise ValueError("startup load arrays must have equal lengths")
        count_arrays = (
            self.steady_counts_before,
            self.steady_counts_after,
            self.startup_counts_before,
            self.startup_counts_after,
        )
        if any(not array for array in count_arrays):
            raise ValueError("result congestion count arrays must not be empty")
        if any(value < 0 for array in count_arrays for value in array):
            raise ValueError("result congestion count arrays must be non-negative")
        if any(
            len(counts) != len(loads)
            for counts, loads in (
                (self.steady_counts_before, self.steady_loads_before),
                (self.steady_counts_after, self.steady_loads_after),
                (self.startup_counts_before, self.startup_loads_before),
                (self.startup_counts_after, self.startup_loads_after),
            )
        ):
            raise ValueError("congestion count arrays must align with load arrays")
        self._validate_heatmap_window(
            self.steady_heatmap,
            self.steady_loads_before,
            self.steady_loads_after,
            self.steady_counts_before,
            self.steady_counts_after,
            "steady",
        )
        self._validate_heatmap_window(
            self.startup_heatmap,
            self.startup_loads_before,
            self.startup_loads_after,
            self.startup_counts_before,
            self.startup_counts_after,
            "startup",
        )
        for label, detail in (
            ("steady", self.steady_heatmap),
            ("startup", self.startup_heatmap),
        ):
            if detail is not None and detail.slot_width_us != self.slot_width_us:
                raise ValueError(
                    f"{label} heatmap slot width disagrees with result timing metadata"
                )

    @staticmethod
    def _validate_heatmap_window(
        detail: HeatmapWindowDetail | None,
        before_loads: tuple[int, ...],
        after_loads: tuple[int, ...],
        before_counts: tuple[int, ...],
        after_counts: tuple[int, ...],
        label: str,
    ) -> None:
        if detail is None:
            return
        if detail.slot_count != len(before_loads):
            raise ValueError(f"{label} heatmap details must align with result arrays")
        original = tuple(
            (slot.total_load, slot.frame_count) for slot in detail.original_slots
        )
        optimized = tuple(
            (slot.total_load, slot.frame_count) for slot in detail.optimized_slots
        )
        if original != tuple(zip(before_loads, before_counts, strict=True)):
            raise ValueError(f"{label} original heatmap details disagree with core arrays")
        if optimized != tuple(zip(after_loads, after_counts, strict=True)):
            raise ValueError(f"{label} optimized heatmap details disagree with core arrays")

    @property
    def original_steady_load(self) -> tuple[int, ...]:
        return self.steady_loads_before

    @property
    def optimized_steady_load(self) -> tuple[int, ...]:
        return self.steady_loads_after

    @property
    def load_window_metadata(self) -> LoadWindowMetadata:
        """Return one timing DTO shared by curves, heatmaps and exports."""

        return LoadWindowMetadata(
            self.slot_width_us,
            len(self.steady_loads_before),
            len(self.startup_loads_before),
        )

    @property
    def original_startup_load(self) -> tuple[int, ...]:
        return self.startup_loads_before

    @property
    def optimized_startup_load(self) -> tuple[int, ...]:
        return self.startup_loads_after

    @property
    def original_steady_count(self) -> tuple[int, ...]:
        return self.steady_counts_before

    @property
    def optimized_steady_count(self) -> tuple[int, ...]:
        return self.steady_counts_after

    @property
    def original_startup_count(self) -> tuple[int, ...]:
        return self.startup_counts_before

    @property
    def optimized_startup_count(self) -> tuple[int, ...]:
        return self.startup_counts_after


@dataclass(frozen=True, slots=True)
class NetworkBatchResult:
    """Status and optional detailed result for one network."""

    network_id: str
    network_name: str
    display_name: str
    source_file: str
    status: NetworkRunStatus
    weight_mode: WeightMode
    mode: OptimizationMode
    result: GuiOptimizationResult | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()
    base_eligible_message_count: int = 0
    routing_excluded_count: int = 0
    final_eligible_message_count: int = 0

    def __post_init__(self) -> None:
        identity = (self.network_id, self.network_name, self.display_name, self.source_file)
        if any(not value.strip() for value in identity):
            raise ValueError("batch network identity and source must not be empty")
        if self.status is NetworkRunStatus.SUCCEEDED and self.result is None:
            raise ValueError("successful network requires a detailed result")
        if self.status is not NetworkRunStatus.SUCCEEDED and self.result is not None:
            raise ValueError("non-successful network must not contain a result")
        if self.status is NetworkRunStatus.FAILED and not self.error:
            raise ValueError("failed network requires an error")
        if self.result is not None and (
            self.result.network_id != self.network_id
            or self.result.network_name != self.network_name
            or self.result.source_file != self.source_file
        ):
            raise ValueError("batch row and detailed result network identity must match")
        if (
            self.result is not None
            and self.base_eligible_message_count == 0
            and self.routing_excluded_count == 0
            and self.final_eligible_message_count == 0
        ):
            inferred = len(self.result.assignments)
            object.__setattr__(self, "base_eligible_message_count", inferred)
            object.__setattr__(self, "final_eligible_message_count", inferred)
        counts = (
            self.base_eligible_message_count,
            self.routing_excluded_count,
            self.final_eligible_message_count,
        )
        if min(counts) < 0:
            raise ValueError("batch routing eligibility counts must be non-negative")
        if self.base_eligible_message_count - self.routing_excluded_count != (
            self.final_eligible_message_count
        ):
            raise ValueError("batch routing eligibility counts are inconsistent")

    @property
    def zss_improvement(self) -> int | None:
        if self.result is None:
            return None
        return self.result.original_metrics.zss - self.result.optimized_metrics.zss


@dataclass(frozen=True, slots=True)
class BatchOptimizationResult:
    """Project-level batch result retaining every completed network."""

    project_name: str
    import_session_directory: Path
    import_manifest_path: Path
    output_directory: Path
    network_results: tuple[NetworkBatchResult, ...]
    elapsed_seconds: float
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    cancelled: bool = False
    network_items_by_id: Mapping[str, NetworkBatchResult] = field(init=False, repr=False)
    results_by_network_id: Mapping[str, GuiOptimizationResult] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.project_name or not self.network_results:
            raise ValueError("batch result project and networks must not be empty")
        item_map = {item.network_id: item for item in self.network_results}
        if len(item_map) != len(self.network_results):
            raise ValueError("batch result network IDs must be unique")
        result_map = {
            item.network_id: item.result
            for item in self.network_results
            if item.result is not None
        }
        object.__setattr__(self, "network_items_by_id", MappingProxyType(item_map))
        object.__setattr__(self, "results_by_network_id", MappingProxyType(result_map))
        if not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("batch elapsed_seconds must be non-negative")

    @property
    def succeeded_count(self) -> int:
        return sum(item.status is NetworkRunStatus.SUCCEEDED for item in self.network_results)

    @property
    def failed_count(self) -> int:
        return sum(item.status is NetworkRunStatus.FAILED for item in self.network_results)

    @property
    def skipped_count(self) -> int:
        return sum(item.status is NetworkRunStatus.SKIPPED for item in self.network_results)

    @property
    def cancelled_count(self) -> int:
        return sum(item.status is NetworkRunStatus.CANCELLED for item in self.network_results)

    @property
    def dbc_write_failed_count(self) -> int:
        return sum(
            item.result is not None and item.result.dbc_write_error is not None
            for item in self.network_results
        )

    @property
    def status(self) -> BatchRunStatus:
        if self.cancelled:
            return BatchRunStatus.CANCELLED
        if self.succeeded_count == len(self.network_results):
            return BatchRunStatus.SUCCEEDED
        if self.succeeded_count:
            return BatchRunStatus.PARTIAL
        return BatchRunStatus.FAILED

    def result_for_network_id(self, network_id: str) -> GuiOptimizationResult:
        return self.results_by_network_id[network_id]

    def network_item_for_id(self, network_id: str) -> NetworkBatchResult:
        return self.network_items_by_id[network_id]


class OptimizationCancelled(RuntimeError):
    """Raised after observing cooperative cancellation."""


class BatchOptimizationCancelled(OptimizationCancelled):
    """Cancellation carrying completed-network results."""

    def __init__(self, partial_result: BatchOptimizationResult) -> None:
        super().__init__("用户已请求停止批量优化")
        self.partial_result = partial_result


class BackendError(RuntimeError):
    """Expected backend failure safe to summarize for a GUI user."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OptimizationCancelled("用户已请求停止")


ProgressCallback = Callable[[ProgressUpdate], None]


@runtime_checkable
class OptimizationBackend(Protocol):
    """Only interface the GUI may use for a workspace batch."""

    @property
    def availability(self) -> BackendAvailability:
        """Describe whether real optimization is available."""

    def import_inputs(
        self,
        sources: tuple[Path, ...],
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> ImportSession:
        """Copy and classify sources into a new user_input session."""

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        """Inspect only workspace copies and discover every network."""

    def apply_sender_selection(
        self,
        inspection: WorkspaceInspection,
        selection: SenderNodeSelectionConfig,
    ) -> WorkspaceInspection:
        """Confirm local transmitter selections and derive final eligibility."""

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        """Optimize every discovered network sequentially."""
