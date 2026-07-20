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
    warnings: tuple[str, ...] = ()
    unoptimizable_reason: str | None = None

    def __post_init__(self) -> None:
        identity = (self.network_id, self.network_name, self.display_name, self.source_file)
        if any(not value.strip() for value in identity):
            raise ValueError("network identity and source fields must not be empty")
        if self.source_workspace_path.is_absolute():
            raise ValueError("network source_workspace_path must be relative")
        if self.message_count < 0:
            raise ValueError("network message_count must be non-negative")
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

    def __post_init__(self) -> None:
        network_ids = tuple(network.network_id for network in self.networks)
        if len(set(network_ids)) != len(network_ids):
            raise ValueError("inspection network IDs must be unique")
        if len(set(self.missing_required)) != len(self.missing_required):
            raise ValueError("missing input kinds must be unique")

    @property
    def can_optimize(self) -> bool:
        return bool(self.optimizable_networks) and not self.missing_required and not self.errors

    @property
    def optimizable_networks(self) -> tuple[NetworkSummary, ...]:
        return tuple(network for network in self.networks if network.is_optimizable)


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
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("restart attempts must be positive integers")
        if self.min_attempts > self.max_attempts:
            raise ValueError("adaptive min_attempts must not exceed max_attempts")


@dataclass(frozen=True, slots=True)
class GuiBatchOptimizationRequest:
    """One immutable request applied to every discovered network."""

    inspection: WorkspaceInspection
    weight_mode: WeightMode
    mode: OptimizationMode
    balanced_tolerance: float
    restart: RestartSettings
    candidate_pool_size: int
    enable_triple_search: bool
    output_root: Path
    offset_search: OffsetSearchConfig = field(default_factory=OffsetSearchConfig)

    def __post_init__(self) -> None:
        if not self.inspection.can_optimize:
            raise ValueError("workspace inspection is not ready for optimization")
        if not isinstance(self.weight_mode, WeightMode):
            raise ValueError("weight mode is unsupported")
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
        if any(
            self.weight_mode not in network.available_weight_modes
            for network in self.inspection.optimizable_networks
            if network.frame_protocol is FrameProtocol.CAN_FD
        ):
            raise ValueError("selected weight mode is not available for every CAN FD network")
        uses_payload = (
            self.weight_mode is WeightMode.PAYLOAD_BYTES
            or any(
                network.frame_protocol is FrameProtocol.CLASSIC_CAN
                for network in self.inspection.optimizable_networks
            )
        )
        if uses_payload and self.mode is not OptimizationMode.PEAK:
            raise ValueError("payload_bytes weight only supports peak mode")
        if self.output_root.exists() and not self.output_root.is_dir():
            raise ValueError("output_root must be a directory")


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

    def __post_init__(self) -> None:
        if not self.message_name.strip():
            raise ValueError("message_name must not be empty")
        if not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("can_id is outside the CAN identifier range")
        if self.cycle_time_us <= 0:
            raise ValueError("cycle_time_us must be positive")
        if self.original_offset_us < 0 or self.optimized_offset_us < 0:
            raise ValueError("Offsets must be non-negative")

    @property
    def change_us(self) -> int:
        return self.optimized_offset_us - self.original_offset_us


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

    def __post_init__(self) -> None:
        if not isinstance(self.weight_mode, WeightMode):
            raise ValueError("result weight mode is unsupported")
        if not isinstance(self.mode, OptimizationMode):
            raise ValueError("result optimization mode is unsupported")
        if not isinstance(self.frame_protocol, FrameProtocol):
            raise ValueError("result frame protocol is unsupported")
        if not isinstance(self.offset_search, OffsetSearchConfig):
            raise ValueError("result offset_search is invalid")
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

    @property
    def original_steady_load(self) -> tuple[int, ...]:
        return self.steady_loads_before

    @property
    def optimized_steady_load(self) -> tuple[int, ...]:
        return self.steady_loads_after

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

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        """Optimize every discovered network sequentially."""
