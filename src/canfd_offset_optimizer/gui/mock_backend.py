"""Fail-closed mock boundary; it never fabricates business results."""

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
    SenderNodeSelectionConfig,
    WorkspaceInspection,
)
from .workspace_io import WorkspaceImporter


class MockBackend(WorkspaceImporter):
    """Retain import/preview identity while prohibiting simulated optimization."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        super().__init__(workspace_root)

    @property
    def availability(self) -> BackendAvailability:
        return BackendAvailability(
            False,
            "MockBackend",
            "当前为界面模拟模式，不能执行真实优化。",
        )

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        del session, progress_callback, cancellation_token
        raise BackendError("MockBackend 不提供业务解析；请使用 RealBackend。")

    def apply_sender_selection(
        self,
        inspection: WorkspaceInspection,
        selection: SenderNodeSelectionConfig,
    ) -> WorkspaceInspection:
        del inspection, selection
        raise BackendError("当前后端不提供 DBC 发送节点筛选。")

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        del request, progress_callback, cancellation_token
        raise BackendError("MockBackend 不生成业务结果，也不会写入 user_output。")
