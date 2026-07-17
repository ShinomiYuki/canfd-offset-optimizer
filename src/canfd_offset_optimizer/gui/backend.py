"""Public GUI backend boundary; no optimizer implementation is imported here."""

from .contracts import (
    BackendAvailability,
    BackendError,
    BatchOptimizationCancelled,
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    GuiOptimizationResult,
    ImportSession,
    NetworkBatchResult,
    NetworkSummary,
    OptimizationBackend,
    OptimizationCancelled,
    ProgressCallback,
    ProgressUpdate,
    WorkspaceInspection,
)

__all__ = [
    "BackendAvailability",
    "BackendError",
    "BatchOptimizationCancelled",
    "BatchOptimizationResult",
    "CancellationToken",
    "GuiBatchOptimizationRequest",
    "GuiOptimizationResult",
    "ImportSession",
    "NetworkBatchResult",
    "NetworkSummary",
    "OptimizationBackend",
    "OptimizationCancelled",
    "ProgressCallback",
    "ProgressUpdate",
    "WorkspaceInspection",
]
