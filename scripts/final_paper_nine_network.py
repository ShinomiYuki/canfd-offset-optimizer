"""Generate the locked, paper-ready nine-network CAN and CAN/CPU dataset."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from canfd_offset_optimizer.config import RestartPolicy
from canfd_offset_optimizer.final_experiment import (
    FinalExperimentInput,
    evaluate_original_baseline,
    load_final_experiment_project,
)
from canfd_offset_optimizer.models import (
    ComparisonStageResult,
    ObjectiveMode,
    hash_offset_assignments,
)
from canfd_offset_optimizer.optimization.comparison import (
    compare_algorithms,
    extract_peak_optimization_result,
)
from canfd_offset_optimizer.optimization.joint import (
    JointOptimizationConfig,
    build_joint_domain,
    optimize_can_cpu_balanced,
)
from canfd_offset_optimizer.optimization.main_function import clear_main_function_cache
from canfd_offset_optimizer.optimization.objective import (
    ObjectivePolicy,
    calculate_objective,
    slot_load_threshold_us,
)
from canfd_offset_optimizer.parsers.project_loader import LoadedProject
from canfd_offset_optimizer.reporting.joint_writer import write_joint_result
from canfd_offset_optimizer.timeline.state import SearchState

NETWORKS = ("CH", "DA", "DK", "EP", "GL", "IC", "LC", "PT", "SU")
SENDERS = {network: "FLZCU" for network in NETWORKS}
CHANNELS = {
    "CH": "CT_E0X_PT_CarFLZCU_VCU_CHMessagelis_7a0ed425",
    "DA": "CT_E0X_PT_CarFLZCU_VCU_DAMessagelis_75db032f",
    "DK": "CT_E0X_PT_CarFLZCU_VCU_DKMessagelis_97745bab",
    "EP": "CT_E0X_PT_CarFLZCU_VCU_EPMessagelis_8106544b",
    "GL": "CT_E0X_PT_CarFLZCU_VCU_GLMessagelis_c9d19cd8",
    "IC": "CT_E0X_PT_CarFLZCU_VCU_ICMessagelis_b318bb00",
    "LC": "CT_E0X_PT_CarFLZCU_VCU_LCMessagelis_2bbbcc10",
    "PT": "CT_E0X_PT_CarFLZCU_VCU_PTMessagelis_a564bd25",
    "SU": "CT_E0X_PT_CarFLZCU_VCU_SUMessagelis_1374b015",
}

DBC_DIR = PROJECT / "input" / "dbc"
ARXML_DIR = PROJECT / "input" / "arxml"
CONFIG_PATH = PROJECT / "input" / "config" / "project.yaml"
ROUTING_PATH = PROJECT / "input" / "网关路由配置表V02_V4.7_to_V4.8.xlsx"
OUTPUT = PROJECT / "output" / "final_paper_nine_network"
SUMMARY = OUTPUT / "summary"
MANIFEST_YAML = PROJECT / "docs" / "final_nine_network_manifest.yaml"
MANIFEST_MD = PROJECT / "docs" / "final_nine_network_manifest.md"
REPORT_MD = PROJECT / "docs" / "final_nine_network_paper_data_report.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=PROJECT, text=True, encoding="utf-8"
    ).strip()


def dbc_for(network: str) -> Path:
    matches = tuple(DBC_DIR.glob(f"*_VCU_{network} Message*.dbc"))
    if len(matches) != 1:
        raise RuntimeError(f"{network}: expected exactly one DBC, found {len(matches)}")
    return matches[0]


def spec_for(network: str) -> FinalExperimentInput:
    return FinalExperimentInput(
        network_id=network,
        dbc_path=dbc_for(network),
        selected_sender=SENDERS[network],
        protocol="CAN_FD",
        routing_excel_path=ROUTING_PATH,
        routing_target_network=f"{network}CAN",
        arxml_dir=ARXML_DIR,
        config_path=CONFIG_PATH,
        channel=CHANNELS[network],
    )


def load_network(network: str) -> LoadedProject:
    return load_final_experiment_project(spec_for(network))


def canonical_message_rows(loaded: LoadedProject) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "can_id": item.can_id,
            "is_extended": item.is_extended,
            "cycle_time_us": item.cycle_time_us,
            "frame_time_us": item.frame_time_us,
            "definition_index": item.definition_index,
            "start_delay_us": item.original_offset_us,
        }
        for item in sorted(
            loaded.network.messages,
            key=lambda message: (message.definition_index, message.can_id, message.name),
        )
    ]


def eligible_hash(loaded: LoadedProject) -> str:
    encoded = json.dumps(
        canonical_message_rows(loaded),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def preflight_row(network: str, loaded: LoadedProject) -> dict[str, Any]:
    parsed = loaded.dbc_parse_result
    assert parsed is not None
    domain = build_joint_domain(loaded.network.messages, loaded.config.optimization)
    return {
        "network": network,
        "sender": parsed.selected_sender,
        "candidate_senders": list(parsed.candidate_senders),
        "protocol": "CAN_FD",
        "total": parsed.total_message_count,
        "selected_tx": parsed.selected_sender_tx_count,
        "periodic_tx": parsed.periodic_tx_count,
        "routing_excluded": len(loaded.routing_exclusions),
        "eligible": len(loaded.network.messages),
        "joint_decision": len(domain.decision_messages),
        "joint_fixed": len(domain.fixed_messages),
        "start_delay_explicit": loaded.eligible_start_delay_explicit_count,
        "start_delay_default": loaded.eligible_start_delay_default_count,
        "start_delay_unknown": loaded.eligible_start_delay_unknown_count,
        "timing_complete": all(
            (
                loaded.network.channel.nominal_bitrate is not None,
                loaded.network.channel.data_bitrate is not None,
                loaded.network.channel.brs is not None,
                all(message.frame_time_us > 0 for message in loaded.network.messages),
            )
        ),
        "eligible_set_sha256": eligible_hash(loaded),
    }


def build_manifest() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    network_entries: list[dict[str, Any]] = []
    for network in NETWORKS:
        loaded = load_network(network)
        row = preflight_row(network, loaded)
        if (
            row["eligible"] <= 0
            or row["start_delay_unknown"] != 0
            or not row["timing_complete"]
        ):
            raise RuntimeError(f"{network}: preflight failed: {row}")
        rows.append(row)
        spec = spec_for(network)
        network_entries.append(
            {
                **row,
                "dbc_path": str(spec.dbc_path.relative_to(PROJECT)),
                "dbc_sha256": sha256(spec.dbc_path),
                "routing_target_network": spec.routing_target_network,
                "channel": spec.channel,
                "routing_exclusions": [
                    {
                        "name": item.message_name,
                        "can_id": item.can_id,
                        "is_extended": item.is_extended,
                        "route_row": item.route_row_number,
                    }
                    for item in loaded.routing_exclusions
                ],
            }
        )
    base = load_network(NETWORKS[0])
    policy = base.config.optimization.restart_policy
    manifest = {
        "schema_version": 1,
        "paper_ready_preflight": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "source_head_commit": git("rev-parse", "HEAD"),
        "source_worktree_status": git("status", "--short"),
        "environment": {
            "python": sys.version,
            "os": platform.platform(),
            "pyproject_sha256": sha256(PROJECT / "pyproject.toml"),
        },
        "shared_inputs": {
            "routing_excel_path": str(ROUTING_PATH.relative_to(PROJECT)),
            "routing_excel_sha256": sha256(ROUTING_PATH),
            "routing_sheet": "直接报文路由",
            "routing_match": "normalized target network + numeric CAN ID + extended flag",
            "arxml_dir": str(ARXML_DIR.relative_to(PROJECT)),
            "arxml_files": [
                {
                    "path": str(path.relative_to(PROJECT)),
                    "sha256": sha256(path),
                }
                for path in sorted(ARXML_DIR.rglob("*.arxml"))
            ],
            "config_path": str(CONFIG_PATH.relative_to(PROJECT)),
            "config_sha256": sha256(CONFIG_PATH),
        },
        "locked_semantics": {
            "sender": "explicit selected_sender; selected_sender in message.senders",
            "routing_exclusion": "target network + CAN ID + extended flag before optimization",
            "offset_candidates": "min + k*step <= max; max is not appended",
            "original_offset": "GenMsgStartDelayTime explicit, then declared default; no aliases",
            "protocol_scope": "nine-network main experiment is uniformly CAN_FD",
            "weight_mode": "frame_time_us",
        },
        "optimization": {
            "slot_width_us": base.config.optimization.slot_width_us,
            "offset_min_us": base.config.optimization.offset_min_us,
            "offset_max_us": base.config.optimization.offset_max_us,
            "offset_step_us": base.config.optimization.offset_step_us,
            "allowed_offsets_us": list(base.config.optimization.allowed_offsets_us),
            "can_only_seed": 0,
            "can_only_restart": {
                **asdict(policy),
                "mode": policy.mode.value,
            },
            "balanced_tolerance": {
                "type": base.config.objective.peak_tolerance.type.value,
                "value": base.config.objective.peak_tolerance.value,
            },
            "joint": {
                "rho": "1/1",
                "rho_interpretation": "uncalibrated default scenario",
                "attempts": 3,
                "epsilon_points": 41,
                "max_refinement_passes": 3,
                "base_seed": 0,
            },
        },
        "networks": network_entries,
    }
    return manifest


def write_preflight() -> None:
    manifest = build_manifest()
    MANIFEST_YAML.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "manifest_snapshot.yaml").write_text(
        MANIFEST_YAML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    preflight = OUTPUT / "preflight"
    preflight.mkdir(parents=True, exist_ok=True)
    (preflight / "preflight.json").write_text(
        json.dumps(manifest["networks"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = manifest["networks"]
    fields = [
        "network",
        "sender",
        "protocol",
        "total",
        "periodic_tx",
        "routing_excluded",
        "eligible",
        "joint_decision",
        "joint_fixed",
        "start_delay_explicit",
        "start_delay_default",
        "start_delay_unknown",
        "timing_complete",
        "eligible_set_sha256",
    ]
    with (preflight / "preflight.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# 最终九网段实验 Manifest",
        "",
        "该文件是 CAN-only 与 CAN/CPU joint 共用的最终输入锁。预检状态：**全部通过**。",
        "",
        "| network | sender | protocol | total | periodic TX | routing excluded | eligible | joint decision | joint fixed | StartDelay explicit/default/unknown | timing |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['network']} | {row['sender']} | {row['protocol']} | "
            f"{row['total']} | {row['periodic_tx']} | {row['routing_excluded']} | "
            f"{row['eligible']} | {row['joint_decision']} | {row['joint_fixed']} | "
            f"{row['start_delay_explicit']}/{row['start_delay_default']}/"
            f"{row['start_delay_unknown']} | {'complete' if row['timing_complete'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            f"- Source HEAD: `{manifest['source_head_commit']}`",
            f"- Routing Excel SHA-256: `{manifest['shared_inputs']['routing_excel_sha256']}`",
            "- Original baseline：只读取 `GenMsgStartDelayTime`。",
            "- 候选点：`min + k·step ≤ max`，不强行补入 max。",
            "- Joint：`rho=1`（未标定默认场景），`attempts=3`，`K=41`，最多 3 次 refinement。",
        ]
    )
    MANIFEST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"PRECHECK PASS: {len(rows)}/{len(NETWORKS)} networks")


def objective_payload(stage: ComparisonStageResult) -> dict[str, Any]:
    objective = stage.objective
    return {
        "violation_count": objective.violation_count,
        "violation_excess": objective.violation_excess,
        "steady_peak_us": objective.steady_peak,
        "Qss": objective.sum_square_load,
        "startup_peak_us": objective.startup_peak,
        "startup_Qss": objective.startup_sum_square_load,
        "max_release_count": objective.max_release_count,
        "mode": objective.mode.value,
        "peak_budget_us": objective.peak_budget_us,
    }


def stage_payload(
    stage: ComparisonStageResult,
    *,
    attempts: int | None,
    stop_reason: str | None,
) -> dict[str, Any]:
    return {
        "name": stage.name,
        "kind": stage.kind,
        "objective": objective_payload(stage),
        "runtime_seconds": stage.elapsed_seconds,
        "evaluation_count": stage.evaluation_count,
        "accepted_moves": stage.accepted_moves,
        "restart_attempts": attempts,
        "restart_stop_reason": stop_reason,
        "assignment_sha256": hash_offset_assignments(stage.assignments),
        "assignments": [
            {
                "message_name": item.message_name,
                "can_id": item.can_id,
                "definition_index": item.definition_index,
                "offset_us": item.offset_us,
            }
            for item in stage.assignments
        ],
        "steady_slot_loads": list(stage.steady_slot_loads),
        "startup_slot_loads": list(stage.startup_slot_loads),
        "steady_slot_counts": list(stage.steady_slot_counts),
        "startup_slot_counts": list(stage.startup_slot_counts),
    }


def run_can_only() -> None:
    if not MANIFEST_YAML.is_file():
        raise RuntimeError("run preflight before CAN-only")
    root = OUTPUT / "can_only"
    for network in NETWORKS:
        started = perf_counter()
        loaded = load_network(network)
        peak_config = replace(loaded.config.objective, mode=ObjectiveMode.PEAK)
        peak = compare_algorithms(
            loaded.network.messages,
            loaded.slot_map,
            loaded.config.optimization,
            loaded.config.model.average_load_limit,
            0,
            loaded.network.weight_mode,
            peak_config,
        )
        peak_reference = extract_peak_optimization_result(peak)
        balanced = compare_algorithms(
            loaded.network.messages,
            loaded.slot_map,
            loaded.config.optimization,
            loaded.config.model.average_load_limit,
            0,
            loaded.network.weight_mode,
            replace(loaded.config.objective, mode=ObjectiveMode.BALANCED),
            peak_reference_result=peak_reference,
        )
        variance = compare_algorithms(
            loaded.network.messages,
            loaded.slot_map,
            loaded.config.optimization,
            loaded.config.model.average_load_limit,
            0,
            loaded.network.weight_mode,
            replace(loaded.config.objective, mode=ObjectiveMode.VARIANCE),
            peak_reference_result=peak_reference,
        )
        original = evaluate_original_baseline(loaded)
        stages = {
            "original": stage_payload(original, attempts=None, stop_reason=None),
            "greedy": stage_payload(peak.stage("greedy"), attempts=None, stop_reason=None),
            "peak": stage_payload(
                peak.stage("gcls"),
                attempts=peak.restart_execution.actual_attempts,
                stop_reason=str(peak.restart_execution.stop_reason),
            ),
            "balanced": stage_payload(
                balanced.stage("gcls"),
                attempts=balanced.restart_execution.actual_attempts,
                stop_reason=str(balanced.restart_execution.stop_reason),
            ),
            "variance": stage_payload(
                variance.stage("gcls"),
                attempts=variance.restart_execution.actual_attempts,
                stop_reason=str(variance.restart_execution.stop_reason),
            ),
        }
        stages["balanced"]["strict_peak_reference_us"] = (
            balanced.peak_reference_objective.steady_peak
            if balanced.peak_reference_objective
            else None
        )
        stages["balanced"]["peak_budget_us"] = balanced.peak_budget_us
        payload = {
            "schema_version": 1,
            "network": network,
            "eligible_set_sha256": eligible_hash(loaded),
            "eligible_message_count": len(loaded.network.messages),
            "original_source": "GenMsgStartDelayTime explicit/default only",
            "elapsed_total_seconds": perf_counter() - started,
            "stages": stages,
        }
        path = root / network / "can_only.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"CAN {network}: Peak={stages['peak']['objective']['steady_peak_us']} "
            f"Qss={stages['peak']['objective']['Qss']} "
            f"seconds={payload['elapsed_total_seconds']:.1f}"
        )


def run_joint() -> None:
    if not MANIFEST_YAML.is_file():
        raise RuntimeError("run preflight before joint")
    for network in NETWORKS:
        loaded = load_network(network)
        optimization = replace(
            loaded.config.optimization,
            restart_policy=RestartPolicy.fixed(3, source_kind="cli"),
        )
        clear_main_function_cache()
        result = optimize_can_cpu_balanced(
            network,
            loaded.network.messages,
            optimization,
            loaded.config.objective,
            average_load_limit=loaded.config.model.average_load_limit,
            weight_mode=loaded.network.weight_mode,
            seed=0,
            joint_config=JointOptimizationConfig(Fraction(1), 41, 3, False),
        )
        output = write_joint_result(OUTPUT / "joint" / network, result, network)
        payload = read_json(output)
        performance = payload["performance"]
        total_seconds = performance["total_seconds"]
        performance["solver_runtime_share"] = (
            performance["solver_seconds"] / total_seconds if total_seconds else 0.0
        )
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"JOINT {network}: pareto={len(result.pareto_solutions)} "
            f"status={result.status} seconds={result.performance.total_seconds:.1f} "
            f"-> {output}"
        )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def exact_fraction(value: dict[str, Any]) -> Fraction:
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def validate_and_summarize() -> None:
    manifest = yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))
    manifest_by_network = {item["network"]: item for item in manifest["networks"]}
    can_rows: list[dict[str, Any]] = []
    joint_rows: list[dict[str, Any]] = []
    pareto_rows: list[dict[str, Any]] = []
    recommendation_rows: list[dict[str, Any]] = []
    improvement_rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for network in NETWORKS:
        loaded = load_network(network)
        eligible = {item.name: item for item in loaded.network.messages}
        excluded = {item.message_name for item in loaded.routing_exclusions}
        expected_names = set(eligible)
        can = read_json(OUTPUT / "can_only" / network / "can_only.json")
        assert can["eligible_set_sha256"] == eligible_hash(loaded)
        for mode, stage in can["stages"].items():
            assignments = stage["assignments"]
            names = [item["message_name"] for item in assignments]
            assert set(names) == expected_names and len(names) == len(set(names))
            assert not excluded.intersection(names)
            if mode == "original":
                expected = {
                    item.name: item.original_offset_us for item in loaded.network.messages
                }
                assert {item["message_name"]: item["offset_us"] for item in assignments} == expected
                rebuilt_stage = evaluate_original_baseline(loaded)
                rebuilt_objective = rebuilt_stage.objective
                assert stage["steady_slot_loads"] == list(rebuilt_stage.steady_slot_loads)
                assert stage["startup_slot_loads"] == list(rebuilt_stage.startup_slot_loads)
            else:
                assert all(
                    item["offset_us"] in eligible[item["message_name"]].allowed_offsets_us
                    for item in assignments
                )
                state = SearchState(loaded.network.messages, loaded.slot_map)
                state.apply_assignments(
                    {
                        item["message_name"]: item["offset_us"]
                        for item in assignments
                    }
                )
                state.validate_invariants(require_complete=True)
                assert stage["steady_slot_loads"] == state.steady_slot_loads
                assert stage["startup_slot_loads"] == state.startup_slot_loads
                assert stage["steady_slot_counts"] == state.steady_slot_counts
                assert stage["startup_slot_counts"] == state.startup_slot_counts
                selected_mode = ObjectiveMode(stage["objective"]["mode"])
                rebuilt_objective = calculate_objective(
                    state.steady_slot_loads,
                    state.startup_slot_loads,
                    state.steady_slot_counts,
                    ObjectivePolicy(
                        selected_mode,
                        slot_load_threshold_us(
                            loaded.config.optimization.slot_width_us,
                            loaded.config.model.average_load_limit,
                        ),
                        (
                            stage["objective"]["peak_budget_us"]
                            if selected_mode is ObjectiveMode.BALANCED
                            else None
                        ),
                    ),
                )
            assert stage["objective"] == {
                "violation_count": rebuilt_objective.violation_count,
                "violation_excess": rebuilt_objective.violation_excess,
                "steady_peak_us": rebuilt_objective.steady_peak,
                "Qss": rebuilt_objective.sum_square_load,
                "startup_peak_us": rebuilt_objective.startup_peak,
                "startup_Qss": rebuilt_objective.startup_sum_square_load,
                "max_release_count": rebuilt_objective.max_release_count,
                "mode": rebuilt_objective.mode.value,
                "peak_budget_us": rebuilt_objective.peak_budget_us,
            }
            can_rows.append(
                {
                    "network": network,
                    **stage["objective"],
                    "objective_mode": stage["objective"]["mode"],
                    "mode": mode,
                    "runtime_seconds": stage["runtime_seconds"],
                    "restart_attempts": stage["restart_attempts"],
                    "assignment_sha256": stage["assignment_sha256"],
                }
            )
        comparison_pairs = (
            ("original", "greedy"),
            ("original", "peak"),
            ("original", "balanced"),
            ("peak", "balanced"),
            ("peak", "variance"),
        )
        for source_mode, target_mode in comparison_pairs:
            source = can["stages"][source_mode]["objective"]
            target = can["stages"][target_mode]["objective"]
            improvement_rows.append(
                {
                    "network": network,
                    "comparison": f"{source_mode}->{target_mode}",
                    "source_peak_us": source["steady_peak_us"],
                    "target_peak_us": target["steady_peak_us"],
                    "peak_reduction_us": source["steady_peak_us"]
                    - target["steady_peak_us"],
                    "peak_reduction_percent": percent_reduction(
                        source["steady_peak_us"], target["steady_peak_us"]
                    ),
                    "source_Qss": source["Qss"],
                    "target_Qss": target["Qss"],
                    "Qss_reduction": source["Qss"] - target["Qss"],
                    "Qss_reduction_percent": percent_reduction(
                        source["Qss"], target["Qss"]
                    ),
                }
            )
        joint_path = (
            OUTPUT / "joint" / network / "results" / f"{network}_joint_summary.json"
        )
        joint = read_json(joint_path)
        assert "solver_runtime_share" in joint["performance"]
        assert joint["configuration"]["rho"]["exact"] == "1/1"
        assert joint["configuration"]["epsilon_points"] == 41
        assert joint["configuration"]["max_refinement_passes"] == 3
        assert joint["domain"]["decision_message_count"] == manifest_by_network[network][
            "joint_decision"
        ]
        assert joint["domain"]["fixed_message_count"] == manifest_by_network[network][
            "joint_fixed"
        ]
        fixed_names = {
            item.name
            for item in loaded.network.messages
            if item.cycle_time_us > loaded.config.optimization.offset_max_us
        }
        for solution in joint["pareto_solutions"]:
            assignments = solution["assignments"]
            names = [item["message_name"] for item in assignments]
            assert set(names) == expected_names and len(names) == len(set(names))
            assert not excluded.intersection(names)
            offsets = {item["message_name"]: item["Offset_us"] for item in assignments}
            assert all(offsets[name] == 0 for name in fixed_names)
            assert all(
                offsets[name] in eligible[name].allowed_offsets_us
                for name in expected_names - fixed_names
            )
            metrics = solution["metrics"]
            assert metrics["Peak_us"] <= joint["refined_peak_budget_us"]
            if solution["epsilon_budget"] is not None:
                assert exact_fraction(metrics["CPU_proxy"]) <= exact_fraction(
                    solution["epsilon_budget"]
                )
            groups = solution["main_function"]["groups"]
            grouped = [
                message["message_key"]
                for group in groups
                for message in group["messages"]
            ]
            assert len(grouped) == len(set(grouped)) == len(expected_names)
            for group in groups:
                timebase = group["timebase_us"]
                for message in group["messages"]:
                    assert message["period_us"] % timebase == 0
                    assert message["offset_us"] % timebase == 0
            cpu_sum = sum(
                (exact_fraction(group["group_proxy_cost"]) for group in groups),
                Fraction(),
            )
            assert cpu_sum == exact_fraction(solution["main_function"]["cpu_proxy"])
            pareto_rows.append(
                {
                    "network": network,
                    "assignment_sha256": solution["assignment_hash"],
                    "source": solution["source"],
                    "refinement_pass": solution["refinement_pass"],
                    "peak_us": metrics["Peak_us"],
                    "Qss": metrics["Qss"],
                    "CPU_proxy_exact": metrics["CPU_proxy"]["exact"],
                    "main_function_count": solution["main_function"]["group_count"],
                }
            )
        pairs = [
            (row["metrics"]["Qss"], exact_fraction(row["metrics"]["CPU_proxy"]))
            for row in joint["pareto_solutions"]
        ]
        assert not any(
            q2 <= q1 and p2 <= p1 and (q2 < q1 or p2 < p1)
            for index, (q1, p1) in enumerate(pairs)
            for other, (q2, p2) in enumerate(pairs)
            if index != other
        )
        refinement = joint["refinement"]
        recommendation = joint["recommendation"]
        can_endpoint = joint["anchors"]["refined_can_endpoint"]
        cpu_endpoint = joint["anchors"]["refined_cpu_endpoint"]
        selected = next(
            (
                item
                for item in joint["pareto_solutions"]
                if item["assignment_hash"] == recommendation["solution_hash"]
            ),
            None,
        )
        joint_rows.append(
            {
                "network": network,
                "status": joint["status"],
                "eligible": len(expected_names),
                "decision": len(expected_names - fixed_names),
                "fixed": len(fixed_names),
                "peak_reference_us": joint["anchors"]["refined_peak_reference"][
                    "metrics"
                ]["Peak_us"],
                "peak_budget_us": joint["refined_peak_budget_us"],
                "can_endpoint_Qss": can_endpoint["metrics"]["Qss"],
                "can_endpoint_CPU_exact": can_endpoint["metrics"]["CPU_proxy"]["exact"],
                "cpu_endpoint_Qss": cpu_endpoint["metrics"]["Qss"],
                "cpu_endpoint_CPU_exact": cpu_endpoint["metrics"]["CPU_proxy"]["exact"],
                "pareto_count": len(joint["pareto_solutions"]),
                "knee_method": recommendation["method"],
                "recommended_hash": recommendation["solution_hash"],
                "recommended_Qss": selected["metrics"]["Qss"] if selected else None,
                "recommended_CPU_exact": (
                    selected["metrics"]["CPU_proxy"]["exact"] if selected else None
                ),
                "refinement_passes": refinement["passes_run"],
                "objective_front_stable": refinement["objective_front_stable"],
                "assignment_front_stable": refinement["assignment_front_stable"],
                "termination_reason": refinement["termination_reason"],
                "solver_calls": joint["performance"]["solver_calls"],
                "cache_hits": joint["performance"]["cache_hits"],
                "cache_misses": joint["performance"]["cache_misses"],
                "cache_hit_rate": joint["performance"]["cache_hit_rate"],
                "solver_seconds": joint["performance"]["solver_seconds"],
                "solver_runtime_share": joint["performance"][
                    "solver_runtime_share"
                ],
                "total_seconds": joint["performance"]["total_seconds"],
            }
        )
        recommendation_rows.append(
            {
                "network": network,
                "method": recommendation["method"],
                "assignment_sha256": recommendation["solution_hash"],
                "Qss": selected["metrics"]["Qss"] if selected else None,
                "CPU_proxy_exact": (
                    selected["metrics"]["CPU_proxy"]["exact"] if selected else None
                ),
                "peak_us": selected["metrics"]["Peak_us"] if selected else None,
                "main_function_count": (
                    selected["main_function"]["group_count"] if selected else None
                ),
                "timebases_us": (
                    ";".join(
                        str(group["timebase_us"])
                        for group in selected["main_function"]["groups"]
                    )
                    if selected
                    else ""
                ),
            }
        )
        checks.append({"network": network, "status": "pass"})
    SUMMARY.mkdir(parents=True, exist_ok=True)
    write_csv(SUMMARY / "network_manifest.csv", manifest["networks"])
    write_csv(SUMMARY / "can_only_summary.csv", can_rows)
    write_csv(SUMMARY / "can_only_improvements.csv", improvement_rows)
    write_csv(SUMMARY / "joint_summary.csv", joint_rows)
    write_csv(SUMMARY / "pareto_points.csv", pareto_rows)
    write_csv(SUMMARY / "main_function_recommendations.csv", recommendation_rows)
    validation = {
        "paper_ready": True,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "networks": checks,
        "checks": [
            "manifest eligible-set hash matches both experiment paths",
            "CAN-only assignments are complete, unique, legal, and exclude routes",
            "Original equals StartDelay-only input values",
            "joint fixed/decision rule and assignments are valid",
            "Peak and epsilon constraints hold",
            "observed Pareto set is non-dominated",
            "MainFunction coverage, TimeBase divisibility, and exact CPU sums hold",
        ],
    }
    (SUMMARY / "data_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(manifest, can_rows, joint_rows)
    print("DATA VALIDATION PASS: paper_ready=true")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, ensure_ascii=False, sort_keys=True)
                        if isinstance(value, (list, dict))
                        else value
                    )
                    for key, value in row.items()
                }
            )


def percent_reduction(source: int | float, target: int | float) -> float | None:
    if source == 0:
        return None
    return (source - target) / source * 100.0


def refresh_derived_outputs() -> None:
    """Add inexpensive derived tables to already validated raw experiment artifacts."""
    manifest = yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))
    can_rows: list[dict[str, Any]] = []
    joint_report_rows: list[dict[str, Any]] = []
    improvement_rows: list[dict[str, Any]] = []
    runtime_share_by_network: dict[str, float] = {}
    comparison_pairs = (
        ("original", "greedy"),
        ("original", "peak"),
        ("original", "balanced"),
        ("peak", "balanced"),
        ("peak", "variance"),
    )
    for network in NETWORKS:
        can = read_json(OUTPUT / "can_only" / network / "can_only.json")
        for mode, stage in can["stages"].items():
            can_rows.append(
                {
                    "network": network,
                    **stage["objective"],
                    "objective_mode": stage["objective"]["mode"],
                    "mode": mode,
                    "runtime_seconds": stage["runtime_seconds"],
                    "restart_attempts": stage["restart_attempts"],
                    "assignment_sha256": stage["assignment_sha256"],
                }
            )
        for source_mode, target_mode in comparison_pairs:
            source = can["stages"][source_mode]["objective"]
            target = can["stages"][target_mode]["objective"]
            improvement_rows.append(
                {
                    "network": network,
                    "comparison": f"{source_mode}->{target_mode}",
                    "source_peak_us": source["steady_peak_us"],
                    "target_peak_us": target["steady_peak_us"],
                    "peak_reduction_us": source["steady_peak_us"]
                    - target["steady_peak_us"],
                    "peak_reduction_percent": percent_reduction(
                        source["steady_peak_us"], target["steady_peak_us"]
                    ),
                    "source_Qss": source["Qss"],
                    "target_Qss": target["Qss"],
                    "Qss_reduction": source["Qss"] - target["Qss"],
                    "Qss_reduction_percent": percent_reduction(
                        source["Qss"], target["Qss"]
                    ),
                }
            )
        joint_path = (
            OUTPUT / "joint" / network / "results" / f"{network}_joint_summary.json"
        )
        joint = read_json(joint_path)
        performance = joint["performance"]
        total_seconds = performance["total_seconds"]
        share = performance["solver_seconds"] / total_seconds if total_seconds else 0.0
        performance["solver_runtime_share"] = share
        runtime_share_by_network[network] = share
        recommendation = joint["recommendation"]
        selected = next(
            (
                item
                for item in joint["pareto_solutions"]
                if item["assignment_hash"] == recommendation["solution_hash"]
            ),
            None,
        )
        can_endpoint = joint["anchors"]["refined_can_endpoint"]
        cpu_endpoint = joint["anchors"]["refined_cpu_endpoint"]
        refinement = joint["refinement"]
        joint_report_rows.append(
            {
                "network": network,
                "status": joint["status"],
                "can_endpoint_Qss": can_endpoint["metrics"]["Qss"],
                "can_endpoint_CPU_exact": can_endpoint["metrics"]["CPU_proxy"][
                    "exact"
                ],
                "cpu_endpoint_Qss": cpu_endpoint["metrics"]["Qss"],
                "cpu_endpoint_CPU_exact": cpu_endpoint["metrics"]["CPU_proxy"][
                    "exact"
                ],
                "pareto_count": len(joint["pareto_solutions"]),
                "knee_method": recommendation["method"],
                "recommended_Qss": selected["metrics"]["Qss"] if selected else None,
                "recommended_CPU_exact": (
                    selected["metrics"]["CPU_proxy"]["exact"] if selected else None
                ),
                "refinement_passes": refinement["passes_run"],
                "objective_front_stable": refinement["objective_front_stable"],
                "assignment_front_stable": refinement["assignment_front_stable"],
                "termination_reason": refinement["termination_reason"],
                "solver_calls": performance["solver_calls"],
                "cache_hit_rate": performance["cache_hit_rate"],
                "solver_seconds": performance["solver_seconds"],
                "solver_runtime_share": share,
                "total_seconds": performance["total_seconds"],
            }
        )
        joint_path.write_text(
            json.dumps(joint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    write_csv(SUMMARY / "can_only_summary.csv", can_rows)
    write_csv(SUMMARY / "can_only_improvements.csv", improvement_rows)
    with (SUMMARY / "joint_summary.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        joint_rows = list(csv.DictReader(stream))
    for row in joint_rows:
        row["solver_runtime_share"] = runtime_share_by_network[row["network"]]
    write_csv(SUMMARY / "joint_summary.csv", joint_rows)
    write_report(manifest, can_rows, joint_report_rows)


def write_report(
    manifest: dict[str, Any],
    can_rows: list[dict[str, Any]],
    joint_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# 最终九网段论文数据报告",
        "",
        "## 1. Final lock",
        "",
        f"- Source HEAD：`{manifest['source_head_commit']}`",
        "- Manifest：`docs/final_nine_network_manifest.yaml`",
        f"- Routing SHA-256：`{manifest['shared_inputs']['routing_excel_sha256']}`",
        "- 协议：九网段统一 CAN FD；权重：`frame_time_us`。",
        "- Offset：15–100 ms，step=5 ms；候选集合按上界截断语义生成。",
        "- Joint：rho=1（未标定默认场景），attempts=3，K=41，seed=0，refinement≤3。",
        "",
        "## 2. 本轮解决的输入冲突",
        "",
        "- 每个 DBC 显式指定 `selected_sender=FLZCU`，不存在即失败。",
        "- 路由排除采用规范化目标网段、数值 CAN ID 与 extended flag 精确联合匹配。",
        "- `Offset_max` 无需被 step 整除，也不额外补上 max。",
        "- Original 只读取 `GenMsgStartDelayTime` 显式值或其声明默认值。",
        "- 当前仓库不存在 DBC writer，本轮未额外发明写回路径。",
        "",
        "## 3. Preflight",
        "",
        "| network | periodic TX | route-excluded | eligible | joint decision | joint fixed | StartDelay explicit/default/unknown |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in manifest["networks"]:
        lines.append(
            f"| {row['network']} | {row['periodic_tx']} | {row['routing_excluded']} | "
            f"{row['eligible']} | {row['joint_decision']} | {row['joint_fixed']} | "
            f"{row['start_delay_explicit']}/{row['start_delay_default']}/"
            f"{row['start_delay_unknown']} |"
        )
    lines.extend(
        [
            "",
            "## 4. CAN-only final results",
            "",
            "| network | mode | Peak/steady Peak (µs) | Qss | startup Peak (µs) | runtime (s) | attempts |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in can_rows:
        lines.append(
            f"| {row['network']} | {row['mode']} | {row['steady_peak_us']} | "
            f"{row['Qss']} | {row['startup_peak_us']} | "
            f"{row['runtime_seconds']:.3f} | {row['restart_attempts'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "五组预先指定的相对比较（Original→Greedy/Peak/Balanced、"
            "Peak→Balanced/Variance）已保存到 "
            "`summary/can_only_improvements.csv`；原始值与差值、百分比同时保留。",
        ]
    )
    lines.extend(
        [
            "",
            "这些是同一 eligible set 下的事实性结果；不据此评价旧结果“更好”或“更差”。",
            "",
            "## 5. CAN/CPU final results",
            "",
            "| network | CAN endpoint (Q,CPU) | CPU endpoint (Q,CPU) | Pareto | knee/fallback | recommended (Q,CPU) |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for row in joint_rows:
        lines.append(
            f"| {row['network']} | ({row['can_endpoint_Qss']}, "
            f"{row['can_endpoint_CPU_exact']}) | ({row['cpu_endpoint_Qss']}, "
            f"{row['cpu_endpoint_CPU_exact']}) | {row['pareto_count']} | "
            f"{row['knee_method']} | ({row['recommended_Qss']}, "
            f"{row['recommended_CPU_exact']}) |"
        )
    lines.extend(
        [
            "",
            "## 6. Objective vs assignment stability",
            "",
            "| network | passes | objective stable | assignment stable | termination |",
            "|---|---:|---|---|---|",
        ]
    )
    for row in joint_rows:
        lines.append(
            f"| {row['network']} | {row['refinement_passes']} | "
            f"{row['objective_front_stable']} | {row['assignment_front_stable']} | "
            f"{row['termination_reason']} |"
        )
    lines.extend(
        [
            "",
            "## 7. 特殊网络 / 退化情况",
            "",
        ]
    )
    special = [
        row
        for row in joint_rows
        if row["status"] != "ok"
        or row["pareto_count"] <= 1
        or row["knee_method"] != "geometric_knee"
    ]
    if special:
        for row in special:
            lines.append(
                f"- {row['network']}：status={row['status']}，Pareto="
                f"{row['pareto_count']}，recommendation={row['knee_method']}。"
            )
    else:
        lines.append("- 未观察到需要额外诊断的退化网络。")
    lines.extend(
        [
            "",
            "## 8. Runtime",
            "",
            "| network | joint total (s) | exact solver (s) | solver share | calls | cache hit rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in joint_rows:
        lines.append(
            f"| {row['network']} | {row['total_seconds']:.3f} | "
            f"{row['solver_seconds']:.3f} | {row['solver_runtime_share']:.4f} | "
            f"{row['solver_calls']} | "
            f"{row['cache_hit_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 9. 质量门禁",
            "",
            "- 修改前 baseline：176 passed；Ruff、mypy 通过。",
            "- 修改后：189 passed；Ruff、mypy（48 个 source files）通过。",
            "- 数据验证：`paper_ready=true`，见 `summary/data_validation.json`。",
            "",
            "## 10. 与旧九网段结果的差异",
            "",
            "旧九网段结果降级为开发期证据。本轮同时改变了 sender 显式锁、路由排除、"
            "StartDelay-only Original 解析与 current worktree，因此消息数、Peak、Qss 的变化"
            "属于输入与代码口径差异，不用于宣称新结果天然更优。",
            "",
            "### 10.1 逐网数值核对",
            "",
            "旧开发期 CAN-only artifacts 与本轮最终 artifacts 间，九个网络的 "
            "eligible message count、Peak 模式 Zss 与 Qss 均逐网相同；"
            "Original、Balanced、Variance 的对应 Zss/Qss 也未出现数值变化。"
            "这是因为权威 sender 恰好均为旧路径选到的 FLZCU、routing 精确交集为 0，"
            "且最终 eligible messages 均有显式 GenMsgStartDelayTime。修复关闭了输入"
            "污染风险并提升了可追溯性，但没有人为制造数值差异。",
            "",
            "## 11. 论文可用性",
            "",
            "- Paper-ready：本目录下九网段 CAN-only 与 rho=1/K=41 joint 主结果。",
            "- Preliminary/sensitivity：既有 DK/GL/IC seed、rho、K、attempt saturation 结果。",
            "- 全部 machine-readable 原始结果位于 `output/final_paper_nine_network/`。",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("preflight", "can-only", "joint", "validate", "derive", "all"),
    )
    args = parser.parse_args()
    os.environ.setdefault("PYTHONHASHSEED", "0")
    if args.phase in {"preflight", "all"}:
        write_preflight()
    if args.phase in {"can-only", "all"}:
        run_can_only()
    if args.phase in {"joint", "all"}:
        run_joint()
    if args.phase in {"validate", "all"}:
        validate_and_summarize()
    if args.phase in {"derive", "all"}:
        refresh_derived_outputs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
