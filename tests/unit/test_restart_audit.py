"""Restart policy, complete records, hashes, and append-only audit tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from canfd_offset_optimizer.config import (
    ObjectiveConfig,
    OptimizationConfig,
    RestartPolicy,
    load_project_config,
)
from canfd_offset_optimizer.exceptions import ConfigurationError
from canfd_offset_optimizer.models import (
    CanMessage,
    ObjectiveMode,
    RestartMode,
    hash_offset_assignments,
)
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.reporting.restart_writer import (
    AppendOnlyRestartWriter,
    restart_record_dict,
)
from canfd_offset_optimizer.timeline.slot_map import (
    SlotMap,
    build_windows,
    precompute_slot_map,
)


def _fixture() -> tuple[tuple[CanMessage, ...], SlotMap]:
    offsets = (5_000, 10_000, 15_000)
    messages = (
        CanMessage("A", 1, False, 10_000, 100, offsets, 5_000, "ECU", 0),
        CanMessage("B", 2, False, 20_000, 200, offsets, 10_000, "ECU", 1),
    )
    startup, steady, _ = build_windows(messages, 5_000, 20_000)
    return messages, precompute_slot_map(messages, startup, steady)


def test_restart_policy_legacy_adapter_and_conflict(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(
        "optimization:\n  random_restarts: 2\n", encoding="utf-8"
    )
    policy = load_project_config(path).optimization.restart_policy
    assert policy.mode is RestartMode.FIXED
    assert policy.total_attempts == 3
    assert policy.legacy_additional_restarts == 2
    path.write_text(
        "optimization:\n  random_restarts: 2\n  restart_policy:\n"
        "    mode: fixed\n    total_attempts: 3\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="conflicts"):
        load_project_config(path)
    path.write_text(
        "optimization:\n  restart_policy:\n    mode: fixed\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="requires total_attempts"):
        load_project_config(path)
    path.write_text("{}\n", encoding="utf-8")
    assert (
        load_project_config(path).optimization.restart_policy.source_kind
        == "default"
    )


def test_fixed_and_adaptive_attempt_counts_are_exact() -> None:
    messages, slot_map = _fixture()
    fixed = run_gcls(
        messages,
        slot_map,
        OptimizationConfig(restart_policy=RestartPolicy.fixed(3)),
        objective_config=ObjectiveConfig(ObjectiveMode.PEAK),
    )
    assert len(fixed.restart_records) == 3
    assert fixed.restart_execution.actual_attempts == 3
    assert fixed.restart_execution.stop_reason == "fixed_limit"
    adaptive_policy = RestartPolicy(
        mode=RestartMode.ADAPTIVE,
        min_attempts=20,
        check_interval=10,
        patience_attempts=20,
        max_attempts=80,
    )
    adaptive = run_gcls(
        messages,
        slot_map,
        OptimizationConfig(restart_policy=adaptive_policy),
        objective_config=ObjectiveConfig(ObjectiveMode.PEAK),
    )
    assert adaptive.restart_execution.actual_attempts in range(20, 81, 10)
    assert adaptive.restart_execution.stop_reason in {
        "patience_exhausted",
        "max_attempts_reached_unverified",
    }


def test_restart_records_are_complete_reproducible_except_runtime() -> None:
    messages, slot_map = _fixture()
    config = OptimizationConfig(restart_policy=RestartPolicy.fixed(3))
    first = run_gcls(messages, slot_map, config, seed=7)
    second = run_gcls(
        tuple(reversed(messages)), slot_map, config, seed=7
    )
    assert first.restart_records == second.restart_records
    assert all(len(record.assignments) == len(messages) for record in first.restart_records)
    assert all(
        record.assignment_hash == hash_offset_assignments(record.assignments)
        for record in first.restart_records
    )


def test_balanced_and_variance_reuse_peak_actual_seed_sequence() -> None:
    messages, slot_map = _fixture()
    policy = RestartPolicy(
        mode=RestartMode.ADAPTIVE,
        min_attempts=2,
        check_interval=1,
        patience_attempts=2,
        max_attempts=5,
    )
    config = OptimizationConfig(restart_policy=policy)
    peak = run_gcls(
        messages,
        slot_map,
        config,
        seed=11,
        objective_config=ObjectiveConfig(ObjectiveMode.PEAK),
    )
    balanced = run_gcls(
        messages,
        slot_map,
        config,
        seed=11,
        objective_config=ObjectiveConfig(ObjectiveMode.BALANCED),
        peak_reference_result=peak,
    )
    variance = run_gcls(
        messages,
        slot_map,
        config,
        seed=11,
        objective_config=ObjectiveConfig(ObjectiveMode.VARIANCE),
        peak_reference_result=peak,
    )
    expected = [record.seed for record in peak.restart_records]
    assert [record.seed for record in balanced.restart_records] == expected
    assert [record.seed for record in variance.restart_records] == expected
    assert balanced.restart_execution.actual_attempts == len(expected)
    assert variance.restart_execution.actual_attempts == len(expected)


def test_append_only_jsonl_resume_rejects_duplicates_and_mismatches(
    tmp_path: Path,
) -> None:
    messages, slot_map = _fixture()
    result = run_gcls(
        messages,
        slot_map,
        OptimizationConfig(restart_policy=RestartPolicy.fixed(1)),
        seed=3,
    )
    path = tmp_path / "records.jsonl"
    writer = AppendOnlyRestartWriter(path, "exp", "hash", "config")
    row = restart_record_dict(
        result.restart_records[0],
        experiment_id="exp",
        input_hash="hash",
        configuration_hash_value="config",
        network="TEST",
        phase="peak",
    )
    writer.append(row)
    assert json.loads(path.read_text(encoding="utf-8"))["assignments"]
    with pytest.raises(FileExistsError):
        writer.existing_keys()
    with pytest.raises(ValueError, match="configuration hash"):
        replace(
            writer, resume=True, configuration_hash_value="different"
        ).existing_keys()
    resumed = replace(writer, resume=True)
    assert resumed.existing_keys() == {("peak", 0, 0)}

    corrupted = dict(row)
    corrupted["assignment_hash"] = "0" * 64
    with pytest.raises(ValueError, match="assignment_hash"):
        AppendOnlyRestartWriter(
            tmp_path / "corrupted.jsonl", "exp", "hash", "config"
        ).append(corrupted)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        resumed.existing_keys()
