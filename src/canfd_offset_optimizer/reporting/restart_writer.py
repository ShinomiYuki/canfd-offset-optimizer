"""Restart attempt audit serialization and append-only JSONL support."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from ..config import ProjectConfig
from ..models import (
    ObjectiveValue,
    OffsetAssignment,
    RestartRecord,
    hash_offset_assignments,
)


def configuration_hash(config: ProjectConfig) -> str:
    """Return a stable SHA-256 for the normalized project configuration."""

    def encode(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        raise TypeError(f"unsupported configuration value: {type(value).__name__}")

    payload = json.dumps(
        asdict(config),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=encode,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def objective_dict(value: ObjectiveValue) -> dict[str, object]:
    """Return named raw metrics and the active lexicographic comparison key."""
    return {
        "mode": value.mode.value,
        "peak_budget_us": value.peak_budget_us,
        "priorities": list(value.priorities),
        "comparison_key": list(value.as_tuple()),
        "metrics": {
            "Nvio": value.violation_count,
            "Vvio": value.violation_excess,
            "Zss": value.steady_peak,
            "Qss": value.sum_square_load,
            "Zst": value.startup_peak,
            "Qst": value.startup_sum_square_load,
            "Kmax": value.max_release_count,
            "peak_budget_excess": value.peak_budget_excess,
        },
    }


def restart_record_dict(
    record: RestartRecord,
    *,
    experiment_id: str,
    input_hash: str,
    configuration_hash_value: str,
    network: str,
    batch_index: int = 0,
    phase: str = "gcls",
) -> dict[str, object]:
    """Build one self-contained append-only audit row."""
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "input_hash": input_hash,
        "configuration_hash": configuration_hash_value,
        "network": network,
        "phase": phase,
        "batch_index": batch_index,
        "restart_index": record.attempt_index,
        "attempt_kind": record.attempt_kind.value,
        "seed": record.seed,
        "objective": objective_dict(record.objective),
        "assignment_hash": record.assignment_hash,
        "assignments": [
            {
                "message_name": item.message_name,
                "CAN_ID": item.can_id,
                "Offset_us": item.offset_us,
                "definition_index": item.definition_index,
            }
            for item in record.assignments
        ],
        "runtime_seconds": record.elapsed_seconds,
        "evaluation_count": record.evaluation_count,
        "accepted_moves": record.accepted_moves,
    }


def _row_assignments(row: dict[str, object]) -> tuple[OffsetAssignment, ...]:
    raw = row.get("assignments")
    if not isinstance(raw, list):
        raise ValueError("restart row assignments must be a list")
    try:
        return tuple(
            OffsetAssignment(
                message_name=str(item["message_name"]),
                can_id=int(item["CAN_ID"]),
                offset_us=int(item["Offset_us"]),
                definition_index=int(item["definition_index"]),
            )
            for item in raw
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("restart row contains an invalid assignment") from exc


@dataclass(slots=True)
class AppendOnlyRestartWriter:
    """Append validated JSONL rows and optionally resume an identical experiment."""

    path: Path
    experiment_id: str
    input_hash: str
    configuration_hash_value: str
    resume: bool = False

    def existing_keys(self) -> set[tuple[str, int, int]]:
        """Validate existing lines and return phase/batch/restart keys."""
        if not self.path.exists():
            return set()
        if not self.resume:
            raise FileExistsError(
                f"restart audit already exists: {self.path}; use --resume"
            )
        keys: set[tuple[str, int, int]] = set()
        hash_assignments: dict[str, str] = {}
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid restart JSONL line {line_number}: {exc}"
                    ) from exc
                if (
                    row.get("experiment_id") != self.experiment_id
                    or row.get("input_hash") != self.input_hash
                    or row.get("configuration_hash")
                    != self.configuration_hash_value
                ):
                    raise ValueError(
                        "restart JSONL experiment/input/configuration hash mismatch"
                    )
                key = (
                    str(row["phase"]),
                    int(row["batch_index"]),
                    int(row["restart_index"]),
                )
                if key in keys:
                    raise ValueError(f"duplicate restart JSONL key: {key}")
                keys.add(key)
                assignments = _row_assignments(row)
                digest = str(row["assignment_hash"])
                actual_digest = hash_offset_assignments(assignments)
                if actual_digest != digest:
                    raise ValueError(
                        f"assignment hash mismatch on restart JSONL line {line_number}"
                    )
                canonical = json.dumps(
                    row["assignments"], ensure_ascii=False, sort_keys=True
                )
                previous = hash_assignments.setdefault(digest, canonical)
                if previous != canonical:
                    raise ValueError("assignment hash collision in restart JSONL")
        return keys

    def append(self, row: dict[str, object]) -> None:
        """Append and fsync one complete JSON object."""
        if row.get("experiment_id") != self.experiment_id:
            raise ValueError("restart row experiment_id mismatch")
        if row.get("input_hash") != self.input_hash:
            raise ValueError("restart row input_hash mismatch")
        if row.get("configuration_hash") != self.configuration_hash_value:
            raise ValueError("restart row configuration_hash mismatch")
        if hash_offset_assignments(_row_assignments(row)) != row.get(
            "assignment_hash"
        ):
            raise ValueError("restart row assignment_hash mismatch")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def write_restart_jsonl(
    path: Path,
    records: Iterable[RestartRecord],
    *,
    experiment_id: str,
    input_hash: str,
    configuration_hash_value: str,
    network: str,
    phase: str = "gcls",
) -> Path:
    """Atomically replace a standard one-run JSONL report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            row = restart_record_dict(
                record,
                experiment_id=experiment_id,
                input_hash=input_hash,
                configuration_hash_value=configuration_hash_value,
                network=network,
                phase=phase,
            )
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)
    return path


def validate_restart_record(record: RestartRecord) -> None:
    """Revalidate a record hash at reporting boundaries."""
    if hash_offset_assignments(record.assignments) != record.assignment_hash:
        raise ValueError("restart record changed after optimization")
