"""Fail-closed backend used when the production adapter cannot initialize."""

from __future__ import annotations

from pathlib import Path

from .contracts import (
    BackendAvailability,
    BackendError,
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    ImportSession,
    ProgressCallback,
    WorkspaceInspection,
)
from .workspace_io import WorkspaceImporter


class UnavailableBackend(WorkspaceImporter):
    """Keep import/preview available but prohibit optimization."""

    def __init__(self, message: str, workspace_root: Path | None = None) -> None:
        super().__init__(workspace_root)
        self._message = message

    @property
    def availability(self) -> BackendAvailability:
        return BackendAvailability(False, "RealBackend", self._message)

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        del progress_callback, cancellation_token
        return WorkspaceInspection(session, (), errors=(self._message,))

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        del request, progress_callback, cancellation_token
        raise BackendError(self._message)
