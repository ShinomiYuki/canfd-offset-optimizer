"""Production GUI adapter for the parser, project loader and GCLS core."""

from __future__ import annotations

import hashlib
import importlib
import re
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ..config import PeakToleranceConfig, RestartPolicy, load_project_config
from ..exceptions import CanfdOptimizerError
from ..models import (
    ObjectiveMode as CoreObjectiveMode,
    ObjectiveValue,
    PeakToleranceType,
    RestartMode as CoreRestartMode,
    WeightMode as CoreWeightMode,
)
from ..optimization.gcls import run_gcls
from ..parsers.arxml_parser import discover_arxml_channel_names
from ..parsers.dbc_parser import parse_dbc
from ..parsers.project_loader import LoadedProject, load_project
from ..reporting.objective_mode_writer import load_statistics
from ..timeline.state import SearchState
from .contracts import (
    BackendAvailability,
    BackendError,
    BatchOptimizationCancelled,
    BatchOptimizationResult,
    CancellationToken,
    GuiBatchOptimizationRequest,
    GuiOptimizationResult,
    ImportRecord,
    ImportRecordStatus,
    ImportSession,
    InputKind,
    NetworkBatchResult,
    NetworkRunStatus,
    NetworkSummary,
    ObjectiveMetrics,
    OffsetAssignmentRow,
    OptimizationCancelled,
    ProgressCallback,
    ProgressPhase,
    ProgressUpdate,
    RestartMode,
    WeightMode,
    WorkspaceInspection,
)
from .artifact_outputs import (
    create_output_layout,
    write_batch_log,
    write_load_curve_png,
    write_load_heatmap_png,
    write_network_log,
)
from .dbc_offset_writer import DbcOffsetReplacement, write_dbc_with_offsets
from .formatting import (
    export_assignments_csv,
    export_batch_summary_csv,
)
from .workspace_io import DEFAULT_CONFIG_NOTE, WorkspaceImporter


REQUIRED_ALLOWED_OFFSETS_US = tuple(range(15_000, 100_001, 5_000))


class RealBackend(WorkspaceImporter):
    """Use only core-owned parsing, eligibility, optimization and load data."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        super().__init__(workspace_root)
        # cantools is intentionally imported lazily by the core parser.  Probe it
        # here so app composition can fail closed before enabling the Run button.
        importlib.import_module("cantools")
        if not all(callable(item) for item in (parse_dbc, load_project, run_gcls)):
            raise RuntimeError("核心 parser/project loader/GCLS 接口不可调用")

    @property
    def availability(self) -> BackendAvailability:
        return BackendAvailability(True, "RealBackend")

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        started = perf_counter()
        if not session.session_directory.is_dir() or not session.manifest_path.is_file():
            raise BackendError("导入工作区或 import_manifest.json 不存在。")
        unique_records = self._unique_usable_records(session)
        dbc_records = tuple(record for record in unique_records if record.kind is InputKind.DBC)
        config_records = tuple(
            record for record in unique_records if record.kind is InputKind.CONFIG
        )
        arxml_records = tuple(
            record for record in unique_records if record.kind is InputKind.ARXML
        )
        missing = tuple(
            kind
            for kind, records in ((InputKind.DBC, dbc_records), (InputKind.CONFIG, config_records))
            if not records
        )
        errors: list[str] = []
        if len(config_records) > 1:
            errors.append("发现多个项目配置，无法确定批量运行使用哪个配置。")
        arxml_channels: tuple[str, ...] = ()
        configured_channel: str | None = None
        if arxml_records and len(config_records) == 1:
            try:
                arxml_channels, configured_channel = self._arxml_channel_context(session)
            except CanfdOptimizerError as exc:
                errors.append(f"ARXML 通道检查失败：{type(exc).__name__}: {exc}")
        display_counts: dict[str, int] = {}
        networks: list[NetworkSummary] = []
        total = max(1, len(dbc_records))
        for index, record in enumerate(
            sorted(dbc_records, key=lambda item: str(item.workspace_relative_path).casefold()),
            start=1,
        ):
            cancellation_token.raise_if_cancelled()
            assert record.workspace_relative_path is not None
            path = session.session_directory / record.workspace_relative_path
            network_name = self._network_name_from_stem(path.stem)
            key = network_name.casefold()
            display_counts[key] = display_counts.get(key, 0) + 1
            ordinal = display_counts[key]
            display_name = network_name if ordinal == 1 else f"{network_name} ({ordinal})"
            identity_material = f"{record.workspace_relative_path.as_posix()}|{record.sha256 or ''}"
            network_id = f"net-{hashlib.sha256(identity_material.encode()).hexdigest()[:16]}"
            try:
                parsed = parse_dbc(path)
                message_count = len(parsed.messages)
                optimizable = True
                reason = None
                network_warnings = list(parsed.warnings)
            except CanfdOptimizerError as exc:
                message_count = 0
                optimizable = False
                reason = self._eligibility_reason(exc)
                network_warnings = []
            available_weight_modes: tuple[WeightMode, ...] = ()
            if optimizable:
                modes = [WeightMode.PAYLOAD_BYTES]
                frame_time_channel = self._resolve_frame_time_channel(
                    path.name, configured_channel, arxml_channels
                )
                if frame_time_channel is not None:
                    modes.append(WeightMode.FRAME_TIME_US)
                    network_warnings.append(
                        f"frame_time_us ARXML Controller：{frame_time_channel}"
                    )
                elif arxml_records:
                    network_warnings.append(
                        "未找到与来源 DBC 唯一对应的 ARXML Controller；"
                        "该网段仅支持 payload_bytes。"
                    )
                available_weight_modes = tuple(modes)
            networks.append(
                NetworkSummary(
                    network_id=network_id,
                    network_name=network_name,
                    display_name=display_name,
                    source_file=path.name,
                    source_workspace_path=record.workspace_relative_path,
                    is_optimizable=optimizable,
                    message_count=message_count,
                    available_weight_modes=available_weight_modes,
                    warnings=tuple(network_warnings),
                    unoptimizable_reason=reason,
                )
            )
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.INSPECTING,
                    f"核心解析资格：{display_name}",
                    elapsed_seconds=perf_counter() - started,
                    overall_completed=index,
                    overall_total=total,
                )
            )
        used_paths = {
            record.workspace_relative_path
            for record in unique_records
            if record.kind in {InputKind.DBC, InputKind.CONFIG, InputKind.ARXML}
        }
        updated_session = replace(
            session,
            records=tuple(
                replace(record, used_by_parser=record.workspace_relative_path in used_paths)
                for record in session.records
            ),
        )
        self._write_manifest(updated_session)
        warnings = self._inspection_warnings(updated_session)
        return WorkspaceInspection(
            updated_session, tuple(networks), missing, warnings, tuple(errors)
        )

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        started = perf_counter()
        session = request.inspection.session
        output_directory = self._unique_directory(
            request.output_root.resolve(),
            f"{self._session_id(session.project_name)}_real",
        )
        output_directory.mkdir(parents=True, exist_ok=False)
        create_output_layout(output_directory)
        results: list[NetworkBatchResult] = []
        networks = request.inspection.networks
        arxml_channels, configured_channel = self._arxml_channel_context(session)
        channel_overrides = {
            network.network_id: self._resolve_frame_time_channel(
                network.source_file, configured_channel, arxml_channels
            )
            for network in request.inspection.optimizable_networks
        }
        total = len(networks)
        for index, network in enumerate(networks, start=1):
            if cancellation_token.is_cancelled:
                results.extend(
                    self._cancelled_rows(networks[index - 1 :], request)
                )
                partial = self._finish_batch(
                    request, output_directory, tuple(results), started, cancelled=True
                )
                raise BatchOptimizationCancelled(partial)
            if not network.is_optimizable:
                results.append(
                    NetworkBatchResult(
                        network.network_id, network.network_name, network.display_name,
                        network.source_file, NetworkRunStatus.SKIPPED,
                        request.weight_mode, request.mode,
                        error=network.unoptimizable_reason,
                        warnings=network.warnings,
                        logs=(f"核心资格判定跳过：{network.unoptimizable_reason}",),
                    )
                )
                self._emit_finished(progress_callback, network, index, total, started,
                                    NetworkRunStatus.SKIPPED)
                continue
            try:
                detail = self._optimize_network(
                    request, network, index, total, output_directory,
                    progress_callback, cancellation_token,
                    channel_overrides[network.network_id],
                )
                results.append(
                    NetworkBatchResult(
                        network.network_id, network.network_name, network.display_name,
                        network.source_file, NetworkRunStatus.SUCCEEDED,
                        request.weight_mode, request.mode, result=detail,
                        warnings=detail.warnings, logs=detail.logs,
                    )
                )
                status = NetworkRunStatus.SUCCEEDED
            except OptimizationCancelled:
                results.append(
                    NetworkBatchResult(
                        network.network_id, network.network_name, network.display_name,
                        network.source_file, NetworkRunStatus.CANCELLED,
                        request.weight_mode, request.mode,
                        logs=("用户取消；核心未产生成功结果。",),
                    )
                )
                results.extend(self._cancelled_rows(networks[index:], request))
                partial = self._finish_batch(
                    request, output_directory, tuple(results), started, cancelled=True
                )
                raise BatchOptimizationCancelled(partial)
            except (CanfdOptimizerError, ValueError, OSError, RuntimeError) as exc:
                message = f"{type(exc).__name__}: {exc}"
                results.append(
                    NetworkBatchResult(
                        network.network_id, network.network_name, network.display_name,
                        network.source_file, NetworkRunStatus.FAILED,
                        request.weight_mode, request.mode, error=message,
                        logs=(f"真实后端失败：{message}",),
                    )
                )
                status = NetworkRunStatus.FAILED
            self._emit_finished(progress_callback, network, index, total, started, status)
        return self._finish_batch(request, output_directory, tuple(results), started)

    def _optimize_network(
        self,
        request: GuiBatchOptimizationRequest,
        network: NetworkSummary,
        index: int,
        total: int,
        batch_output: Path,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
        channel_override: str | None,
    ) -> GuiOptimizationResult:
        started = perf_counter()
        session = request.inspection.session
        config_path = self._single_workspace_path(session, InputKind.CONFIG)
        dbc_path = session.session_directory / network.source_workspace_path
        arxml_records = self._records_of_kind(session, InputKind.ARXML)
        arxml_root = session.session_directory / "arxml" if arxml_records else session.session_directory
        core_weight = CoreWeightMode(request.weight_mode.value)
        core_mode = CoreObjectiveMode(request.mode.value)
        if request.weight_mode is WeightMode.FRAME_TIME_US and channel_override is None:
            raise BackendError(
                f"网段 {network.display_name} 没有唯一的 ARXML Controller 映射"
            )
        loaded = load_project(
            dbc_path, arxml_root, config_path,
            weight_mode_override=core_weight,
            channel_override=channel_override,
            objective_mode_override=core_mode,
        )
        if loaded.config.optimization.allowed_offsets_us != REQUIRED_ALLOWED_OFFSETS_US:
            actual = loaded.config.optimization.allowed_offsets_us
            raise ValueError(
                "非法候选 Offset：要求精确等于 15,20,...,100 ms；"
                f"核心配置实际为 {tuple(value / 1000 for value in actual)} ms"
            )
        for message in loaded.network.messages:
            self._validate_offset_contract(
                message.name,
                message.original_offset_us,
                "core NetworkModel.original_offset_us",
            )
        loaded = self._apply_request_settings(loaded, request)
        initial_state = self._baseline_state(loaded)
        attempt_limit = loaded.config.optimization.restart_policy.attempt_limit

        def observe(record: object) -> None:
            cancellation_token.raise_if_cancelled()
            attempt = int(getattr(record, "attempt_index")) + 1
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.NETWORK_RUNNING,
                    f"{network.display_name}：核心 GCLS attempt {attempt}",
                    elapsed_seconds=perf_counter() - started,
                    network_id=network.network_id,
                    network_name=network.network_name,
                    network_index=index,
                    network_total=total,
                    attempt=attempt,
                    total_attempts=attempt_limit,
                    overall_completed=index - 1,
                    overall_total=total,
                )
            )

        core_result = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            loaded.config.optimization,
            average_load_limit=loaded.config.model.average_load_limit,
            seed=0,
            weight_mode=loaded.network.weight_mode,
            objective_config=loaded.config.objective,
            restart_observer=observe,
        )
        cancellation_token.raise_if_cancelled()
        assignments_by_name = {item.message_name: item for item in core_result.assignments}
        rows = tuple(
            OffsetAssignmentRow(
                message.name,
                message.can_id,
                message.cycle_time_us,
                (message.original_offset_us
                 if message.original_offset_us is not None else min(message.allowed_offsets_us)),
                assignments_by_name[message.name].offset_us,
            )
            for message in core_result.messages
        )
        for row in rows:
            self._validate_offset_contract(
                row.message_name,
                row.optimized_offset_us,
                "core OptimizationResult.assignments",
            )
        layout = create_output_layout(batch_output)
        network_output = layout.results / self._safe_name(network.display_name)
        network_output.mkdir(parents=False, exist_ok=False)
        detail = GuiOptimizationResult(
            network.network_id,
            network.network_name,
            network.display_name,
            network.source_file,
            request.weight_mode,
            request.mode,
            self._metrics(core_result.initial_objective, tuple(initial_state.steady_slot_loads)),
            self._metrics(core_result.objective, core_result.steady_slot_loads),
            rows,
            core_result.restart_execution.actual_attempts,
            core_result.restart_execution.stop_reason,
            core_result.elapsed_seconds,
            loaded.network.warnings,
            self._copy_int_tuple(initial_state.steady_slot_loads),
            self._copy_int_tuple(core_result.steady_slot_loads),
            self._copy_int_tuple(initial_state.startup_slot_loads),
            self._copy_int_tuple(core_result.startup_slot_loads),
            steady_counts_before=self._copy_int_tuple(initial_state.steady_slot_counts),
            steady_counts_after=self._copy_int_tuple(core_result.steady_slot_counts),
            startup_counts_before=self._copy_int_tuple(initial_state.startup_slot_counts),
            startup_counts_after=self._copy_int_tuple(core_result.startup_slot_counts),
            logs=(
                "数据源：core load_project + run_gcls",
                f"arxml_channel={channel_override or 'not_used'}",
                f"assignment_hash={core_result.assignment_hash}",
            ),
            output_directory=network_output,
        )
        stem = self._safe_name(network.display_name)
        assignment_path = export_assignments_csv(detail, network_output / "offsets.csv")
        load_plot_path = write_load_curve_png(detail, layout.plots / f"{stem}_load_curve.png")
        heatmap_path = write_load_heatmap_png(detail, layout.plots / f"{stem}_heatmap.png")
        offset_by_name = {row.message_name: row.optimized_offset_us for row in rows}
        replacements = tuple(
            DbcOffsetReplacement(
                message.name,
                message.can_id,
                message.is_extended,
                offset_by_name[message.name],
            )
            for message in loaded.network.messages
        )
        dbc_output = layout.dbc / network.source_file
        if dbc_output.exists():
            dbc_output = layout.dbc / f"{stem}_{network.source_file}"
        dbc_path = write_dbc_with_offsets(dbc_path, dbc_output, replacements)
        log_path = write_network_log(
            NetworkBatchResult(
                network.network_id,
                network.network_name,
                network.display_name,
                network.source_file,
                NetworkRunStatus.SUCCEEDED,
                request.weight_mode,
                request.mode,
                result=detail,
                warnings=detail.warnings,
                logs=detail.logs,
            ),
            layout.logs / f"{stem}.log",
        )
        return replace(
            detail,
            exported_files=(
                assignment_path,
                load_plot_path,
                heatmap_path,
                log_path,
                dbc_path,
            ),
        )

    @staticmethod
    def _validate_offset_contract(
        message_name: str, offset_us: int | None, source: str
    ) -> None:
        if offset_us not in REQUIRED_ALLOWED_OFFSETS_US:
            rendered = "missing" if offset_us is None else f"{offset_us / 1000:g} ms"
            raise ValueError(
                f"非法 Offset：报文={message_name}，值={rendered}，数据源={source}；"
                "要求 15..100 ms 且步长 5 ms，未执行取整或截断"
            )

    @staticmethod
    def _copy_int_tuple(values: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        """Create a distinct immutable array for every network DTO."""
        return tuple(value for value in values)

    @staticmethod
    def _baseline_state(loaded: LoadedProject) -> SearchState:
        state = SearchState(loaded.network.messages, loaded.slot_map)
        for message in loaded.network.messages:
            original = message.original_offset_us
            state.apply(
                message,
                original if original in message.allowed_offsets_us else min(message.allowed_offsets_us),
            )
        return state

    @staticmethod
    def _metrics(objective: ObjectiveValue, loads: tuple[int, ...]) -> ObjectiveMetrics:
        return ObjectiveMetrics(
            zss=objective.steady_peak,
            qss=objective.sum_square_load,
            standard_deviation=load_statistics(loads)[2],
            zst=objective.startup_peak,
            qst=objective.startup_sum_square_load,
            nvio=objective.violation_count,
            vvio=objective.violation_excess,
        )

    @staticmethod
    def _apply_request_settings(
        loaded: LoadedProject, request: GuiBatchOptimizationRequest
    ) -> LoadedProject:
        if request.restart.mode is RestartMode.FIXED:
            policy = RestartPolicy.fixed(request.restart.fixed_attempts, source_kind="cli")
        else:
            policy = RestartPolicy(
                mode=CoreRestartMode.ADAPTIVE,
                min_attempts=request.restart.min_attempts,
                check_interval=min(10, request.restart.min_attempts),
                patience_attempts=min(20, request.restart.max_attempts),
                max_attempts=request.restart.max_attempts,
                source_kind="cli",
            )
        optimization = replace(
            loaded.config.optimization,
            restart_policy=policy,
            peak_candidate_pool_size=request.candidate_pool_size,
            conflict_triple_enabled=request.enable_triple_search,
        )
        objective = replace(
            loaded.config.objective,
            mode=CoreObjectiveMode(request.mode.value),
            peak_tolerance=PeakToleranceConfig(
                PeakToleranceType.RELATIVE, request.balanced_tolerance
            ),
        )
        config = replace(loaded.config, optimization=optimization, objective=objective)
        return replace(loaded, config=config)

    def _finish_batch(
        self,
        request: GuiBatchOptimizationRequest,
        output_directory: Path,
        rows: tuple[NetworkBatchResult, ...],
        started: float,
        *,
        cancelled: bool = False,
    ) -> BatchOptimizationResult:
        batch = BatchOptimizationResult(
            request.inspection.session.project_name,
            request.inspection.session.session_directory,
            request.inspection.session.manifest_path,
            output_directory,
            rows,
            perf_counter() - started,
            warnings=request.inspection.warnings,
            errors=tuple(item.error for item in rows if item.status is NetworkRunStatus.FAILED and item.error),
            cancelled=cancelled,
        )
        layout = create_output_layout(output_directory)
        export_batch_summary_csv(batch, layout.results / "networks_summary.csv")
        for item in rows:
            write_network_log(
                item,
                layout.logs / f"{self._safe_name(item.display_name)}.log",
            )
        write_batch_log(batch, layout.logs / "batch.log")
        return batch

    @staticmethod
    def _emit_finished(
        callback: ProgressCallback,
        network: NetworkSummary,
        index: int,
        total: int,
        started: float,
        status: NetworkRunStatus,
    ) -> None:
        callback(
            ProgressUpdate(
                ProgressPhase.FINALIZING,
                f"{network.display_name}：{status.value}",
                elapsed_seconds=perf_counter() - started,
                network_id=network.network_id,
                network_name=network.network_name,
                network_index=index,
                network_total=total,
                network_status=status,
                overall_completed=index,
                overall_total=total,
            )
        )

    @staticmethod
    def _cancelled_rows(
        networks: tuple[NetworkSummary, ...], request: GuiBatchOptimizationRequest
    ) -> list[NetworkBatchResult]:
        return [
            NetworkBatchResult(
                network.network_id, network.network_name, network.display_name,
                network.source_file,
                (NetworkRunStatus.SKIPPED if not network.is_optimizable
                 else NetworkRunStatus.CANCELLED),
                request.weight_mode, request.mode,
                error=network.unoptimizable_reason if not network.is_optimizable else None,
            )
            for network in networks
        ]

    @classmethod
    def _arxml_channel_context(
        cls, session: ImportSession
    ) -> tuple[tuple[str, ...], str | None]:
        config_path = cls._single_workspace_path(session, InputKind.CONFIG)
        configured_channel = load_project_config(config_path).network.channel
        if not cls._records_of_kind(session, InputKind.ARXML):
            return (), configured_channel
        arxml_root = session.session_directory / "arxml"
        return discover_arxml_channel_names(arxml_root), configured_channel

    @staticmethod
    def _resolve_frame_time_channel(
        source_file: str,
        configured_channel: str | None,
        available_channels: tuple[str, ...],
    ) -> str | None:
        if configured_channel in available_channels:
            return configured_channel
        stem = Path(source_file).stem
        source_prefix = re.split(
            r"[\s_-]+Message(?:[\s_-]+list)?\b",
            stem,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        signature = re.sub(r"[^A-Za-z0-9]", "", source_prefix).casefold()
        if not signature:
            return None
        matches = tuple(
            channel
            for channel in available_channels
            if signature in re.sub(r"[^A-Za-z0-9]", "", channel).casefold()
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _unique_usable_records(session: ImportSession) -> tuple[ImportRecord, ...]:
        usable = (
            record for record in session.records
            if record.status is not ImportRecordStatus.INVALID
            and record.kind not in {InputKind.UNRECOGNIZED, InputKind.INVALID}
            and record.workspace_relative_path is not None
        )
        return tuple({record.workspace_relative_path: record for record in usable}.values())

    @classmethod
    def _records_of_kind(
        cls, session: ImportSession, kind: InputKind
    ) -> tuple[ImportRecord, ...]:
        return tuple(record for record in cls._unique_usable_records(session) if record.kind is kind)

    @classmethod
    def _single_workspace_path(cls, session: ImportSession, kind: InputKind) -> Path:
        records = cls._records_of_kind(session, kind)
        if len(records) != 1 or records[0].workspace_relative_path is None:
            raise BackendError(f"工作区要求恰好一个 {kind.value} 文件。")
        return session.session_directory / records[0].workspace_relative_path

    @staticmethod
    def _network_name_from_stem(stem: str) -> str:
        matches: list[str] = re.findall(
            r"(?:^|[_\s-])([A-Z][A-Z0-9]{1,7})(?=\s+Message(?:\s|$))", stem
        )
        if matches:
            return matches[-1]
        vcu_match = re.search(r"(?:^|_)VCU_([A-Z][A-Z0-9]{1,7})(?:_|\s|$)", stem)
        if vcu_match:
            return vcu_match.group(1)
        return WorkspaceImporter._safe_name(stem)

    @staticmethod
    def _eligibility_reason(exc: CanfdOptimizerError) -> str:
        text = str(exc)
        if "not a CAN FD data frame" in text:
            return f"跳过：包含经典 CAN 报文；仅周期 CAN FD TX 可优化。详情：{text}"
        if "no periodic CAN FD TX messages" in text:
            return f"跳过：无可优化的周期 CAN FD TX 报文。详情：{text}"
        return f"跳过：核心解析判定不可优化。详情：{text}"

    @staticmethod
    def _inspection_warnings(session: ImportSession) -> tuple[str, ...]:
        warnings: list[str] = []
        if any(record.note == DEFAULT_CONFIG_NOTE for record in session.records):
            warnings.append(DEFAULT_CONFIG_NOTE)
        unrecognized = sum(record.kind is InputKind.UNRECOGNIZED for record in session.records)
        invalid = sum(record.status is ImportRecordStatus.INVALID for record in session.records)
        if unrecognized:
            warnings.append(f"有 {unrecognized} 个未识别文件；未交给核心解析器。")
        if invalid:
            warnings.append(f"有 {invalid} 个输入无效或无法读取。")
        return tuple(warnings)
