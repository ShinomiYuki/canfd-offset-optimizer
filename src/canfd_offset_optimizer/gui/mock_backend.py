"""Deterministic workspace backend used until a public core service exists."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from math import sin
from pathlib import Path
from time import perf_counter, sleep
from typing import Iterable

from .contracts import (
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
    OptimizationMode,
    ProgressCallback,
    ProgressPhase,
    ProgressUpdate,
    RestartMode,
    WeightMode,
    WorkspaceInspection,
)
from .formatting import (
    export_assignments_csv,
    export_batch_summary_csv,
    export_batch_summary_json,
    export_network_summary_json,
)


class MockBackend:
    """Copy real files, then simulate all-network inspection and optimization."""

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
            raise BackendError("MockBackend 模拟工程整体解析失败")

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

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult:
        if self._fail_all_optimization:
            raise BackendError("MockBackend 模拟工程级批量优化失败")
        started = perf_counter()
        output_id = self._session_id(request.inspection.session.project_name)
        output_directory = self._unique_directory(request.output_root, output_id)
        output_directory.mkdir(parents=True, exist_ok=False)
        network_results: list[NetworkBatchResult] = []
        networks = request.inspection.optimizable_networks
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
                    weight_mode=request.weight_mode,
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
                    weight_mode=request.weight_mode,
                    mode=request.mode,
                    error="MockBackend 配置为跳过该网段",
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
                    weight_mode=request.weight_mode,
                    mode=request.mode,
                    error=f"MockBackend 模拟网段 {network.network_name} 优化失败",
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
                    weight_mode=request.weight_mode,
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
                weight_mode=request.weight_mode,
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
        seed = self._stable_seed(network.network_id)
        attempts = self._attempt_count(request, seed)
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
        before, after = self._metrics(request.mode, seed)
        steady_before, steady_after, startup_before, startup_after = self._load_curves(seed)
        result = GuiOptimizationResult(
            network_id=network.network_id,
            network_name=network.network_name,
            display_name=network.display_name,
            source_file=network.source_file,
            weight_mode=request.weight_mode,
            mode=request.mode,
            original_metrics=before,
            optimized_metrics=after,
            assignments=self._assignments(network, seed),
            actual_attempts=attempts,
            stop_reason=(
                "fixed_limit"
                if request.restart.mode is RestartMode.FIXED
                else ("stable_plateau" if seed % 2 else "patience_exhausted")
            ),
            elapsed_seconds=round(0.012 * attempts + (seed % 37) / 1000, 3),
            warnings=self._network_warnings(request),
            steady_loads_before=steady_before,
            steady_loads_after=steady_after,
            startup_loads_before=startup_before,
            startup_loads_after=startup_after,
            logs=(
                f"开始网段 {network.network_name}（Mock 后端）",
                f"network_id={network.network_id}",
                f"来源 DBC：{network.source_file}",
                f"完成 {attempts} attempts",
                "生成网段用户产物",
            ),
            output_directory=output_directory
            / self._safe_name(f"{network.display_name}_{network.network_id[-8:]}"),
        )
        return self._write_success_outputs(result)

    def _write_success_outputs(self, result: GuiOptimizationResult) -> GuiOptimizationResult:
        assert result.output_directory is not None
        result.output_directory.mkdir(parents=True, exist_ok=True)
        offsets = export_assignments_csv(result, result.output_directory / "offsets.csv")
        metrics = export_network_summary_json(result, result.output_directory / "metrics.json")
        curves = result.output_directory / "load_curves.json"
        curves.write_text(
            json.dumps(
                {
                    "steady_before": result.steady_loads_before,
                    "steady_after": result.steady_loads_after,
                    "startup_before": result.startup_loads_before,
                    "startup_after": result.startup_loads_after,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log_path = result.output_directory / "run.log"
        log_path.write_text("\n".join(result.logs) + "\n", encoding="utf-8")
        completed = replace(
            result,
            exported_files=(offsets, metrics, curves, log_path),
        )
        export_network_summary_json(completed, metrics)
        return completed

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
                weight_mode=request.weight_mode,
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
        ) + ("当前使用 MockBackend，结果不可用于工程交付。",)
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
        directory = output_directory / MockBackend._safe_name(
            f"{item.display_name}_{item.network_id[-8:]}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "status.json").write_text(
            json.dumps(
                {
                    "network_id": item.network_id,
                    "network": item.network_name,
                    "display_name": item.display_name,
                    "source_file": item.source_file,
                    "status": item.status.value,
                    "error": item.error,
                    "warnings": item.warnings,
                    "logs": item.logs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_batch_outputs(batch: BatchOptimizationResult) -> None:
        export_batch_summary_csv(batch, batch.output_directory / "summary.csv")
        export_batch_summary_json(batch, batch.output_directory / "summary.json")

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

            root_label = MockBackend._safe_name(source.name or "root")
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
            seed = cls._stable_seed(network_id)
            networks.append(
                NetworkSummary(
                    network_id=network_id,
                    network_name=network_name,
                    display_name=display_name,
                    source_file=source_file,
                    source_workspace_path=record.workspace_relative_path,
                    is_optimizable=True,
                    message_count=20 + seed % 41,
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
        return tokens[-1] if tokens else MockBackend._safe_name(stem)

    def _inspection_warnings(self, session: ImportSession) -> tuple[str, ...]:
        warnings = ["当前使用 MockBackend，文件仅按扩展名分类。"]
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

    def _network_warnings(
        self, request: GuiBatchOptimizationRequest
    ) -> tuple[str, ...]:
        warnings = ["MockBackend 结果不可用于工程交付。"]
        if request.weight_mode is WeightMode.PAYLOAD_BYTES:
            warnings.append("Payload 权重不代表物理总线占用时间。")
        if request.enable_triple_search:
            warnings.append("已模拟启用高质量离线 3-opt；未执行真实核心搜索。")
        if self._extra_warning:
            warnings.append(self._extra_warning)
        return tuple(warnings)

    @staticmethod
    def _metrics(mode: OptimizationMode, seed: int) -> tuple[ObjectiveMetrics, ObjectiveMetrics]:
        original_zss = 620 + seed % 83
        improvement_base = {
            OptimizationMode.PEAK: 58,
            OptimizationMode.BALANCED: 39,
            OptimizationMode.VARIANCE: 27,
        }[mode]
        zss_improvement = improvement_base + (seed >> 8) % 31
        original_qss = 9_600_000 + (seed >> 13) % 1_900_000
        qss_reduction = 780_000 + (seed >> 23) % 1_150_000
        original_zst = original_zss - 18 - (seed >> 5) % 17
        optimized_zss = original_zss - zss_improvement
        optimized_zst = min(original_zst, optimized_zss + 8 + (seed >> 11) % 13)
        before = ObjectiveMetrics(
            original_zss,
            original_qss,
            round(68.0 + (seed >> 17) % 220 / 10, 3),
            original_zst,
            original_qss - 1_100_000 - (seed >> 7) % 350_000,
            1 + seed % 4,
            80 + (seed >> 9) % 121,
        )
        standard_base = {
            OptimizationMode.PEAK: 48.0,
            OptimizationMode.BALANCED: 35.0,
            OptimizationMode.VARIANCE: 29.0,
        }[mode]
        after = ObjectiveMetrics(
            optimized_zss,
            original_qss - qss_reduction,
            round(standard_base + (seed >> 29) % 170 / 10, 3),
            optimized_zst,
            max(0, before.qst - 720_000 - (seed >> 31) % 480_000),
            0,
            0,
        )
        return before, after

    @staticmethod
    def _assignments(
        network: NetworkSummary, seed: int
    ) -> tuple[OffsetAssignmentRow, ...]:
        prefix = MockBackend._safe_name(network.network_name)
        cycles = (10_000, 20_000, 50_000, 100_000)
        return tuple(
            OffsetAssignmentRow(
                f"{prefix}_Message_{index + 1:02d}",
                0x100 + (seed % 0x400) + index,
                cycles[index % len(cycles)],
                1_000 + (seed % 7 + index * 2) * 1_000,
                (
                    1_000 + (seed % 7 + index * 2) * 1_000
                    if index % 4 == 0
                    else 1_000 + ((seed >> 4) % 11 + index * 3) * 1_000
                ),
            )
            for index in range(12)
        )

    @staticmethod
    def _stable_seed(network_id: str) -> int:
        return int(hashlib.sha256(network_id.encode("utf-8")).hexdigest()[:16], 16)

    @staticmethod
    def _matches_network(network: NetworkSummary, configured: frozenset[str]) -> bool:
        return bool(
            {network.network_id, network.network_name, network.display_name} & configured
        )

    @staticmethod
    def _attempt_count(request: GuiBatchOptimizationRequest, seed: int) -> int:
        if request.restart.mode is RestartMode.FIXED:
            return request.restart.fixed_attempts
        span = request.restart.max_attempts - request.restart.min_attempts + 1
        return request.restart.min_attempts + seed % min(span, 9)

    @staticmethod
    def _load_curves(
        seed: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        phase = (seed % 360) / 180
        steady_base = 420 + seed % 47
        startup_base = 380 + (seed >> 7) % 53
        steady_before = tuple(
            steady_base + int((92 + seed % 31) * (1 + sin(slot * 0.72 + phase)))
            for slot in range(30)
        )
        steady_after = tuple(
            steady_base + 22 + int((37 + seed % 17) * (1 + sin(slot * 0.72 + phase + 0.35)))
            for slot in range(30)
        )
        startup_before = tuple(
            startup_base + int((82 + seed % 29) * (1 + sin(slot * 0.91 + phase)))
            for slot in range(18)
        )
        startup_after = tuple(
            startup_base + 18 + int((34 + seed % 13) * (1 + sin(slot * 0.91 + phase + 0.4)))
            for slot in range(18)
        )
        return steady_before, steady_after, startup_before, startup_after
