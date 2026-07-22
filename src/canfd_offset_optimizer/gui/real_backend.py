"""Production GUI adapter for the parser, project loader and GCLS core."""

from __future__ import annotations

import hashlib
import importlib
import re
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ..config import (
    OffsetSearchConfig,
    PeakToleranceConfig,
    RestartPolicy,
    load_project_config,
)
from ..exceptions import CanfdOptimizerError
from ..models import (
    FrameProtocol as CoreFrameProtocol,
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
from ..timeline.slot_map import precompute_slot_map
from ..timeline.slot_map import build_windows
from ..timeline.state import SearchState
from .contracts import (
    BackendAvailability,
    BackendError,
    BatchOptimizationCancelled,
    BatchOptimizationResult,
    CancellationToken,
    CLASSIC_WEIGHT_MODEL,
    DbcSenderSelectionSummary,
    FrameProtocol,
    GuiBatchOptimizationRequest,
    GuiOptimizationResult,
    MessageEligibilityStatus,
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
    RouteMessageRecord,
    RoutingExclusionReport,
    SenderNodeSelectionConfig,
    SenderSelectionDbcStatus,
    WeightMode,
    WorkspaceInspection,
)
from .artifact_outputs import (
    create_output_layout,
    write_batch_log,
    write_load_curve_png,
    write_load_heatmap_png,
    write_message_eligibility_csv,
    write_network_log,
    write_routing_exclusion_csv,
    write_run_config_json,
)
from .dbc_offset_writer import (
    DbcOffsetReplacement,
    inspect_dbc_offset_write,
    write_dbc_with_offsets,
)
from .formatting import (
    export_assignments_csv,
    export_batch_summary_csv,
)
from .output_paths import (
    create_timestamped_batch_directory,
    dbc_output_destination,
    short_output_stem,
)
from .sender_selection import (
    apply_selection_to_summary,
    build_sender_inventory,
    dbc_identity,
    dbc_revision,
    validate_complete_selection,
)
from .workspace_io import DEFAULT_CONFIG_NOTE, WorkspaceImporter
from .routing_exclusion import (
    RouteMessageTableParser,
    RouteTableParseError,
    match_route_messages,
)


REQUIRED_ALLOWED_OFFSETS_US = OffsetSearchConfig().candidate_offsets_us


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
        routing_records = tuple(
            record
            for record in unique_records
            if record.kind is InputKind.ROUTING_TABLE
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
        allowed_offsets_us = REQUIRED_ALLOWED_OFFSETS_US
        if len(config_records) == 1:
            config_path = self._single_workspace_path(session, InputKind.CONFIG)
            allowed_offsets_us = load_project_config(config_path).optimization.allowed_offsets_us
        if arxml_records and len(config_records) == 1:
            try:
                arxml_channels, configured_channel = self._arxml_channel_context(session)
            except CanfdOptimizerError as exc:
                errors.append(f"ARXML 通道检查失败：{type(exc).__name__}: {exc}")
        display_counts: dict[str, int] = {}
        networks: list[NetworkSummary] = []
        sender_summaries: list[DbcSenderSelectionSummary] = []
        parsed_messages_by_network: dict[
            str, tuple[tuple[int, str, bool], ...]
        ] = {}
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
            record_sha256 = record.sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
            dbc_id = dbc_identity(record.workspace_relative_path, record_sha256)
            try:
                parsed = parse_dbc(path, allowed_offsets_us=allowed_offsets_us)
                message_count = len(parsed.messages)
                optimizable = True
                reason = None
                network_warnings = list(parsed.warnings)
                frame_protocol = (
                    FrameProtocol.CLASSIC_CAN
                    if parsed.messages[0].frame_protocol is CoreFrameProtocol.CLASSIC_CAN
                    else FrameProtocol.CAN_FD
                )
                parsed_messages_by_network[network_id] = tuple(
                    (message.can_id, message.name, message.is_extended)
                    for message in parsed.messages
                )
            except CanfdOptimizerError as exc:
                message_count = 0
                optimizable = False
                reason = self._eligibility_reason(exc)
                network_warnings = []
                frame_protocol = FrameProtocol.CAN_FD
            sender_summary = build_sender_inventory(
                dbc_id=dbc_id,
                dbc_file=path.name,
                network_id=network_id,
                network_name=network_name,
                source_workspace_path=record.workspace_relative_path,
                sha256=record_sha256,
                dbc_path=path,
                allowed_offsets_us=allowed_offsets_us,
            )
            sender_summaries.append(sender_summary)
            parsed_messages_by_network[network_id] = tuple(
                (message.can_id, message.message_name, message.is_extended)
                for message in sender_summary.messages
                if message.can_id is not None and message.base_eligible
            )
            frame_time_channel = self._resolve_frame_time_channel(
                path.name, configured_channel, arxml_channels
            )
            fd_modes = [WeightMode.PAYLOAD_BYTES]
            if frame_time_channel is not None:
                fd_modes.append(WeightMode.FRAME_TIME_US)
            available_weight_modes: tuple[WeightMode, ...] = tuple(fd_modes)
            automatic_weight_mode: WeightMode | None = (
                WeightMode.FRAME_TIME_US
                if frame_time_channel is not None
                else WeightMode.PAYLOAD_BYTES
            )
            classic_weight_model: str | None = None
            if optimizable and frame_protocol is FrameProtocol.CLASSIC_CAN:
                available_weight_modes = (WeightMode.PAYLOAD_BYTES,)
                automatic_weight_mode = WeightMode.PAYLOAD_BYTES
                classic_weight_model = CLASSIC_WEIGHT_MODEL
                network_warnings.append(
                    'classic_weight_model = "payload_bytes_approximation"'
                )
            elif optimizable and frame_time_channel is not None:
                network_warnings.append(
                    f"frame_time_us ARXML Controller：{frame_time_channel}"
                )
            elif optimizable:
                network_warnings.append(
                    "CAN FD 缺少唯一 ARXML Controller 映射，只能选择 payload_bytes。"
                )
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
                    frame_protocol=frame_protocol,
                    automatic_weight_mode=automatic_weight_mode,
                    classic_weight_model=classic_weight_model,
                    warnings=tuple(network_warnings),
                    unoptimizable_reason=reason,
                    dbc_id=dbc_id,
                    dbc_message_count=sender_summary.message_count,
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
        routing_report = RoutingExclusionReport(table_count=len(routing_records))
        route_source_records: list[RouteMessageRecord] = []
        route_parser = RouteMessageTableParser()
        for record in routing_records:
            assert record.workspace_relative_path is not None
            path = session.session_directory / record.workspace_relative_path
            try:
                route_source_records.extend(route_parser.parse(path))
            except RouteTableParseError as exc:
                errors.append(
                    f"路由报文排除表解析失败：{path.name}：{exc}"
                )
        if not any(error.startswith("路由报文排除表解析失败：") for error in errors):
            routing_report = match_route_messages(
                route_source_records,
                {network.network_id: network.network_name for network in networks},
                parsed_messages_by_network,
                table_count=len(routing_records),
            )
            updated_networks: list[NetworkSummary] = []
            for network in networks:
                if not network.is_optimizable:
                    updated_networks.append(network)
                    continue
                base_count = network.message_count
                excluded_count = len(
                    routing_report.excluded_can_ids(network.network_id)
                )
                final_count = base_count - excluded_count
                if final_count == 0:
                    updated_networks.append(
                        replace(
                            network,
                            is_optimizable=False,
                            message_count=0,
                            available_weight_modes=(),
                            automatic_weight_mode=None,
                            unoptimizable_reason=(
                                "跳过：所有可优化周期 TX 报文均为路由报文"
                            ),
                            base_eligible_message_count=base_count,
                            routing_excluded_count=excluded_count,
                            final_eligible_message_count=0,
                        )
                    )
                else:
                    updated_networks.append(
                        replace(
                            network,
                            message_count=final_count,
                            base_eligible_message_count=base_count,
                            routing_excluded_count=excluded_count,
                            final_eligible_message_count=final_count,
                        )
                    )
            networks = updated_networks
            sender_summaries = [
                replace(
                    summary,
                    messages=tuple(
                        replace(
                            message,
                            routing_match=(
                                message.can_id is not None
                                and message.can_id
                                in routing_report.excluded_can_ids(summary.network_id)
                            ),
                        )
                        for message in summary.messages
                    ),
                )
                for summary in sender_summaries
            ]
        used_paths = {
            record.workspace_relative_path
            for record in unique_records
            if record.kind
            in {
                InputKind.DBC,
                InputKind.CONFIG,
                InputKind.ARXML,
                InputKind.ROUTING_TABLE,
            }
        }
        updated_session = replace(
            session,
            records=tuple(
                replace(record, used_by_parser=record.workspace_relative_path in used_paths)
                for record in session.records
            ),
        )
        self._write_manifest(updated_session)
        warnings = self._inspection_warnings(updated_session, routing_report)
        summaries = tuple(sender_summaries)
        revision = dbc_revision(summaries)
        return WorkspaceInspection(
            session=updated_session,
            networks=tuple(networks),
            missing_required=missing,
            warnings=warnings,
            errors=tuple(errors),
            routing_exclusion=routing_report,
            sender_selection=SenderNodeSelectionConfig(dbc_revision=revision),
            sender_selection_summaries=summaries,
            dbc_revision=revision,
        )

    def apply_sender_selection(
        self,
        inspection: WorkspaceInspection,
        selection: SenderNodeSelectionConfig,
    ) -> WorkspaceInspection:
        """Confirm per-DBC local transmitters and derive the formal final set."""

        if selection.dbc_revision != inspection.dbc_revision:
            raise ValueError("发送节点选择不属于当前 DBC 集合或内容版本")
        validate_complete_selection(inspection.sender_selection_summaries, selection)
        confirmed = replace(selection, confirmed=True)
        summaries = tuple(
            apply_selection_to_summary(summary, confirmed)
            for summary in inspection.sender_selection_summaries
        )
        by_network = {summary.network_id: summary for summary in summaries}
        networks: list[NetworkSummary] = []
        for network in inspection.networks:
            summary = by_network[network.network_id]
            excluded = summary.excluded_by_user
            final_count = summary.final_eligible_count
            base_count = summary.base_eligible_count
            selected_input_errors = tuple(
                record.exclusion_reason
                for record in summary.messages
                if record.selected_transmitter_match
                and record.final_status is MessageEligibilityStatus.INPUT_ERROR
            )
            if excluded:
                reason = "用户明确排除该 DBC"
            elif selected_input_errors:
                reason = selected_input_errors[0]
            elif summary.status is SenderSelectionDbcStatus.INPUT_ERROR:
                reason = summary.note or "DBC 输入异常"
            elif summary.selected_sender_message_count == 0:
                reason = "所选本机节点没有发送任何报文"
            elif base_count == 0:
                reason = "所选本机节点没有基础合资格周期 TX 报文"
            elif final_count == 0:
                reason = "所选本机节点的合资格周期 TX 均被路由表排除"
            else:
                reason = None
            selected_protocols = {
                record.frame_protocol
                for record in summary.messages
                if record.selected_transmitter_match
                and record.base_eligible
                and record.final_status is not MessageEligibilityStatus.INPUT_ERROR
                and record.frame_protocol is not None
            }
            selected_protocol = (
                next(iter(selected_protocols))
                if len(selected_protocols) == 1
                else network.frame_protocol
            )
            available_modes = network.available_weight_modes
            automatic_weight = network.automatic_weight_mode
            classic_model = None
            if selected_protocol is FrameProtocol.CLASSIC_CAN:
                available_modes = (WeightMode.PAYLOAD_BYTES,)
                automatic_weight = WeightMode.PAYLOAD_BYTES
                classic_model = CLASSIC_WEIGHT_MODEL
            elif not available_modes:
                available_modes = (WeightMode.PAYLOAD_BYTES,)
                automatic_weight = WeightMode.PAYLOAD_BYTES
            networks.append(
                replace(
                    network,
                    is_optimizable=reason is None,
                    frame_protocol=selected_protocol,
                    available_weight_modes=available_modes,
                    automatic_weight_mode=automatic_weight,
                    classic_weight_model=classic_model,
                    message_count=final_count,
                    base_eligible_message_count=base_count,
                    routing_excluded_count=summary.routing_excluded_count,
                    final_eligible_message_count=final_count,
                    unoptimizable_reason=reason,
                    dbc_message_count=summary.message_count,
                    selected_transmitters=summary.selected_transmitters,
                    selected_transmitter_message_count=(
                        summary.selected_sender_message_count
                    ),
                    unselected_transmitter_excluded_count=(
                        summary.unselected_transmitter_count
                    ),
                    excluded_by_user=excluded,
                )
            )
        return replace(
            inspection,
            networks=tuple(networks),
            sender_selection=confirmed,
            sender_selection_summaries=summaries,
        )

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        started = perf_counter()
        session = request.inspection.session
        output_directory = create_timestamped_batch_directory(
            request.output_root.resolve()
        )
        create_output_layout(output_directory)
        results: list[NetworkBatchResult] = []
        networks = request.inspection.networks
        arxml_channels, configured_channel = self._arxml_channel_context(session)
        channel_overrides = {
            network.network_id: (
                self._resolve_frame_time_channel(
                    network.source_file, configured_channel, arxml_channels
                )
                if network.frame_protocol is FrameProtocol.CAN_FD
                else None
            )
            for network in request.inspection.optimizable_networks
        }
        total = len(networks)
        for index, network in enumerate(networks, start=1):
            actual_weight = self._network_weight(network, request)
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
                        actual_weight, request.mode,
                        error=network.unoptimizable_reason,
                        warnings=network.warnings,
                        logs=(f"核心资格判定跳过：{network.unoptimizable_reason}",),
                        base_eligible_message_count=self._base_count(network),
                        routing_excluded_count=network.routing_excluded_count,
                        final_eligible_message_count=self._final_count(network),
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
                        detail.weight_mode, request.mode, result=detail,
                        warnings=detail.warnings, logs=detail.logs,
                        base_eligible_message_count=self._base_count(network),
                        routing_excluded_count=network.routing_excluded_count,
                        final_eligible_message_count=self._final_count(network),
                    )
                )
                status = NetworkRunStatus.SUCCEEDED
            except OptimizationCancelled:
                results.append(
                    NetworkBatchResult(
                        network.network_id, network.network_name, network.display_name,
                        network.source_file, NetworkRunStatus.CANCELLED,
                        actual_weight, request.mode,
                        logs=("用户取消；核心未产生成功结果。",),
                        base_eligible_message_count=self._base_count(network),
                        routing_excluded_count=network.routing_excluded_count,
                        final_eligible_message_count=self._final_count(network),
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
                        actual_weight, request.mode, error=message,
                        logs=(f"真实后端失败：{message}",),
                        base_eligible_message_count=self._base_count(network),
                        routing_excluded_count=network.routing_excluded_count,
                        final_eligible_message_count=self._final_count(network),
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
        actual_weight = self._network_weight(network, request)
        core_weight = CoreWeightMode(actual_weight.value)
        core_mode = CoreObjectiveMode(request.mode.value)
        if actual_weight is WeightMode.FRAME_TIME_US and channel_override is None:
            raise BackendError(
                f"网段 {network.display_name} 没有唯一的 ARXML Controller 映射"
            )
        loaded = load_project(
            dbc_path, arxml_root, config_path,
            weight_mode_override=core_weight,
            channel_override=channel_override,
            objective_mode_override=core_mode,
            offset_search_override=request.offset_search,
            selected_transmitters=request.sender_selection.selected_for(
                network.dbc_id or ""
            ),
        )
        loaded = self._apply_routing_exclusions(loaded, request, network)
        loaded = self._apply_request_settings(loaded, request)
        preflight_replacements = tuple(
            DbcOffsetReplacement(
                message.name,
                message.can_id,
                message.is_extended,
                (
                    message.original_offset_us
                    if message.original_offset_us is not None
                    else min(message.allowed_offsets_us)
                ),
            )
            for message in loaded.network.messages
        )
        offset_write_plan = None
        dbc_preflight_error: str | None = None
        try:
            offset_write_plan = inspect_dbc_offset_write(
                dbc_path, preflight_replacements
            )
        except (OSError, ValueError) as exc:
            # DBC is an export artifact. Its inability to accept assignments must
            # not discard a valid and potentially expensive core optimization.
            dbc_preflight_error = f"{type(exc).__name__}: {exc}"
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
                request.offset_search.candidate_offsets_us,
            )
        layout = create_output_layout(batch_output)
        stem = short_output_stem(network.display_name)
        network_output = layout.results / stem
        network_output.mkdir(parents=False, exist_ok=False)
        detail = GuiOptimizationResult(
            network.network_id,
            network.network_name,
            network.display_name,
            network.source_file,
            actual_weight,
            request.mode,
            self._metrics(
                core_result.initial_objective,
                tuple(initial_state.steady_slot_loads),
                physical=actual_weight is WeightMode.FRAME_TIME_US,
            ),
            self._metrics(
                core_result.objective,
                core_result.steady_slot_loads,
                physical=actual_weight is WeightMode.FRAME_TIME_US,
            ),
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
                "负载口径：可优化报文负载曲线（路由报文已在 GCLS 前排除）",
                f"base_eligible_message_count={self._base_count(network)}",
                f"routing_excluded_count={network.routing_excluded_count}",
                f"final_eligible_message_count={self._final_count(network)}",
                f"arxml_channel={channel_override or 'not_used'}",
                f"weight_mode={actual_weight.value}",
                f"offset_min_ms={request.offset_search.min_offset_ms}",
                f"offset_max_ms={request.offset_search.max_offset_ms}",
                f"offset_step_ms={request.offset_search.offset_step_ms}",
                f"offset_effective_max_ms={request.offset_search.effective_max_offset_ms}",
                f"offset_candidate_count={request.offset_search.candidate_count}",
                *(
                    (
                        f"dbc_offset_attribute={offset_write_plan.attribute_name or 'existing'}",
                        f"dbc_offset_replaced_count={offset_write_plan.replaced_count}",
                        f"dbc_offset_inserted_count={offset_write_plan.inserted_count}",
                    )
                    if offset_write_plan is not None
                    else (
                        "dbc_offset_preflight=failed",
                        f"dbc_offset_preflight_error={dbc_preflight_error}",
                    )
                ),
                *(
                    ('classic_weight_model = "payload_bytes_approximation"',)
                    if network.frame_protocol is FrameProtocol.CLASSIC_CAN
                    else ()
                ),
                f"assignment_hash={core_result.assignment_hash}",
            ),
            output_directory=network_output,
            frame_protocol=network.frame_protocol,
            classic_weight_model=network.classic_weight_model,
            offset_search=request.offset_search,
        )
        progress_callback(
            ProgressUpdate(
                ProgressPhase.FINALIZING,
                f"{network.display_name}：正在生成负载图、热力图和 DBC 副本",
                elapsed_seconds=perf_counter() - started,
                network_id=network.network_id,
                network_name=network.network_name,
                network_index=index,
                network_total=total,
                overall_completed=index - 1,
                overall_total=total,
            )
        )
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
        dbc_output = dbc_output_destination(
            layout.dbc,
            network.source_file,
            network.display_name,
            network.network_id,
        )
        written_dbc_path: Path | None = None
        dbc_write_error = dbc_preflight_error
        if dbc_write_error is None:
            try:
                written_dbc_path = write_dbc_with_offsets(
                    dbc_path, dbc_output, replacements
                )
            except (OSError, ValueError) as exc:
                dbc_write_error = f"{type(exc).__name__}: {exc}"
        if dbc_write_error is None:
            detail = replace(
                detail,
                logs=detail.logs
                + (
                    "dbc_write_status=succeeded",
                    f"dbc_output_path={written_dbc_path}",
                ),
            )
        else:
            warning = (
                "DBC 写回失败；优化结果及其他输出已保留："
                f"{dbc_write_error}；目标：{dbc_output}"
            )
            detail = replace(
                detail,
                warnings=detail.warnings + (warning,),
                logs=detail.logs
                + (
                    "dbc_write_status=failed",
                    f"dbc_write_error={dbc_write_error}",
                    f"dbc_output_path={dbc_output}",
                ),
                dbc_write_error=dbc_write_error,
            )
        log_path = write_network_log(
            NetworkBatchResult(
                network.network_id,
                network.network_name,
                network.display_name,
                network.source_file,
                NetworkRunStatus.SUCCEEDED,
                actual_weight,
                request.mode,
                result=detail,
                warnings=detail.warnings,
                logs=detail.logs,
                base_eligible_message_count=self._base_count(network),
                routing_excluded_count=network.routing_excluded_count,
                final_eligible_message_count=self._final_count(network),
            ),
            layout.logs / f"{stem}.log",
        )
        exported_files = [assignment_path, load_plot_path, heatmap_path, log_path]
        if written_dbc_path is not None:
            exported_files.append(written_dbc_path)
        return replace(detail, exported_files=tuple(exported_files))

    @staticmethod
    def _validate_offset_contract(
        message_name: str,
        offset_us: int | None,
        source: str,
        allowed_offsets_us: tuple[int, ...] = REQUIRED_ALLOWED_OFFSETS_US,
    ) -> None:
        if offset_us not in allowed_offsets_us:
            rendered = "missing" if offset_us is None else f"{offset_us / 1000:g} ms"
            raise ValueError(
                f"Illegal Offset: message={message_name}, value={rendered}, source={source}; "
                f"candidate domain={tuple(value / 1000 for value in allowed_offsets_us)} ms; "
                "no rounding or truncation was applied"
            )

    @staticmethod
    def _copy_int_tuple(values: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        """Create a distinct immutable array for every network DTO."""
        return tuple(value for value in values)

    @staticmethod
    def _baseline_state(loaded: LoadedProject) -> SearchState:
        baseline_messages = tuple(
            replace(
                message,
                allowed_offsets_us=(
                    message.original_offset_us
                    if message.original_offset_us is not None
                    else min(message.allowed_offsets_us),
                ),
            )
            for message in loaded.network.messages
        )
        baseline_map = precompute_slot_map(
            baseline_messages,
            loaded.network.startup_window,
            loaded.network.steady_window,
        )
        state = SearchState(baseline_messages, baseline_map)
        for message in baseline_messages:
            state.apply(message, message.allowed_offsets_us[0])
        return state

    @staticmethod
    def _base_count(network: NetworkSummary) -> int:
        return (
            network.message_count
            if network.base_eligible_message_count is None
            else network.base_eligible_message_count
        )

    @staticmethod
    def _final_count(network: NetworkSummary) -> int:
        return (
            network.message_count
            if network.final_eligible_message_count is None
            else network.final_eligible_message_count
        )

    @classmethod
    def _apply_routing_exclusions(
        cls,
        loaded: LoadedProject,
        request: GuiBatchOptimizationRequest,
        network: NetworkSummary,
    ) -> LoadedProject:
        excluded_ids = request.inspection.routing_exclusion.excluded_can_ids(
            network.network_id
        )
        if not excluded_ids:
            return loaded
        remaining = tuple(
            message
            for message in loaded.network.messages
            if message.can_id not in excluded_ids
        )
        expected = cls._final_count(network)
        if len(remaining) != expected:
            raise BackendError(
                f"网段 {network.display_name} 路由排除计数不一致："
                f"预期 {expected}，实际 {len(remaining)}"
            )
        if not remaining:
            raise BackendError("所有可优化周期 TX 报文均为路由报文")
        startup, steady, hyperperiod = build_windows(
            remaining,
            loaded.config.optimization.slot_width_us,
            loaded.config.optimization.hyperperiod_us,
            loaded.config.optimization.hyperperiod_cap_us,
        )
        routing_paths = tuple(
            dict.fromkeys(
                request.inspection.session.session_directory
                / record.workspace_relative_path
                for record in request.inspection.session.records_of_kind(
                    InputKind.ROUTING_TABLE
                )
                if record.workspace_relative_path is not None
                and record.status is not ImportRecordStatus.INVALID
            )
        )
        warnings = tuple(
            warning
            for warning in loaded.network.warnings
            if not warning.startswith("average load exceeds configured limit")
        )
        filtered_network = replace(
            loaded.network,
            messages=remaining,
            startup_window=startup,
            steady_window=steady,
            hyperperiod_us=hyperperiod,
            warnings=warnings
            + (
                f"routing_excluded_count={len(excluded_ids)}；"
                "路由报文未进入 GCLS 与可优化报文负载曲线",
            ),
            input_files=loaded.network.input_files + routing_paths,
        )
        if (
            filtered_network.weight_mode is CoreWeightMode.FRAME_TIME_US
            and filtered_network.average_load
            > loaded.config.model.average_load_limit
        ):
            filtered_network = replace(
                filtered_network,
                warnings=filtered_network.warnings
                + (
                    "average load exceeds configured limit and cannot be repaired "
                    "by Offset optimization",
                ),
            )
        return replace(
            loaded,
            network=filtered_network,
            slot_map=precompute_slot_map(remaining, startup, steady),
        )

    @staticmethod
    def _metrics(
        objective: ObjectiveValue,
        loads: tuple[int, ...],
        *,
        physical: bool = True,
    ) -> ObjectiveMetrics:
        return ObjectiveMetrics(
            zss=objective.steady_peak,
            qss=objective.sum_square_load,
            standard_deviation=load_statistics(loads)[2],
            zst=objective.startup_peak,
            qst=objective.startup_sum_square_load,
            nvio=objective.violation_count if physical else None,
            vvio=objective.violation_excess if physical else None,
        )

    @staticmethod
    def _network_weight(
        network: NetworkSummary, request: GuiBatchOptimizationRequest
    ) -> WeightMode:
        if network.frame_protocol is FrameProtocol.CLASSIC_CAN:
            return request.classic_can_weight
        return request.can_fd_weight

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
        write_run_config_json(request, layout.results / "run_config.json")
        write_message_eligibility_csv(
            request, layout.results / "message_eligibility.csv"
        )
        write_routing_exclusion_csv(
            request.inspection.routing_exclusion,
            layout.results / "routing_exclusion_summary.csv",
        )
        for item in rows:
            write_network_log(
                item,
                layout.logs / f"{short_output_stem(item.display_name)}.log",
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
                RealBackend._network_weight(network, request), request.mode,
                error=network.unoptimizable_reason if not network.is_optimizable else None,
                base_eligible_message_count=RealBackend._base_count(network),
                routing_excluded_count=network.routing_excluded_count,
                final_eligible_message_count=RealBackend._final_count(network),
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
        matrix_marker = re.search(r"_Matrix(?:_|$)", stem, re.IGNORECASE)
        if matrix_marker:
            prefix = stem[: matrix_marker.start()]
            if ")" in prefix:
                matrix_network = prefix.rsplit(")", 1)[1].strip("_ -")
            else:
                matrix_network = prefix.rsplit("_", 1)[-1].strip("_ -")
            if matrix_network:
                return WorkspaceImporter._safe_name(matrix_network)
        return WorkspaceImporter._safe_name(stem)

    @staticmethod
    def _eligibility_reason(exc: CanfdOptimizerError) -> str:
        text = str(exc)
        if "mixes eligible Classic CAN and CAN FD" in text:
            return (
                "跳过：同一物理网段混合了 Classic CAN 与 CAN FD；"
                f"当前核心不支持混合帧格式优化。详情：{text}"
            )
        if "no eligible periodic TX messages" in text:
            return f"跳过：没有符合资格的周期 TX 报文。详情：{text}"
        if "not a CAN FD data frame" in text:
            return f"跳过：包含经典 CAN 报文；仅周期 CAN FD TX 可优化。详情：{text}"
        if "no periodic CAN FD TX messages" in text:
            return f"跳过：无可优化的周期 CAN FD TX 报文。详情：{text}"
        return f"跳过：核心解析判定不可优化。详情：{text}"

    @staticmethod
    def _inspection_warnings(
        session: ImportSession, routing: RoutingExclusionReport
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if any(record.note == DEFAULT_CONFIG_NOTE for record in session.records):
            warnings.append(DEFAULT_CONFIG_NOTE)
        unrecognized = sum(record.kind is InputKind.UNRECOGNIZED for record in session.records)
        invalid = sum(record.status is ImportRecordStatus.INVALID for record in session.records)
        if unrecognized:
            warnings.append(f"有 {unrecognized} 个未识别文件；未交给核心解析器。")
        if invalid:
            warnings.append(f"有 {invalid} 个输入无效或无法读取。")
        if routing.not_found_count:
            warnings.append(
                f"路由报文表有 {routing.not_found_count} 条记录未找到匹配报文。"
            )
        if routing.ambiguous_count:
            warnings.append(
                f"路由报文表有 {routing.ambiguous_count} 条记录匹配歧义，未执行排除。"
            )
        if routing.invalid_can_id_count:
            warnings.append(
                f"路由报文表有 {routing.invalid_can_id_count} 条记录的 CAN ID 无效。"
            )
        conflict_count = sum(
            "duplicate_conflict_warning" in {issue.value for issue in record.issues}
            for record in routing.records
        )
        if conflict_count:
            warnings.append(
                f"路由报文表有 {conflict_count} 条重复记录的辅助信息冲突。"
            )
        return tuple(warnings)
