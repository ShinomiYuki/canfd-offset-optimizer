from __future__ import annotations

import json
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    ImportRecordStatus,
    InputKind,
)
from canfd_offset_optimizer.gui.mock_backend import MockBackend


def test_recursive_import_classifies_copies_and_preserves_originals(
    backend: MockBackend, source_project: Path
) -> None:
    before = {
        path.relative_to(source_project): path.read_bytes()
        for path in source_project.rglob("*")
        if path.is_file()
    }
    progress = []
    session = backend.import_inputs((source_project,), progress.append, CancellationToken())

    assert session.session_directory.parent.name == "user_input"
    assert session.manifest_path.is_file()
    assert {record.kind for record in session.records} == {
        InputKind.DBC,
        InputKind.CONFIG,
        InputKind.ARXML,
        InputKind.UNRECOGNIZED,
    }
    for record in session.records:
        assert record.original_path.is_absolute()
        assert record.workspace_relative_path is not None
        assert (session.session_directory / record.workspace_relative_path).is_file()
        assert record.sha256 and len(record.sha256) == 64
    after = {
        path.relative_to(source_project): path.read_bytes()
        for path in source_project.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert progress[-1].overall_completed == progress[-1].overall_total

    manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_id"] == session.session_id
    assert len(manifest["records"]) == len(session.records)
    assert all("original_absolute_path" in item for item in manifest["records"])


def test_one_import_accepts_multiple_directories_and_files(
    backend: MockBackend, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "PT.dbc").write_text("PT", encoding="utf-8")
    (second / "DA.dbc").write_text("DA", encoding="utf-8")
    config = tmp_path / "project.yaml"
    config.write_text("project: mixed", encoding="utf-8")

    session = backend.import_inputs(
        (first, second, config), lambda _update: None, CancellationToken()
    )
    paths = {record.workspace_relative_path.as_posix() for record in session.records}
    assert "dbc/first/PT.dbc" in paths
    assert "dbc/second/DA.dbc" in paths
    assert "config/project.yaml" in paths


def test_invalid_and_unrecognized_inputs_are_retained_and_reported(
    backend: MockBackend, tmp_path: Path
) -> None:
    unknown = tmp_path / "input.bin"
    unknown.write_bytes(b"data")
    missing = tmp_path / "missing.dbc"
    session = backend.import_inputs(
        (unknown, missing), lambda _update: None, CancellationToken()
    )
    assert any(record.kind is InputKind.UNRECOGNIZED for record in session.records)
    invalid = next(record for record in session.records if record.kind is InputKind.INVALID)
    assert invalid.status is ImportRecordStatus.INVALID
    assert invalid.workspace_relative_path is None
    inspection = backend.inspect_workspace(
        session, lambda _update: None, CancellationToken()
    )
    assert set(inspection.missing_required) == {InputKind.DBC, InputKind.CONFIG}
    assert not inspection.can_optimize
    assert any("无法识别" in warning for warning in inspection.warnings)


def test_same_content_is_deduplicated_and_name_conflict_is_stably_renamed(
    backend: MockBackend, tmp_path: Path
) -> None:
    first = tmp_path / "a" / "same.dbc"
    duplicate = tmp_path / "b" / "same.dbc"
    conflict = tmp_path / "c" / "same.dbc"
    for path in (first, duplicate, conflict):
        path.parent.mkdir()
    first.write_text("same", encoding="utf-8")
    duplicate.write_text("same", encoding="utf-8")
    conflict.write_text("different", encoding="utf-8")
    session = backend.import_inputs(
        (first, duplicate, conflict), lambda _update: None, CancellationToken()
    )
    statuses = [record.status for record in session.records]
    assert statuses.count(ImportRecordStatus.IMPORTED) == 1
    assert statuses.count(ImportRecordStatus.DUPLICATE) == 1
    assert statuses.count(ImportRecordStatus.CONFLICT_RENAMED) == 1
    renamed = next(
        record
        for record in session.records
        if record.status is ImportRecordStatus.CONFLICT_RENAMED
    )
    assert renamed.workspace_relative_path is not None
    assert "__" in renamed.workspace_relative_path.stem


def test_reimport_creates_independent_history_session(
    backend: MockBackend, source_project: Path
) -> None:
    first = backend.import_inputs(
        (source_project,), lambda _update: None, CancellationToken()
    )
    second = backend.import_inputs(
        (source_project,), lambda _update: None, CancellationToken()
    )
    assert first.session_id != second.session_id
    assert first.session_directory != second.session_directory
    assert first.session_directory.is_dir()
    assert second.session_directory.is_dir()
    first_inspection = backend.inspect_workspace(
        first, lambda _update: None, CancellationToken()
    )
    second_inspection = backend.inspect_workspace(
        second, lambda _update: None, CancellationToken()
    )
    assert [network.network_id for network in first_inspection.networks] == [
        network.network_id for network in second_inspection.networks
    ]
    file_session = backend.import_inputs(
        tuple(path for path in source_project.rglob("*") if path.is_file()),
        lambda _update: None,
        CancellationToken(),
    )
    file_inspection = backend.inspect_workspace(
        file_session, lambda _update: None, CancellationToken()
    )
    assert {network.network_id for network in file_inspection.networks} == {
        network.network_id for network in first_inspection.networks
    }
