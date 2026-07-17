"""End-to-end diagnostic workflow tests on the small repository fixture."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import cast

import pytest

from canfd_offset_optimizer.diagnostics import cpsat_verify
from canfd_offset_optimizer.diagnostics.candidate_pool_study import (
    run_candidate_pool_study,
)
from canfd_offset_optimizer.diagnostics.restart_study import (
    _balanced_is_stable,
    _recommended_checkpoint,
    run_restart_study,
)
from canfd_offset_optimizer.diagnostics.tolerance_study import run_tolerance_scan
from canfd_offset_optimizer.diagnostics.triple_ablation import run_triple_ablation
from canfd_offset_optimizer.config import (
    ModelConfig,
    OptimizationConfig,
    ProjectConfig,
    RestartPolicy,
)
from canfd_offset_optimizer.exceptions import ConfigurationError
from canfd_offset_optimizer.models import (
    CanMessage,
    ChannelConfig,
    NetworkModel,
    WeightMode,
)
from canfd_offset_optimizer.parsers.project_loader import LoadedProject, load_project
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


FIXTURES = Path(__file__).parents[1] / "fixtures"


def _loaded() -> LoadedProject:
    return load_project(
        FIXTURES / "dbc" / "four_messages.dbc",
        FIXTURES / "arxml",
        FIXTURES / "config" / "project.yaml",
        weight_mode_override=WeightMode.FRAME_TIME_US,
        objective_mode_override=None,
    )


def test_restart_study_writes_jsonl_summaries_and_plot(tmp_path: Path) -> None:
    loaded = _loaded()
    summary = run_restart_study(
        loaded,
        tmp_path,
        "TEST",
        batch_count=2,
        max_attempts=3,
        checkpoints=(1, 2, 3),
    )
    assert summary["batch_count"] == 2
    lines = (tmp_path / "results" / "restart_records.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) >= 6
    assert all(json.loads(line)["assignments"] for line in lines)
    assert (tmp_path / "results" / "batch_summary.json").is_file()
    assert (tmp_path / "results" / "unique_assignments.json").is_file()
    assert (tmp_path / "plots" / "TEST_restart_saturation.png").is_file()
    assert (tmp_path / "plots" / "TEST_global_best_hit_rate.png").is_file()
    assert (
        tmp_path / "plots" / "TEST_batch_objective_distribution.png"
    ).is_file()


def test_candidate_pool_study_writes_auditable_grid(tmp_path: Path) -> None:
    summary = run_candidate_pool_study(
        _loaded(),
        tmp_path,
        "TEST",
        seed=3,
        total_attempts=4,
        pool_sizes=(1, 4),
    )
    assert summary["pool_sizes"] == [1, 4]
    runs = cast(list[dict[str, object]], summary["runs"])
    assert [run["requested_pool_size"] for run in runs] == [1, 4]
    audit_path = tmp_path / "results" / "candidate_pool_audit.jsonl"
    audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert audit
    assert all(row["candidate_assignment_hash"] for row in audit)
    assert all(row["candidate_steady_phase_hash"] for row in audit)
    assert all("balanced_objective_before" in row for row in audit)
    assert (tmp_path / "results" / "candidate_pool_comparison.csv").read_bytes().startswith(
        b"\xef\xbb\xbf"
    )
    assert (tmp_path / "results" / "candidate_pool_summary.json").is_file()


def test_triple_ablation_writes_four_groups_and_audit(tmp_path: Path) -> None:
    summary = run_triple_ablation(
        _loaded(), tmp_path, "TEST", seed=5, total_attempts=4
    )
    variants = cast(list[dict[str, object]], summary["variants"])
    assert [variant["group"] for variant in variants] == ["A", "B", "C", "D"]
    assert [variant["pool_size"] for variant in variants] == [1, 4, 1, 4]
    assert [variant["triple_enabled"] for variant in variants] == [
        False,
        False,
        True,
        True,
    ]
    audit = [
        json.loads(line)
        for line in (
            tmp_path / "results" / "triple_ablation_audit.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert audit
    assert all(row["triple_search"] is None for row in audit if not row["triple_enabled"])
    assert all(row["triple_search"] is not None for row in audit if row["triple_enabled"])
    enabled_audits = [row["triple_search"] for row in audit if row["triple_enabled"]]
    assert all(item["timings"] is not None for item in enabled_audits)
    assert all("must not be summed" in item["timing_semantics"] for item in enabled_audits)
    csv_path = tmp_path / "results" / "triple_ablation.csv"
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "贡献预计算耗时(s)" in csv_path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert (tmp_path / "results" / "triple_ablation_summary.json").is_file()


def test_restart_saturation_and_balanced_escalation_rules() -> None:
    checkpoints = (1, 3, 5, 10)
    assert _recommended_checkpoint(
        checkpoints, {1: False, 3: True, 5: True, 10: True}
    ) == 3
    assert _recommended_checkpoint(
        checkpoints, {1: False, 3: True, 5: False, 10: True}
    ) is None
    assert _recommended_checkpoint(
        checkpoints, {1: False, 3: False, 5: False, 10: False}
    ) is None
    assert _balanced_is_stable(0.90, 10, 5, 5)
    assert not _balanced_is_stable(0.89, 10, 1, 5)
    assert not _balanced_is_stable(0.95, 10, 6, 5)


def test_tolerance_scan_reuses_peak_and_writes_auditable_outputs(
    tmp_path: Path,
) -> None:
    loaded = _loaded()
    payload = run_tolerance_scan(
        loaded,
        tmp_path,
        "TEST",
        total_attempts=1,
        tolerances=(0.0, 0.05, 0.20),
    )
    assert len(cast(list[object], payload["tolerances"])) == 3
    assert (tmp_path / "results" / "tolerance_scan.csv").read_bytes().startswith(
        b"\xef\xbb\xbf"
    )
    assert (tmp_path / "plots" / "TEST_tolerance_pareto.png").is_file()


def test_missing_optional_solver_has_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = cpsat_verify.importlib.import_module

    def missing(name: str) -> object:
        if name == "ortools.sat.python.cp_model":
            raise ImportError(name)
        return original(name)

    monkeypatch.setattr(cpsat_verify.importlib, "import_module", missing)
    with pytest.raises(ConfigurationError, match=r"\[solver\]"):
        cpsat_verify._cp_model_module()


def test_cpsat_matches_exhaustive_q_on_a_tiny_instance(tmp_path: Path) -> None:
    pytest.importorskip("ortools.sat.python.cp_model")
    offsets = (5_000, 10_000)
    messages = (
        CanMessage("A", 1, False, 10_000, 100, offsets, 5_000, "ECU", 0),
        CanMessage("B", 2, False, 10_000, 200, offsets, 10_000, "ECU", 1),
    )
    startup, steady, hyperperiod = build_windows(messages, 5_000, 10_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    input_file = tmp_path / "input.txt"
    input_file.write_text("tiny", encoding="utf-8")
    network = NetworkModel(
        messages,
        ChannelConfig("CAN", 500_000, 2_000_000, True),
        hyperperiod,
        startup,
        steady,
        WeightMode.FRAME_TIME_US,
        input_files=(input_file,),
    )
    config = ProjectConfig(
        optimization=OptimizationConfig(
            slot_width_us=5_000,
            offset_min_us=5_000,
            offset_max_us=10_000,
            offset_step_us=5_000,
            restart_policy=RestartPolicy.fixed(1),
        ),
        model=ModelConfig(weight_mode=WeightMode.FRAME_TIME_US),
    )
    loaded = LoadedProject(config, network, slot_map)
    payload = cpsat_verify.run_cpsat_verification(
        loaded,
        tmp_path / "solver",
        "TINY",
        total_attempts=1,
        time_limit_seconds=10,
    )
    exhaustive_q = []
    for first, second in product(offsets, repeat=2):
        state = SearchState(messages, slot_map)
        state.apply_assignments({"A": first, "B": second})
        exhaustive_q.append(sum(load * load for load in state.steady_slot_loads))
    assert payload["solver_status"] == "OPTIMAL"
    assert payload["best_feasible_Qss"] == min(exhaustive_q)
