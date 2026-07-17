"""Backend boundary exports; no optimizer implementation is imported here."""

from .contracts import (
    BackendError,
    CancellationToken,
    GuiOptimizationRequest,
    GuiOptimizationResult,
    InputInspectionRequest,
    InputSummary,
    OptimizationBackend,
    OptimizationCancelled,
    ProgressCallback,
    ProgressUpdate,
    WeightMode,
)

__all__ = [
    "BackendError",
    "CancellationToken",
    "GuiOptimizationRequest",
    "GuiOptimizationResult",
    "InputInspectionRequest",
    "InputSummary",
    "OptimizationBackend",
    "OptimizationCancelled",
    "ProgressCallback",
    "ProgressUpdate",
    "WeightMode",
]
