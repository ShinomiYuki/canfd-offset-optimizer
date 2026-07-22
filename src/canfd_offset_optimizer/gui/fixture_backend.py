"""Explicit deterministic fixture backend for GUI tests only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import Iterable

from .artifact_outputs import (
    create_output_layout,
    write_batch_log,
    write_load_curve_png,
    write_load_heatmap_png,
    write_network_log,
)
from .output_paths import create_timestamped_batch_directory, short_output_stem
from .contracts import (
    BackendAvailability,
    BackendError,
    BatchOptimizationCancelled,
    BatchOptimizationResult,
    CancellationToken,
    FrameProtocol,
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
    OptimizationMode,
    ProgressCallback,
    ProgressPhase,
    ProgressUpdate,
    RestartMode,
    SenderNodeSelectionConfig,
    WeightMode,
    WorkspaceInspection,
)
from .formatting import (
    export_assignments_csv,
    export_batch_summary_csv,
)
from .workspace_io import (
    DEFAULT_CONFIG_NOTE,
    DEFAULT_PROJECT_CONFIG_PATH,
    add_default_project_config,
)


class FixtureBackend:
    """Copy real files, then simulate all-network inspection and optimization."""

    _LOAD_PROFILES = (
        (
            (520, 610, 545, 680, 570, 630, 555, 650, 580, 620, 540, 665),
            (555, 570, 560, 585, 565, 575, 558, 580, 568, 572, 562, 578),
            (470, 590, 520, 640, 535, 605, 510, 625),
            (520, 545, 530, 555, 535, 548, 528, 552),
        ),
        (
            (490, 650, 530, 620, 575, 690, 515, 640, 560, 675, 525, 610),
            (545, 565, 550, 575, 560, 580, 548, 570, 555, 578, 552, 568),
            (455, 615, 500, 660, 525, 630, 485, 645),
            (505, 535, 515, 545, 525, 540, 512, 542),
        ),
        (
            (560, 625, 500, 670, 545, 655, 515, 685, 530, 640, 505, 660),
            (550, 568, 545, 578, 552, 572, 548, 580, 555, 570, 546, 575),
            (485, 600, 470, 650, 510, 620, 495, 635),
            (515, 540, 508, 550, 520, 545, 512, 548),
        ),
    )

    _EXTENSIONS = {
        ".dbc": InputKind.DBC,
        ".yaml": InputKind.CONFIG,
        ".yml": InputKind.CONFIG,
        ".arxml": InputKind.ARXML,
    }
    _CATEGORY_DIRECTORIES = {
        InputKind.DBC: "dbc",
        InputKind.CONFIG: "config",
        InputKind.ARXML: "arxml",
        InputKind.OTHER_SUPPORTED: "other",
        InputKind.UNRECOGNIZED: "unrecognized",
    }

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delay_seconds: float = 0.01,
        fail_inspection: bool = False,
        fail_all_optimization: bool = False,
        fail_networks: Iterable[str] = (),
        skip_networks: Iterable[str] = (),
        extra_warning: str | None = None,
        default_config_path: Path = DEFAULT_PROJECT_CONFIG_PATH,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._delay_seconds = delay_seconds
        self._fail_inspection = fail_inspection
        self._fail_all_optimization = fail_all_optimization
        self._fail_networks = frozenset(fail_networks)
        self._skip_networks = frozenset(skip_networks)
        self._extra_warning = extra_warning
        self._default_config_path = default_config_path
        self._profile_index_by_network_id: dict[str, int] = {}

    @property
    def availability(self) -> BackendAvailability:
        return BackendAvailability(True, "FixtureBackend")

    def import_inputs(
        self,
        sources: tuple[Path, ...],
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> ImportSession:
        if not sources:
            raise BackendError("请至少添加一个文件或目录。")
        started = perf_counter()
        imported_at = datetime.now(timezone.utc).isoformat()
        discovered, invalid_sources = self._discover_sources(sources)
        project_name = self._project_name(discovered, sources)
        session_id = self._session_id(project_name)
        session_directory = self._unique_directory(
            self._workspace_root / "user_input", session_id
        )
        session_directory.mkdir(parents=True, exist_ok=False)
        records: list[ImportRecord] = []
        for path, note in invalid_sources:
            records.append(
                ImportRecord(
                    path,
                    None,
                    InputKind.INVALID,
                    ImportRecordStatus.INVALID,
                    None,
                    None,
                    imported_at,
                    note=note,
                )
            )

        duplicate_index: dict[tuple[str, str, str], Path] = {}
        destination_hashes: dict[str, str] = {}
        total = max(1, len(discovered))
        for index, (source, relative, root_label) in enumerate(discovered, start=1):
            cancellation_token.raise_if_cancelled()
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.IMPORTING,
                    f"复制并识别 {source.name}",
                    elapsed_seconds=perf_counter() - started,
                    overall_completed=index - 1,
                    overall_total=total,
                )
            )
            try:
                size = source.stat().st_size
                digest = self._sha256(source)
                kind = self._classify(source)
                duplicate_key = (kind.value, source.name.casefold(), digest)
                duplicate_path = duplicate_index.get(duplicate_key)
                if duplicate_path is not None:
                    records.append(
                        ImportRecord(
                            source.resolve(),
                            duplicate_path,
                            kind,
                            ImportRecordStatus.DUPLICATE,
                            size,
                            digest,
                            imported_at,
                            note="同名同内容文件已按 SHA-256 去重",
                        )
                    )
                    continue
                destination_relative = self._destination_relative(kind, relative, root_label)
                status = ImportRecordStatus.IMPORTED
                existing_hash = destination_hashes.get(destination_relative.as_posix().casefold())
                if existing_hash is not None and existing_hash != digest:
                    destination_relative = self._conflict_name(destination_relative, digest)
                    status = ImportRecordStatus.CONFLICT_RENAMED
                while destination_relative.as_posix().casefold() in destination_hashes:
                    destination_relative = self._conflict_name(destination_relative, digest)
                destination = session_directory / destination_relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                destination_hashes[destination_relative.as_posix().casefold()] = digest
                duplicate_index[duplicate_key] = destination_relative
                records.append(
                    ImportRecord(
                        source.resolve(),
                        destination_relative,
                        kind,
                        status,
                        size,
                        digest,
                        imported_at,
                        note=(
                            "同名不同内容文件已使用 SHA-256 后缀稳定重命名"
                            if status is ImportRecordStatus.CONFLICT_RENAMED
                            else ""
                        ),
                    )
                )
            except (OSError, PermissionError) as exc:
                records.append(
                    ImportRecord(
                        source.resolve(strict=False),
                        None,
                        InputKind.INVALID,
                        ImportRecordStatus.INVALID,
                        None,
                        None,
                        imported_at,
                        note=f"无法读取或复制：{exc}",
                    )
                )
            self._tick(cancellation_token)

        default_record = add_default_project_config(
            session_directory,
            records,
            imported_at,
            self._default_config_path,
        )
        if default_record is not None:
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.IMPORTING,
                    DEFAULT_CONFIG_NOTE,
                    elapsed_seconds=perf_counter() - started,
                    overall_completed=total,
                    overall_total=total,
                )
            )
        manifest_path = session_directory / "import_manifest.json"
        session = ImportSession(
            session_id=session_id,
            project_name=project_name,
            workspace_root=self._workspace_root,
            session_directory=session_directory,
            manifest_path=manifest_path,
            created_at=imported_at,
            records=tuple(records),
        )
        self._write_manifest(session)
        progress_callback(
            ProgressUpdate(
                ProgressPhase.IMPORTING,
                "工程文件已复制到 user_input 工作区",
                elapsed_seconds=perf_counter() - started,
                overall_completed=total,
                overall_total=total,
            )
        )
        return session

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection:
        started = perf_counter()
        if not session.session_directory.is_dir() or not session.manifest_path.is_file():
            raise BackendError("导入工作区或 import_manifest.json 不存在。")
        for index, message in enumerate(("校验工作区副本", "识别必需输入", "发现全部网段"), 1):
            self._tick(cancellation_token)
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.INSPECTING,
                    message,
                    elapsed_seconds=perf_counter() - started,
                    overall_completed=index,
                    overall_total=3,
                )
            )
        if self._fail_inspection:
            raise BackendError("FixtureBackend 模拟工程整体解析失败")

        usable = tuple(
            record
            for record in session.records
            if record.status is not ImportRecordStatus.INVALID
            and record.kind not in {InputKind.UNRECOGNIZED, InputKind.INVALID}
        )
        unique_by_workspace = {
            record.workspace_relative_path: record
            for record in usable
            if record.workspace_relative_path is not None
        }
        unique_records = tuple(unique_by_workspace.values())
        dbc_records = tuple(record for record in unique_records if record.kind is InputKind.DBC)
        config_records = tuple(
            record for record in unique_records if record.kind is InputKind.CONFIG
        )
        arxml_records = tuple(record for record in unique_records if record.kind is InputKind.ARXML)
        missing: list[InputKind] = []
        if not dbc_records:
            missing.append(InputKind.DBC)
        if not config_records:
            missing.append(InputKind.CONFIG)
        errors: list[str] = []
        if len(config_records) > 1:
            errors.append("发现多个项目配置，无法确定本次批量运行使用哪一个配置。")
        weight_modes = (
            (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US)
            if arxml_records
            else (WeightMode.PAYLOAD_BYTES,)
        )
        networks = self._networks_from_dbc(dbc_records, weight_modes)
        self._profile_index_by_network_id = {
            network.network_id: index % len(self._LOAD_PROFILES)
            for index, network in enumerate(networks)
        }
        used_paths = {record.workspace_relative_path for record in unique_records}
        updated_records = tuple(
            replace(
                record,
                used_by_parser=(
                    record.workspace_relative_path in used_paths
                    and record.kind in {InputKind.DBC, InputKind.CONFIG, InputKind.ARXML}
                ),
            )
            for record in session.records
        )
        updated_session = replace(session, records=updated_records)
        self._write_manifest(updated_session)
        warnings = self._inspection_warnings(updated_session)
        return WorkspaceInspection(
            session=updated_session,
            networks=networks,
            missing_required=tuple(missing),
            warnings=warnings,
            errors=tuple(errors),
        )

    def apply_sender_selection(
        self,
        inspection: WorkspaceInspection,
        selection: SenderNodeSelectionConfig,
    ) -> WorkspaceInspection:
        """Fixture inventories are intentionally absent; preserve legacy GUI fixtures."""
        if inspection.sender_selection_summaries:
            raise BackendError("FixtureBackend 不模拟正式 DBC 发送节点资格。")
        if selection.selected_transmitters_by_dbc or selection.excluded_dbc_ids:
            raise BackendError("FixtureBackend 没有可应用的 DBC 发送节点清单。")
        return inspection

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        if self._fail_all_optimization:
            raise BackendError("FixtureBackend 模拟工程级批量优化失败")
        started = perf_counter()
        output_directory = create_timestamped_batch_directory(request.output_root)
        create_output_layout(output_directory)
        network_results: list[NetworkBatchResult] = []
        networks = request.inspection.optimizable_networks
        # Requests may have been inspected by a different FixtureBackend instance.
        # Bind the explicit fixture profiles to this immutable request at run time.
        self._profile_index_by_network_id = {
            network.network_id: index % len(self._LOAD_PROFILES)
            for index, network in enumerate(networks)
        }
        total = len(networks)
        progress_callback(
            ProgressUpdate(
                ProgressPhase.PREPARING,
                "准备全网段不可变批量请求",
                overall_completed=0,
                overall_total=total,
            )
        )
        for index, network in enumerate(networks, start=1):
            if cancellation_token.is_cancelled:
                current = NetworkBatchResult(
                    network_id=network.network_id,
                    network_name=network.network_name,
                    display_name=network.display_name,
                    source_file=network.source_file,
                    status=NetworkRunStatus.CANCELLED,
                    weight_mode=self._network_weight(network, request),
                    mode=request.mode,
                    error="用户在网段开始前取消了批量任务",
                    logs=("当前网段未开始。",),
                )
                network_results.append(current)
                self._write_non_success(output_directory, current)
                self._cancel_batch(
                    request,
                    output_directory,
                    network_results,
                    index + 1,
                    started,
                )
            if self._matches_network(network, self._skip_networks):
                item = NetworkBatchResult(
                    network_id=network.network_id,
                    network_name=network.network_name,
                    display_name=network.display_name,
                    source_file=network.source_file,
                    status=NetworkRunStatus.SKIPPED,
                    weight_mode=self._network_weight(network, request),
                    mode=request.mode,
                    error="FixtureBackend 配置为跳过该网段",
                    logs=("网段未开始优化。",),
                )
                network_results.append(item)
                self._write_non_success(output_directory, item)
                self._emit_network_finished(progress_callback, item, index, total, started)
                continue
            if self._matches_network(network, self._fail_networks):
                item = NetworkBatchResult(
                    network_id=network.network_id,
                    network_name=network.network_name,
                    display_name=network.display_name,
                    source_file=network.source_file,
                    status=NetworkRunStatus.FAILED,
                    weight_mode=self._network_weight(network, request),
                    mode=request.mode,
                    error=f"FixtureBackend 模拟网段 {network.network_name} 优化失败",
                    logs=("已记录错误并继续后续网段。",),
                )
                network_results.append(item)
                self._write_non_success(output_directory, item)
                self._emit_network_finished(progress_callback, item, index, total, started)
                continue
            try:
                result = self._optimize_network(
                    request,
                    network,
                    output_directory,
                    progress_callback,
                    cancellation_token,
                    index,
                    total,
                    started,
                )
            except OptimizationCancelled:
                current = NetworkBatchResult(
                    network_id=network.network_id,
                    network_name=network.network_name,
                    display_name=network.display_name,
                    source_file=network.source_file,
                    status=NetworkRunStatus.CANCELLED,
                    weight_mode=self._network_weight(network, request),
                    mode=request.mode,
                    error="用户取消了当前网段",
                    logs=("当前网段已在安全检查点停止。",),
                )
                network_results.append(current)
                self._write_non_success(output_directory, current)
                self._cancel_batch(
                    request,
                    output_directory,
                    network_results,
                    index + 1,
                    started,
                )
            item = NetworkBatchResult(
                network_id=network.network_id,
                network_name=network.network_name,
                display_name=network.display_name,
                source_file=network.source_file,
                status=NetworkRunStatus.SUCCEEDED,
                weight_mode=self._network_weight(network, request),
                mode=request.mode,
                result=result,
                warnings=result.warnings,
                logs=result.logs,
            )
            network_results.append(item)
            self._emit_network_finished(progress_callback, item, index, total, started)
        batch = self._batch_result(
            request,
            output_directory,
            tuple(network_results),
            perf_counter() - started,
            cancelled=False,
        )
        self._write_batch_outputs(batch)
        progress_callback(
            ProgressUpdate(
                ProgressPhase.FINALIZING,
                "全网段批量优化完成",
                elapsed_seconds=batch.elapsed_seconds,
                overall_completed=total,
                overall_total=total,
            )
        )
        return batch

    def _optimize_network(
        self,
        request: GuiBatchOptimizationRequest,
        network: NetworkSummary,
        output_directory: Path,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
        network_index: int,
        network_total: int,
        batch_started: float,
    ) -> GuiOptimizationResult:
        profile = self._profile_index_by_network_id[network.network_id]
        attempts = self._attempt_count(request, profile)
        for attempt in range(1, attempts + 1):
            self._tick(cancellation_token)
            progress_callback(
                ProgressUpdate(
                    ProgressPhase.NETWORK_RUNNING,
                    f"{network.network_name} attempt {attempt}/{attempts}",
                    elapsed_seconds=perf_counter() - batch_started,
                    network_id=network.network_id,
                    network_name=network.network_name,
                    network_index=network_index,
                    network_total=network_total,
                    attempt=attempt,
                    total_attempts=attempts,
                    overall_completed=network_index - 1,
                    overall_total=network_total,
                )
            )
        before, after = self._metrics(request.mode, profile)
        steady_before, steady_after, startup_before, startup_after = self._load_curves(profile)
        (
            steady_counts_before,
            steady_counts_after,
            startup_counts_before,
            startup_counts_after,
        ) = self._load_counts(profile)
        result = GuiOptimizationResult(
            network_id=network.network_id,
            network_name=network.network_name,
            display_name=network.display_name,
            source_file=network.source_file,
            weight_mode=self._network_weight(network, request),
            mode=request.mode,
            original_metrics=before,
            optimized_metrics=after,
            assignments=self._assignments(network, profile),
            actual_attempts=attempts,
            stop_reason=(
                "fixed_limit"
                if request.restart.mode is RestartMode.FIXED
                else ("stable_plateau" if profile % 2 else "patience_exhausted")
            ),
            elapsed_seconds=round(0.012 * attempts + profile / 1000, 3),
            warnings=self._network_warnings(
                request, self._network_weight(network, request)
            ),
            steady_loads_before=steady_before,
            steady_loads_after=steady_after,
            startup_loads_before=startup_before,
            startup_loads_after=startup_after,
            steady_counts_before=steady_counts_before,
            steady_counts_after=steady_counts_after,
            startup_counts_before=startup_counts_before,
            startup_counts_after=startup_counts_after,
            logs=(
                f"开始网段 {network.network_name}（Mock 后端）",
                f"network_id={network.network_id}",
                f"来源 DBC：{network.source_file}",
                f"完成 {attempts} attempts",
                "生成网段用户产物",
            ),
            output_directory=create_output_layout(output_directory).results
            / short_output_stem(f"{network.display_name}_{network.network_id[-8:]}"),
            frame_protocol=network.frame_protocol,
            classic_weight_model=network.classic_weight_model,
        )
        return self._write_success_outputs(result, output_directory)

    def _write_success_outputs(
        self, result: GuiOptimizationResult, batch_output: Path
    ) -> GuiOptimizationResult:
        assert result.output_directory is not None
        layout = create_output_layout(batch_output)
        result.output_directory.mkdir(parents=True, exist_ok=True)
        offsets = export_assignments_csv(result, result.output_directory / "offsets.csv")
        stem = short_output_stem(result.display_name)
        load_plot = write_load_curve_png(result, layout.plots / f"{stem}_load_curve.png")
        heatmap = write_load_heatmap_png(result, layout.plots / f"{stem}_heatmap.png")
        log_path = write_network_log(
            NetworkBatchResult(
                result.network_id,
                result.network_name,
                result.display_name,
                result.source_file,
                NetworkRunStatus.SUCCEEDED,
                result.weight_mode,
                result.mode,
                result=result,
                warnings=result.warnings,
                logs=result.logs,
            ),
            layout.logs / f"{stem}.log",
        )
        return replace(result, exported_files=(offsets, load_plot, heatmap, log_path))

    def _cancel_batch(
        self,
        request: GuiBatchOptimizationRequest,
        output_directory: Path,
        completed: list[NetworkBatchResult],
        next_network_index: int,
        started: float,
    ) -> None:
        networks = request.inspection.optimizable_networks
        for network in networks[next_network_index - 1 :]:
            skipped = NetworkBatchResult(
                network_id=network.network_id,
                network_name=network.network_name,
                display_name=network.display_name,
                source_file=network.source_file,
                status=NetworkRunStatus.SKIPPED,
                weight_mode=self._network_weight(network, request),
                mode=request.mode,
                error="批量任务已取消，网段未开始",
                logs=("因用户取消而未运行。",),
            )
            completed.append(skipped)
            self._write_non_success(output_directory, skipped)
        batch = self._batch_result(
            request,
            output_directory,
            tuple(completed),
            perf_counter() - started,
            cancelled=True,
        )
        self._write_batch_outputs(batch)
        raise BatchOptimizationCancelled(batch)

    def _batch_result(
        self,
        request: GuiBatchOptimizationRequest,
        output_directory: Path,
        network_results: tuple[NetworkBatchResult, ...],
        elapsed_seconds: float,
        *,
        cancelled: bool,
    ) -> BatchOptimizationResult:
        errors = tuple(
            item.error
            for item in network_results
            if item.status is NetworkRunStatus.FAILED and item.error is not None
        )
        warnings = (
            (self._extra_warning,) if self._extra_warning else ()
        ) + ("当前使用 FixtureBackend，结果不可用于工程交付。",)
        return BatchOptimizationResult(
            project_name=request.inspection.session.project_name,
            import_session_directory=request.inspection.session.session_directory,
            import_manifest_path=request.inspection.session.manifest_path,
            output_directory=output_directory,
            network_results=network_results,
            elapsed_seconds=elapsed_seconds,
            warnings=warnings,
            errors=errors,
            cancelled=cancelled,
        )

    @staticmethod
    def _write_non_success(output_directory: Path, item: NetworkBatchResult) -> None:
        layout = create_output_layout(output_directory)
        write_network_log(
            item,
            layout.logs / f"{short_output_stem(item.display_name)}.log",
        )

    @staticmethod
    def _write_batch_outputs(batch: BatchOptimizationResult) -> None:
        layout = create_output_layout(batch.output_directory)
        export_batch_summary_csv(batch, layout.results / "networks_summary.csv")
        for item in batch.network_results:
            write_network_log(
                item,
                layout.logs / f"{short_output_stem(item.display_name)}.log",
            )
        write_batch_log(batch, layout.logs / "batch.log")

    @staticmethod
    def _emit_network_finished(
        callback: ProgressCallback,
        item: NetworkBatchResult,
        index: int,
        total: int,
        started: float,
    ) -> None:
        callback(
            ProgressUpdate(
                ProgressPhase.NETWORK_RUNNING,
                f"网段 {item.network_name}：{item.status.value}",
                elapsed_seconds=perf_counter() - started,
                network_id=item.network_id,
                network_name=item.network_name,
                network_index=index,
                network_total=total,
                network_status=item.status,
                overall_completed=index,
                overall_total=total,
            )
        )

    def _tick(self, cancellation_token: CancellationToken) -> None:
        cancellation_token.raise_if_cancelled()
        if self._delay_seconds:
            sleep(self._delay_seconds)
        cancellation_token.raise_if_cancelled()

    @staticmethod
    def _discover_sources(
        sources: tuple[Path, ...],
    ) -> tuple[list[tuple[Path, Path, str | None]], list[tuple[Path, str]]]:
        discovered: list[tuple[Path, Path, str | None]] = []
        invalid: list[tuple[Path, str]] = []
        for raw_source in sources:
            source = raw_source.expanduser().resolve(strict=False)
            if source.is_file():
                discovered.append((source, Path(source.name), None))
                continue
            if not source.is_dir():
                invalid.append((source, "路径不存在或不是普通文件/目录"))
                continue
            walk_errors: list[OSError] = []

            def onerror(error: OSError) -> None:
                walk_errors.append(error)

            root_label = FixtureBackend._safe_name(source.name or "root")
            for directory, directories, filenames in os.walk(source, onerror=onerror):
                directories.sort(key=str.casefold)
                filenames.sort(key=str.casefold)
                directory_path = Path(directory)
                for filename in filenames:
                    path = directory_path / filename
                    discovered.append((path, path.relative_to(source), root_label))
            invalid.extend(
                (Path(error.filename or source).resolve(strict=False), f"目录无法读取：{error}")
                for error in walk_errors
            )
        return discovered, invalid

    @classmethod
    def _classify(cls, path: Path) -> InputKind:
        return cls._EXTENSIONS.get(path.suffix.casefold(), InputKind.UNRECOGNIZED)

    @classmethod
    def _destination_relative(
        cls, kind: InputKind, relative: Path, root_label: str | None
    ) -> Path:
        category = cls._CATEGORY_DIRECTORIES[kind]
        return Path(category, root_label, relative) if root_label else Path(category, relative)

    @staticmethod
    def _conflict_name(relative: Path, digest: str) -> Path:
        return relative.with_name(f"{relative.stem}__{digest[:8]}{relative.suffix}")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._")
        return cleaned or "project"

    @classmethod
    def _project_name(
        cls,
        discovered: list[tuple[Path, Path, str | None]],
        sources: tuple[Path, ...],
    ) -> str:
        dbc = next((path for path, _, _ in discovered if path.suffix.casefold() == ".dbc"), None)
        if dbc is not None:
            return cls._safe_name(dbc.stem)
        first = sources[0]
        return cls._safe_name(first.stem if first.suffix else first.name)

    @classmethod
    def _session_id(cls, project_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{timestamp}_{cls._safe_name(project_name)}"

    @staticmethod
    def _unique_directory(root: Path, name: str) -> Path:
        root = root.resolve()
        candidate = root / name
        suffix = 2
        while candidate.exists():
            candidate = root / f"{name}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _write_manifest(session: ImportSession) -> None:
        data = {
            "session_id": session.session_id,
            "project_name": session.project_name,
            "created_at": session.created_at,
            "workspace_root": str(session.workspace_root),
            "session_directory": str(session.session_directory),
            "records": [
                {
                    "original_absolute_path": str(record.original_path),
                    "workspace_relative_path": (
                        record.workspace_relative_path.as_posix()
                        if record.workspace_relative_path is not None
                        else None
                    ),
                    "detected_type": record.kind.value,
                    "status": record.status.value,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                    "imported_at": record.imported_at,
                    "used_by_parser": record.used_by_parser,
                    "note": record.note,
                }
                for record in session.records
            ],
        }
        session.manifest_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def _networks_from_dbc(
        cls, records: tuple[ImportRecord, ...], weight_modes: tuple[WeightMode, ...]
    ) -> tuple[NetworkSummary, ...]:
        networks: list[NetworkSummary] = []
        display_counts: dict[str, int] = {}
        for record in sorted(records, key=lambda item: str(item.workspace_relative_path).casefold()):
            assert record.workspace_relative_path is not None
            source_file = record.original_path.name
            network_name = cls._network_name_from_stem(record.original_path.stem)
            key = network_name.casefold()
            display_counts[key] = display_counts.get(key, 0) + 1
            ordinal = display_counts[key]
            display_name = network_name if ordinal == 1 else f"{network_name} ({ordinal})"
            identity_material = f"{source_file.casefold()}|{record.sha256 or ''}"
            network_id = f"net-{hashlib.sha256(identity_material.encode()).hexdigest()[:16]}"
            networks.append(
                NetworkSummary(
                    network_id=network_id,
                    network_name=network_name,
                    display_name=display_name,
                    source_file=source_file,
                    source_workspace_path=record.workspace_relative_path,
                    is_optimizable=True,
                    message_count=12,
                    available_weight_modes=weight_modes,
                )
            )
        return tuple(networks)

    @staticmethod
    def _network_name_from_stem(stem: str) -> str:
        """Extract a concise mock network name without pretending to parse DBC syntax."""

        matches: list[str] = re.findall(
            r"(?:^|[_\s-])([A-Z][A-Z0-9]{1,7})(?=\s+Message(?:\s|$))",
            stem,
        )
        if matches:
            return matches[-1]
        vcu_match = re.search(r"(?:^|_)VCU_([A-Z][A-Z0-9]{1,7})(?:_|\s|$)", stem)
        if vcu_match:
            return vcu_match.group(1)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,11}", stem):
            return stem
        tokens = re.findall(r"[A-Z][A-Z0-9]{1,5}", stem)
        return tokens[-1] if tokens else FixtureBackend._safe_name(stem)

    def _inspection_warnings(self, session: ImportSession) -> tuple[str, ...]:
        warnings = ["当前使用 FixtureBackend，文件仅按扩展名分类。"]
        if any(record.note == DEFAULT_CONFIG_NOTE for record in session.records):
            warnings.append(DEFAULT_CONFIG_NOTE)
        counts = {
            status: sum(record.status is status for record in session.records)
            for status in ImportRecordStatus
        }
        unrecognized = sum(record.kind is InputKind.UNRECOGNIZED for record in session.records)
        if unrecognized:
            warnings.append(f"有 {unrecognized} 个文件无法识别，已保留在工作区。")
        if counts[ImportRecordStatus.DUPLICATE]:
            warnings.append(f"已去重 {counts[ImportRecordStatus.DUPLICATE]} 个同内容文件。")
        if counts[ImportRecordStatus.CONFLICT_RENAMED]:
            warnings.append(
                f"已稳定重命名 {counts[ImportRecordStatus.CONFLICT_RENAMED]} 个冲突文件。"
            )
        if counts[ImportRecordStatus.INVALID]:
            warnings.append(f"有 {counts[ImportRecordStatus.INVALID]} 个输入无效或无法读取。")
        if self._extra_warning:
            warnings.append(self._extra_warning)
        return tuple(warnings)

    @staticmethod
    def _network_weight(
        network: NetworkSummary, request: GuiBatchOptimizationRequest
    ) -> WeightMode:
        if network.frame_protocol is FrameProtocol.CLASSIC_CAN:
            return request.classic_can_weight
        return request.can_fd_weight

    def _network_warnings(
        self, request: GuiBatchOptimizationRequest, weight_mode: WeightMode
    ) -> tuple[str, ...]:
        warnings = ["FixtureBackend 结果不可用于工程交付。"]
        if weight_mode is WeightMode.PAYLOAD_BYTES:
            warnings.append("Payload 权重不代表物理总线占用时间。")
        if request.enable_triple_search:
            warnings.append("已模拟启用高质量离线 3-opt；未执行真实核心搜索。")
        if self._extra_warning:
            warnings.append(self._extra_warning)
        return tuple(warnings)

    @staticmethod
    def _metrics(
        mode: OptimizationMode, profile: int
    ) -> tuple[ObjectiveMetrics, ObjectiveMetrics]:
        original_zss = (700, 680, 660)[profile]
        improvement = {
            OptimizationMode.PEAK: (80, 70, 60),
            OptimizationMode.BALANCED: (65, 55, 45),
            OptimizationMode.VARIANCE: (50, 40, 30),
        }[mode][profile]
        original_qss = (11_000_000, 10_500_000, 10_000_000)[profile]
        before = ObjectiveMetrics(
            original_zss,
            original_qss,
            (82.0, 76.0, 70.0)[profile],
            original_zss - 25,
            original_qss - 1_100_000,
            profile + 1,
            (180, 140, 100)[profile],
        )
        after = ObjectiveMetrics(
            original_zss - improvement,
            original_qss - (1_500_000, 1_300_000, 1_100_000)[profile],
            (42.0, 38.0, 34.0)[profile],
            original_zss - improvement - 12,
            before.qst - 850_000,
            0,
            0,
        )
        return before, after

    @staticmethod
    def _assignments(
        network: NetworkSummary, profile: int
    ) -> tuple[OffsetAssignmentRow, ...]:
        prefix = FixtureBackend._safe_name(network.network_name)
        cycles = (10_000, 20_000, 50_000, 100_000)
        original_offsets = (15_000, 20_000, 25_000, 30_000, 35_000, 40_000)
        optimized_offsets = (
            (35_000, 45_000, 55_000, 65_000, 75_000, 85_000),
            (40_000, 50_000, 60_000, 70_000, 80_000, 90_000),
            (45_000, 55_000, 65_000, 75_000, 85_000, 95_000),
        )[profile]
        return tuple(
            OffsetAssignmentRow(
                f"{prefix}_Fixture_{index + 1:02d}",
                0x300 + profile * 0x20 + index,
                cycles[index % len(cycles)],
                original_offsets[index % len(original_offsets)],
                optimized_offsets[index % len(optimized_offsets)],
            )
            for index in range(12)
        )

    @staticmethod
    def _matches_network(network: NetworkSummary, configured: frozenset[str]) -> bool:
        return bool(
            {network.network_id, network.network_name, network.display_name} & configured
        )

    @staticmethod
    def _attempt_count(request: GuiBatchOptimizationRequest, profile: int) -> int:
        if request.restart.mode is RestartMode.FIXED:
            return request.restart.fixed_attempts
        span = request.restart.max_attempts - request.restart.min_attempts + 1
        return request.restart.min_attempts + profile % min(span, 3)

    @staticmethod
    def _load_curves(
        profile: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        before, after, startup_before, startup_after = FixtureBackend._LOAD_PROFILES[profile]
        return (
            tuple(before[index % len(before)] for index in range(100)),
            tuple(after[index % len(after)] for index in range(100)),
            tuple(value for value in startup_before),
            tuple(value for value in startup_after),
        )

    @staticmethod
    def _load_counts(
        profile: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        before_pattern = (0, 1, 2, 3, 5, 2, 1, 4, 0, 2)
        after_pattern = (0, 1, 2, 2, 3, 2, 1, 2, 0, 1)
        return (
            tuple(before_pattern[(index + profile) % len(before_pattern)] for index in range(100)),
            tuple(after_pattern[(index + profile) % len(after_pattern)] for index in range(100)),
            tuple(before_pattern[(index + profile) % len(before_pattern)] for index in range(8)),
            tuple(after_pattern[(index + profile) % len(after_pattern)] for index in range(8)),
        )
