"""Stable DTO and backend protocol boundary consumed by the GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from pathlib import Path
from threading import Event
from typing import Callable, Protocol, runtime_checkable


class OptimizationMode(str, Enum):
    """User-facing optimization modes supported by the core project."""

    PEAK = "peak"
    BALANCED = "balanced"
    VARIANCE = "variance"


class RestartMode(str, Enum):
    """User-facing restart policy selection."""

    ADAPTIVE = "adaptive"
    FIXED = "fixed"


class ProgressPhase(str, Enum):
    """Coarse phases that are stable enough for presentation."""

    INSPECTING = "inspecting"
    PREPARING = "preparing"
    PEAK_SEARCH = "peak_search"
    BALANCED_SEARCH = "balanced_search"
    FINALIZING = "finalizing"


@dataclass(frozen=True, slots=True)
class InputInspectionRequest:
    """Paths required to inspect one GUI project selection."""

    dbc_path: Path
    config_path: Path
    arxml_directory: Path | None = None

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.dbc_path.is_file():
            errors.append(f"DBC 文件不存在：{self.dbc_path}")
        if not self.config_path.is_file():
            errors.append(f"项目配置不存在：{self.config_path}")
        if self.arxml_directory is not None and not self.arxml_directory.is_dir():
            errors.append(f"ARXML 目录不存在：{self.arxml_directory}")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class NetworkSummary:
    """One selectable network returned by backend inspection."""

    name: str
    message_count: int
    weight_mode: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("network name must not be empty")
        if self.message_count <= 0:
            raise ValueError("network message_count must be positive")
        if not self.weight_mode.strip():
            raise ValueError("network weight_mode must not be empty")


@dataclass(frozen=True, slots=True)
class InputSummary:
    """Backend inspection result with stable selectable network order."""

    networks: tuple[NetworkSummary, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.networks)
        if not names:
            raise ValueError("inspection must return at least one network")
        if len(set(names)) != len(names):
            raise ValueError("inspection network names must be unique")


@dataclass(frozen=True, slots=True)
class RestartSettings:
    """Restart settings mirrored from the existing public configuration semantics."""

    mode: RestartMode = RestartMode.ADAPTIVE
    fixed_attempts: int = 21
    min_attempts: int = 20
    max_attempts: int = 80

    def __post_init__(self) -> None:
        values = (self.fixed_attempts, self.min_attempts, self.max_attempts)
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("restart attempts must be positive integers")
        if self.min_attempts > self.max_attempts:
            raise ValueError("adaptive min_attempts must not exceed max_attempts")


@dataclass(frozen=True, slots=True)
class GuiOptimizationRequest:
    """Complete immutable request sent through the GUI backend protocol."""

    inspection: InputInspectionRequest
    network_name: str
    mode: OptimizationMode
    balanced_tolerance: float
    restart: RestartSettings
    candidate_pool_size: int
    enable_triple_search: bool
    output_directory: Path

    def __post_init__(self) -> None:
        if not self.network_name.strip():
            raise ValueError("network_name must not be empty")
        if not isfinite(self.balanced_tolerance) or not 0 <= self.balanced_tolerance <= 1:
            raise ValueError("balanced_tolerance must be finite and in [0, 1]")
        if self.candidate_pool_size not in {1, 4, 8, 16, 32}:
            raise ValueError("candidate_pool_size is unsupported")
        if not isinstance(self.enable_triple_search, bool):
            raise ValueError("enable_triple_search must be boolean")

    def validation_errors(self) -> tuple[str, ...]:
        errors = list(self.inspection.validation_errors())
        if not self.output_directory:
            errors.append("请选择用户输出目录")
        elif self.output_directory.exists() and not self.output_directory.is_dir():
            errors.append(f"输出路径不是目录：{self.output_directory}")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """One thread-safe progress notification."""

    phase: ProgressPhase
    message: str
    attempt: int | None = None
    total_attempts: int | None = None
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("progress message must not be empty")
        if not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("progress elapsed_seconds must be non-negative")
        if (self.attempt is None) != (self.total_attempts is None):
            raise ValueError("attempt and total_attempts must appear together")
        if self.attempt is not None and (
            self.attempt < 0
            or self.total_attempts is None
            or self.total_attempts <= 0
            or self.attempt > self.total_attempts
        ):
            raise ValueError("progress attempt range is invalid")


@dataclass(frozen=True, slots=True)
class ObjectiveMetrics:
    """Complete metrics already calculated by a backend."""

    zss: int
    qss: int
    standard_deviation: float
    zst: int
    qst: int
    nvio: int
    vvio: int

    def __post_init__(self) -> None:
        integer_values = (self.zss, self.qss, self.zst, self.qst, self.nvio, self.vvio)
        if any(value < 0 for value in integer_values):
            raise ValueError("objective metrics must be non-negative")
        if not isfinite(self.standard_deviation) or self.standard_deviation < 0:
            raise ValueError("standard_deviation must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class OffsetAssignmentRow:
    """One immutable row for the GUI Offset comparison table."""

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
    """Stable view-ready result; GUI code must treat it as immutable."""

    network_name: str
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
    exported_files: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.network_name.strip() or not self.stop_reason.strip():
            raise ValueError("result network and stop reason must not be empty")
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


class OptimizationCancelled(RuntimeError):
    """Raised by a backend after observing cooperative cancellation."""


class BackendError(RuntimeError):
    """Expected backend failure safe to summarize for a GUI user."""


class CancellationToken:
    """Thread-safe cooperative cancellation shared with a worker."""

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
    """Only interface the GUI may use to inspect and optimize projects."""

    def inspect_input(
        self,
        request: InputInspectionRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> InputSummary:
        """Validate input and return selectable networks."""

    def optimize(
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> GuiOptimizationResult:
        """Run one synchronous optimization without touching GUI objects."""
