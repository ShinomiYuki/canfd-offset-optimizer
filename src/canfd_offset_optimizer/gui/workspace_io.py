"""Filesystem-only import support shared by GUI backends.

This module copies user-selected inputs and writes an auditable manifest.  It
does not parse CAN data, decide optimization eligibility, or create results.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .contracts import (
    BackendError,
    CancellationToken,
    ImportRecord,
    ImportRecordStatus,
    ImportSession,
    InputKind,
    ProgressCallback,
    ProgressPhase,
    ProgressUpdate,
)


DEFAULT_PROJECT_CONFIG_PATH = Path(__file__).with_name("default_project.yaml")
DEFAULT_CONFIG_NOTE = "用户未提供项目配置；已使用内置默认 project.yaml"


def add_default_project_config(
    session_directory: Path,
    records: list[ImportRecord],
    imported_at: str,
    default_config_path: Path = DEFAULT_PROJECT_CONFIG_PATH,
) -> ImportRecord | None:
    """Copy the bundled default when no usable YAML/YML was imported."""

    if any(
        record.kind is InputKind.CONFIG
        and record.workspace_relative_path is not None
        and record.status is not ImportRecordStatus.INVALID
        for record in records
    ):
        return None
    source = default_config_path.resolve(strict=False)
    if not source.is_file():
        raise BackendError(f"内置默认项目配置不存在：{source}")
    content = source.read_bytes()
    relative = Path("config/project.yaml")
    destination = session_directory / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    record = ImportRecord(
        source.resolve(),
        relative,
        InputKind.CONFIG,
        ImportRecordStatus.IMPORTED,
        len(content),
        hashlib.sha256(content).hexdigest(),
        imported_at,
        note=DEFAULT_CONFIG_NOTE,
    )
    records.append(record)
    return record


class WorkspaceImporter:
    """Copy inputs into one immutable ``user_input`` session."""

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
        workspace_root: Path | None = None,
        *,
        default_config_path: Path = DEFAULT_PROJECT_CONFIG_PATH,
    ) -> None:
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._default_config_path = default_config_path

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
        session_directory = self._unique_directory(self._workspace_root / "user_input", session_id)
        session_directory.mkdir(parents=True, exist_ok=False)
        records = [
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
            for path, note in invalid_sources
        ]
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
                            source.resolve(), duplicate_path, kind,
                            ImportRecordStatus.DUPLICATE, size, digest, imported_at,
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
                        source.resolve(), destination_relative, kind, status, size, digest,
                        imported_at,
                        note=("同名不同内容文件已使用 SHA-256 后缀重命名"
                              if status is ImportRecordStatus.CONFLICT_RENAMED else ""),
                    )
                )
            except (OSError, PermissionError) as exc:
                records.append(
                    ImportRecord(
                        source.resolve(strict=False), None, InputKind.INVALID,
                        ImportRecordStatus.INVALID, None, None, imported_at,
                        note=f"无法读取或复制：{exc}",
                    )
                )
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
            session_id, project_name, self._workspace_root, session_directory,
            manifest_path, imported_at, tuple(records),
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
            root_label = WorkspaceImporter._safe_name(source.name or "root")
            for directory, directories, filenames in os.walk(
                source, onerror=walk_errors.append
            ):
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
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{cls._safe_name(project_name)}"

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
                        if record.workspace_relative_path is not None else None
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
