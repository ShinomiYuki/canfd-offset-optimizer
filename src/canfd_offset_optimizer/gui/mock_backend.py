"""Deterministic backend used to complete the GUI before a public core service exists."""

from __future__ import annotations

from math import sin
from time import perf_counter, sleep

from .contracts import (
    BackendError,
    CancellationToken,
    GuiOptimizationRequest,
    GuiOptimizationResult,
    InputInspectionRequest,
    InputSummary,
    NetworkSummary,
    ObjectiveMetrics,
    OffsetAssignmentRow,
    OptimizationMode,
    ProgressCallback,
    ProgressPhase,
    ProgressUpdate,
    RestartMode,
)


class MockBackend:
    """Simulate validation, progress, warnings, success, failure and cancellation."""

    def __init__(
        self,
        *,
        delay_seconds: float = 0.01,
        fail_inspection: bool = False,
        fail_optimization: bool = False,
        extra_warning: str | None = None,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        self._delay_seconds = delay_seconds
        self._fail_inspection = fail_inspection
        self._fail_optimization = fail_optimization
        self._extra_warning = extra_warning

    def inspect_input(
        self,
        request: InputInspectionRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> InputSummary:
        started = perf_counter()
        errors = request.validation_errors()
        if errors:
            raise BackendError("\n".join(errors))
        for step, message in enumerate(
            ("检查输入路径", "读取项目元数据", "整理可用网段"), start=1
        ):
            self._tick(cancellation_token)
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.INSPECTING,
                    message,
                    step,
                    3,
                    perf_counter() - started,
                )
            )
        if self._fail_inspection:
            raise BackendError("MockBackend 模拟输入检查失败")
        warnings = ["当前使用 MockBackend，网段和结果仅用于 GUI 联调。"]
        if self._extra_warning:
            warnings.append(self._extra_warning)
        return InputSummary(
            networks=(
                NetworkSummary("PT_CAN", 42, "frame_time_us", "动力 CAN FD 网段"),
                NetworkSummary("BODY_CAN", 31, "frame_time_us", "车身 CAN FD 网段"),
                NetworkSummary("ADAS_CAN", 56, "frame_time_us", "辅助驾驶 CAN FD 网段"),
            ),
            warnings=tuple(warnings),
        )

    def optimize(
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> GuiOptimizationResult:
        errors = request.validation_errors()
        if errors:
            raise BackendError("\n".join(errors))
        if self._fail_optimization:
            raise BackendError("MockBackend 模拟优化失败")
        started = perf_counter()
        progress_callback(
            ProgressUpdate(ProgressPhase.PREPARING, "准备不可变请求快照")
        )
        self._tick(cancellation_token)
        attempts = (
            request.restart.fixed_attempts
            if request.restart.mode is RestartMode.FIXED
            else request.restart.min_attempts
        )
        for attempt in range(1, attempts + 1):
            self._tick(cancellation_token)
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.PEAK_SEARCH,
                    f"Peak 搜索 attempt {attempt}/{attempts}",
                    attempt,
                    attempts,
                    perf_counter() - started,
                )
            )
        if request.mode is OptimizationMode.BALANCED:
            pool_size = request.candidate_pool_size
            for index in range(1, pool_size + 1):
                self._tick(cancellation_token)
                progress_callback(
                    ProgressUpdate(
                        ProgressPhase.BALANCED_SEARCH,
                        f"Balanced 候选 {index}/{pool_size}",
                        index,
                        pool_size,
                        perf_counter() - started,
                    )
                )
        progress_callback(
            ProgressUpdate(
                ProgressPhase.FINALIZING,
                "生成只读 GUI 结果",
                elapsed_seconds=perf_counter() - started,
            )
        )
        self._tick(cancellation_token)
        assignments = self._assignments(request.network_name)
        warnings = ["MockBackend 结果不可用于工程交付。"]
        if request.enable_triple_search:
            warnings.append("已模拟启用高质量离线 3-opt；未执行真实核心搜索。")
        if self._extra_warning:
            warnings.append(self._extra_warning)
        before, after = self._metrics(request.mode)
        steady_before = tuple(430 + int(115 * (1 + sin(index * 0.72))) for index in range(30))
        steady_after = tuple(455 + int(48 * (1 + sin(index * 0.72 + 0.35))) for index in range(30))
        startup_before = tuple(390 + int(100 * (1 + sin(index * 0.91))) for index in range(18))
        startup_after = tuple(410 + int(44 * (1 + sin(index * 0.91 + 0.4))) for index in range(18))
        return GuiOptimizationResult(
            network_name=request.network_name,
            mode=request.mode,
            original_metrics=before,
            optimized_metrics=after,
            assignments=assignments,
            actual_attempts=attempts,
            stop_reason=(
                "fixed_limit"
                if request.restart.mode is RestartMode.FIXED
                else "patience_exhausted"
            ),
            elapsed_seconds=perf_counter() - started,
            warnings=tuple(warnings),
            steady_loads_before=steady_before,
            steady_loads_after=steady_after,
            startup_loads_before=startup_before,
            startup_loads_after=startup_after,
        )

    def _tick(self, cancellation_token: CancellationToken) -> None:
        cancellation_token.raise_if_cancelled()
        if self._delay_seconds:
            sleep(self._delay_seconds)
        cancellation_token.raise_if_cancelled()

    @staticmethod
    def _metrics(mode: OptimizationMode) -> tuple[ObjectiveMetrics, ObjectiveMetrics]:
        before = ObjectiveMetrics(648, 10_842_500, 81.4, 611, 8_904_200, 3, 146)
        if mode is OptimizationMode.PEAK:
            after = ObjectiveMetrics(572, 9_335_100, 57.2, 559, 7_993_400, 0, 0)
        elif mode is OptimizationMode.VARIANCE:
            after = ObjectiveMetrics(601, 8_804_600, 43.8, 575, 7_704_200, 0, 0)
        else:
            after = ObjectiveMetrics(584, 8_621_900, 41.7, 566, 7_611_800, 0, 0)
        return before, after

    @staticmethod
    def _assignments(network_name: str) -> tuple[OffsetAssignmentRow, ...]:
        prefix = network_name.split("_", 1)[0]
        cycles = (10_000, 20_000, 50_000, 100_000)
        rows: list[OffsetAssignmentRow] = []
        for index in range(12):
            original = 15_000 + (index % 6) * 5_000
            optimized = original if index % 4 == 0 else 15_000 + ((index * 3) % 12) * 5_000
            rows.append(
                OffsetAssignmentRow(
                    f"{prefix}_Message_{index + 1:02d}",
                    0x180 + index,
                    cycles[index % len(cycles)],
                    original,
                    optimized,
                )
            )
        return tuple(rows)
