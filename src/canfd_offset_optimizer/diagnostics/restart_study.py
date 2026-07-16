"""Peak restart batch stability and saturation diagnostics."""

from __future__ import annotations

import csv
import importlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from ..config import ObjectiveConfig, RestartPolicy
from ..models import (
    ObjectiveMode,
    ObjectiveValue,
    OffsetAssignment,
    RestartRecord,
    hash_offset_assignments,
)
from ..optimization.gcls import run_gcls
from ..parsers.project_loader import LoadedProject
from ..reporting.restart_writer import (
    AppendOnlyRestartWriter,
    configuration_hash,
    restart_record_dict,
)
from ..reporting.summary_writer import combined_input_hash


DEFAULT_CHECKPOINTS = (1, 3, 5, 10, 20, 21, 40, 80)


def _candidate_key(
    objective: ObjectiveValue, assignments: tuple[OffsetAssignment, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return objective.as_tuple(), tuple(item.offset_us for item in assignments)


def _best_prefix(
    baseline: tuple[ObjectiveValue, tuple[OffsetAssignment, ...]],
    records: tuple[RestartRecord, ...],
    count: int,
) -> tuple[ObjectiveValue, tuple[OffsetAssignment, ...]]:
    candidates = [baseline]
    candidates.extend(
        (record.objective, record.assignments) for record in records[:count]
    )
    return min(candidates, key=lambda item: _candidate_key(*item))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not rows:
            return
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _recommended_checkpoint(
    checkpoints: tuple[int, ...], status: dict[int, bool]
) -> int | None:
    """Return a pre-cap checkpoint whose complete suffix satisfies the rule."""
    # The cap matches its own prefix endpoint by construction. Requiring evidence
    # at a checkpoint strictly below the cap prevents this tautology from being
    # mislabeled as verified saturation.
    for index, checkpoint in enumerate(checkpoints[:-1]):
        if all(status[item] for item in checkpoints[index:]):
            return checkpoint
    return None


def _balanced_is_stable(
    hit_rate: float,
    batches_run: int,
    last_improvement_batch: int,
    no_improvement_window: int,
) -> bool:
    """Apply the fixed 90% hit-rate and trailing no-improvement criteria."""
    return (
        hit_rate >= 0.90
        and batches_run - last_improvement_batch >= no_improvement_window
    )


def _derive_unique_assignments(jsonl_path: Path, output: Path) -> None:
    grouped: dict[str, dict[str, Any]] = {}
    with jsonl_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            digest = str(row["assignment_hash"])
            item = grouped.get(digest)
            if item is None:
                grouped[digest] = {
                    "assignment_hash": digest,
                    "occurrence_count": 1,
                    "objective": row["objective"],
                    "objectives": [row["objective"]],
                    "phase_counts": {str(row["phase"]): 1},
                    "assignments": row["assignments"],
                    "first_occurrence": {
                        "line": line_number,
                        "batch_index": row["batch_index"],
                        "restart_index": row["restart_index"],
                        "seed": row["seed"],
                    },
                }
            else:
                if item["assignments"] != row["assignments"]:
                    raise ValueError("assignment hash collision while aggregating JSONL")
                item["occurrence_count"] = int(item["occurrence_count"]) + 1
                objectives = cast(list[object], item["objectives"])
                if row["objective"] not in objectives:
                    objectives.append(row["objective"])
                phase_counts = cast(dict[str, int], item["phase_counts"])
                phase = str(row["phase"])
                phase_counts[phase] = phase_counts.get(phase, 0) + 1
    output.write_text(
        json.dumps(
            sorted(grouped.values(), key=lambda item: str(item["assignment_hash"])),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_restart_study(
    loaded: LoadedProject,
    output: Path,
    network_prefix: str,
    *,
    base_seed: int = 0,
    batch_count: int = 30,
    max_attempts: int = 80,
    checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS,
    resume: bool = False,
) -> dict[str, object]:
    """Run independent fixed Peak pools and derive prefix stability statistics."""
    if batch_count <= 0 or max_attempts <= 0:
        raise ValueError("batch_count and max_attempts must be positive")
    if not checkpoints or tuple(sorted(set(checkpoints))) != checkpoints:
        raise ValueError("checkpoints must be unique and increasing")
    if checkpoints[-1] != max_attempts or checkpoints[0] <= 0:
        raise ValueError("checkpoints must end at max_attempts")
    results_dir = output / "results"
    plots_dir = output / "plots"
    results_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    input_hash = combined_input_hash(loaded.network.input_files)
    config_hash = configuration_hash(loaded.config)
    experiment_id = (
        f"restart-study-{network_prefix}-{input_hash[:12]}-"
        f"{base_seed}-{batch_count}-{max_attempts}"
    )
    jsonl_path = results_dir / "restart_records.jsonl"
    writer = AppendOnlyRestartWriter(
        jsonl_path, experiment_id, input_hash, config_hash, resume=resume
    )
    existing = writer.existing_keys()
    peak_objective = ObjectiveConfig(mode=ObjectiveMode.PEAK)
    prefix_rows: list[dict[str, object]] = []
    batch_endpoints: list[
        tuple[ObjectiveValue, tuple[OffsetAssignment, ...]]
    ] = []

    for batch_index in range(batch_count):
        seed = base_seed + batch_index * max_attempts
        one_config = replace(
            loaded.config.optimization,
            restart_policy=RestartPolicy.fixed(1),
        )
        one = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            one_config,
            loaded.config.model.average_load_limit,
            seed,
            loaded.network.weight_mode,
            peak_objective,
        )
        full_config = replace(
            loaded.config.optimization,
            restart_policy=RestartPolicy.fixed(max_attempts),
        )

        def observe(record: RestartRecord, batch: int = batch_index) -> None:
            key = ("peak", batch, record.attempt_index)
            if key in existing:
                return
            writer.append(
                restart_record_dict(
                    record,
                    experiment_id=experiment_id,
                    input_hash=input_hash,
                    configuration_hash_value=config_hash,
                    network=network_prefix,
                    batch_index=batch,
                    phase="peak",
                )
            )
            existing.add(key)

        full = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            full_config,
            loaded.config.model.average_load_limit,
            seed,
            loaded.network.weight_mode,
            peak_objective,
            restart_observer=observe,
        )
        baseline = (one.objective, one.assignments)
        for checkpoint in checkpoints:
            objective, assignments = _best_prefix(
                baseline, full.restart_records, checkpoint
            )
            digest = hash_offset_assignments(assignments)
            prefix_rows.append(
                {
                    "批次": batch_index,
                    "seed起点": seed,
                    "总attempts": checkpoint,
                    "Nvio": objective.violation_count,
                    "Vvio": objective.violation_excess,
                    "Zss": objective.steady_peak,
                    "Qss": objective.sum_square_load,
                    "Zst": objective.startup_peak,
                    "Qst": objective.startup_sum_square_load,
                    "Kmax": objective.max_release_count,
                    "assignment_hash": digest,
                }
            )
        batch_endpoints.append(_best_prefix(baseline, full.restart_records, max_attempts))

    endpoint_best = min(batch_endpoints, key=lambda item: _candidate_key(*item))
    saturation_rows: list[dict[str, object]] = []
    checkpoint_status: dict[int, bool] = {}
    for checkpoint in checkpoints:
        rows = [row for row in prefix_rows if row["总attempts"] == checkpoint]
        endpoint_matches = 0
        for batch_index, row in enumerate(rows):
            endpoint = batch_endpoints[batch_index]
            if tuple(
                cast(int, row[name])
                for name in ("Nvio", "Vvio", "Zss", "Qss", "Zst", "Qst", "Kmax")
            ) == endpoint[0].as_tuple():
                endpoint_matches += 1
        current_best = min(
            rows,
            key=lambda row: (
                tuple(
                    cast(int, row[name])
                    for name in ("Nvio", "Vvio", "Zss", "Qss", "Zst", "Qst", "Kmax")
                ),
                str(row["assignment_hash"]),
            ),
        )
        current_key = tuple(
            cast(int, current_best[name])
            for name in ("Nvio", "Vvio", "Zss", "Qss", "Zst", "Qst", "Kmax")
        )
        matches_global = current_key == endpoint_best[0].as_tuple()
        global_objective_hit_rate = sum(
            tuple(
                cast(int, row[name])
                for name in (
                    "Nvio",
                    "Vvio",
                    "Zss",
                    "Qss",
                    "Zst",
                    "Qst",
                    "Kmax",
                )
            )
            == endpoint_best[0].as_tuple()
            for row in rows
        ) / batch_count
        within_rate = endpoint_matches / batch_count
        checkpoint_status[checkpoint] = matches_global and within_rate >= 0.95
        saturation_rows.append(
            {
                "总attempts": checkpoint,
                "跨批最好Zss": current_best["Zss"],
                "跨批最好Qss": current_best["Qss"],
                "达到各批80次结果比例": within_rate,
                "达到跨批80次最好目标": matches_global,
            }
        )
        saturation_rows[-1]["全局最好目标命中率"] = (
            global_objective_hit_rate
        )
    recommended = _recommended_checkpoint(checkpoints, checkpoint_status)
    _write_csv(results_dir / "restart_saturation.csv", saturation_rows)
    _write_csv(results_dir / "batch_results.csv", prefix_rows)
    summary: dict[str, object] = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "input_hash": input_hash,
        "configuration_hash": config_hash,
        "network": network_prefix,
        "objective_mode": "peak",
        "batch_count": batch_count,
        "max_attempts": max_attempts,
        "checkpoints": list(checkpoints),
        "recommended_fixed_attempts": recommended,
        "saturation_verified": recommended is not None,
        "max_attempts_reached_without_verified_saturation": recommended is None,
        "global_best_objective": list(endpoint_best[0].as_tuple()),
        "global_best_assignment_hash": hash_offset_assignments(endpoint_best[1]),
        "global_best_objective_hit_rate": sum(
            item[0].as_tuple() == endpoint_best[0].as_tuple()
            for item in batch_endpoints
        )
        / batch_count,
        "global_best_assignment_hit_rate": sum(
            item[1] == endpoint_best[1] for item in batch_endpoints
        )
        / batch_count,
        "endpoint_objective_distribution": {
            ",".join(str(value) for value in objective): sum(
                item[0].as_tuple() == objective for item in batch_endpoints
            )
            for objective in sorted(
                {item[0].as_tuple() for item in batch_endpoints}
            )
        },
        "distinct_endpoint_objectives": len(
            {item[0].as_tuple() for item in batch_endpoints}
        ),
        "distinct_endpoint_assignments": len(
            {hash_offset_assignments(item[1]) for item in batch_endpoints}
        ),
    }
    best_offsets = {
        item.message_name: item.offset_us for item in endpoint_best[1]
    }
    cycles = {
        message.name: message.cycle_time_us
        for message in loaded.network.messages
    }
    summary["batch_endpoints"] = [
        {
            "batch_index": batch_index,
            "objective": list(objective.as_tuple()),
            "assignment_hash": hash_offset_assignments(assignments),
            "offset_difference_from_global_best": sum(
                item.offset_us != best_offsets[item.message_name]
                for item in assignments
            ),
            "steady_phase_difference_from_global_best": sum(
                item.offset_us % cycles[item.message_name]
                != best_offsets[item.message_name] % cycles[item.message_name]
                for item in assignments
            ),
        }
        for batch_index, (objective, assignments) in enumerate(batch_endpoints)
    ]

    balanced_attempts = recommended or max_attempts
    balanced_rows: list[dict[str, object]] = []
    balanced_best: tuple[int, ...] | None = None
    last_improvement_batch = 0
    balanced_stable = False
    balanced_batches_run = 0
    for target_batches, no_improvement_window in ((10, 5), (20, 10), (30, 10)):
        while balanced_batches_run < target_batches:
            batch_index = balanced_batches_run
            seed = (
                base_seed
                + batch_count * max_attempts
                + batch_index * balanced_attempts
            )
            fixed_config = replace(
                loaded.config.optimization,
                restart_policy=RestartPolicy.fixed(balanced_attempts),
            )

            def observe_balanced_peak(
                record: RestartRecord, batch: int = batch_index
            ) -> None:
                key = ("balanced_peak_reference", batch, record.attempt_index)
                if key in existing:
                    return
                writer.append(
                    restart_record_dict(
                        record,
                        experiment_id=experiment_id,
                        input_hash=input_hash,
                        configuration_hash_value=config_hash,
                        network=network_prefix,
                        batch_index=batch,
                        phase="balanced_peak_reference",
                    )
                )
                existing.add(key)

            reference = run_gcls(
                loaded.network.messages,
                loaded.slot_map,
                fixed_config,
                loaded.config.model.average_load_limit,
                seed,
                loaded.network.weight_mode,
                ObjectiveConfig(mode=ObjectiveMode.PEAK),
                restart_observer=observe_balanced_peak,
            )

            def observe_balanced(
                record: RestartRecord, batch: int = batch_index
            ) -> None:
                key = ("balanced", batch, record.attempt_index)
                if key in existing:
                    return
                writer.append(
                    restart_record_dict(
                        record,
                        experiment_id=experiment_id,
                        input_hash=input_hash,
                        configuration_hash_value=config_hash,
                        network=network_prefix,
                        batch_index=batch,
                        phase="balanced",
                    )
                )
                existing.add(key)

            balanced = run_gcls(
                loaded.network.messages,
                loaded.slot_map,
                fixed_config,
                loaded.config.model.average_load_limit,
                seed,
                loaded.network.weight_mode,
                ObjectiveConfig(mode=ObjectiveMode.BALANCED),
                reference,
                observe_balanced,
            )
            physical_metrics = balanced.objective.metrics_tuple()
            if balanced_best is None or physical_metrics < balanced_best:
                balanced_best = physical_metrics
                last_improvement_batch = batch_index + 1
            balanced_rows.append(
                {
                    "batch_index": batch_index,
                    "seed_start": seed,
                    "objective": list(balanced.objective.as_tuple()),
                    "physical_metrics": list(physical_metrics),
                    "assignment_hash": hash_offset_assignments(
                        balanced.assignments
                    ),
                    "peak_budget_us": balanced.peak_budget_us,
                }
            )
            balanced_batches_run += 1
        assert balanced_best is not None
        hit_rate = sum(
            row["physical_metrics"] == list(balanced_best)
            for row in balanced_rows
        ) / balanced_batches_run
        balanced_stable = _balanced_is_stable(
            hit_rate,
            balanced_batches_run,
            last_improvement_batch,
            no_improvement_window,
        )
        if balanced_stable:
            break
    full_balanced_saturation_triggered = not balanced_stable
    full_balanced_endpoints: list[tuple[int, ...]] = []
    full_balanced_assignment_hashes: list[str] = []
    full_balanced_prefix_rows: list[dict[str, object]] = []
    if full_balanced_saturation_triggered:
        for batch_index in range(30):
            seed = (
                base_seed
                + batch_count * max_attempts
                + 30 * balanced_attempts
                + batch_index * max_attempts
            )
            fixed_config = replace(
                loaded.config.optimization,
                restart_policy=RestartPolicy.fixed(max_attempts),
            )

            def observe_full_peak(
                record: RestartRecord, batch: int = batch_index
            ) -> None:
                key = (
                    "balanced_full_peak_reference",
                    batch,
                    record.attempt_index,
                )
                if key in existing:
                    return
                writer.append(
                    restart_record_dict(
                        record,
                        experiment_id=experiment_id,
                        input_hash=input_hash,
                        configuration_hash_value=config_hash,
                        network=network_prefix,
                        batch_index=batch,
                        phase="balanced_full_peak_reference",
                    )
                )
                existing.add(key)

            reference = run_gcls(
                loaded.network.messages,
                loaded.slot_map,
                fixed_config,
                loaded.config.model.average_load_limit,
                seed,
                loaded.network.weight_mode,
                ObjectiveConfig(mode=ObjectiveMode.PEAK),
                restart_observer=observe_full_peak,
            )

            def observe_full(
                record: RestartRecord, batch: int = batch_index
            ) -> None:
                key = ("balanced_full", batch, record.attempt_index)
                if key in existing:
                    return
                writer.append(
                    restart_record_dict(
                        record,
                        experiment_id=experiment_id,
                        input_hash=input_hash,
                        configuration_hash_value=config_hash,
                        network=network_prefix,
                        batch_index=batch,
                        phase="balanced_full",
                    )
                )
                existing.add(key)

            result = run_gcls(
                loaded.network.messages,
                loaded.slot_map,
                fixed_config,
                loaded.config.model.average_load_limit,
                seed,
                loaded.network.weight_mode,
                ObjectiveConfig(mode=ObjectiveMode.BALANCED),
                reference,
                observe_full,
            )
            full_balanced_endpoints.append(result.objective.metrics_tuple())
            full_balanced_assignment_hashes.append(
                hash_offset_assignments(result.assignments)
            )
            if (
                result.pre_restart_objective is None
                or not result.pre_restart_assignments
            ):
                raise RuntimeError("balanced result lacks its pre-restart incumbent")
            baseline = (
                result.pre_restart_objective,
                result.pre_restart_assignments,
            )
            for checkpoint in checkpoints:
                objective, assignments = _best_prefix(
                    baseline, result.restart_records, checkpoint
                )
                full_balanced_prefix_rows.append(
                    {
                        "批次": batch_index,
                        "总attempts": checkpoint,
                        "完整物理指标": list(objective.metrics_tuple()),
                        "词典序比较键": list(objective.as_tuple()),
                        "assignment_hash": hash_offset_assignments(assignments),
                    }
                )
        _write_csv(
            results_dir / "balanced_full_saturation.csv",
            full_balanced_prefix_rows,
        )
    balanced_full_checkpoint_rates: dict[str, float] = {}
    if full_balanced_prefix_rows:
        for checkpoint in checkpoints:
            rows = [
                row
                for row in full_balanced_prefix_rows
                if row["总attempts"] == checkpoint
            ]
            rate = sum(
                tuple(cast(list[int], row["完整物理指标"]))
                == full_balanced_endpoints[batch_index]
                for batch_index, row in enumerate(rows)
            ) / len(full_balanced_endpoints)
            balanced_full_checkpoint_rates[str(checkpoint)] = rate
    summary["balanced_validation"] = {
        "fixed_attempts": balanced_attempts,
        "batches_run": balanced_batches_run,
        "stable": balanced_stable,
        "best_objective_hit_rate": (
            sum(
                row["physical_metrics"] == list(balanced_best)
                for row in balanced_rows
            )
            / balanced_batches_run
            if balanced_best is not None
            else 0.0
        ),
        "last_strict_improvement_batch": last_improvement_batch,
        "assignment_difference_does_not_trigger_escalation": True,
        "full_saturation_triggered": full_balanced_saturation_triggered,
        "full_saturation_distinct_objectives": len(set(full_balanced_endpoints)),
        "full_saturation_distinct_assignments": len(
            set(full_balanced_assignment_hashes)
        ),
        "full_saturation_best_physical_metrics": (
            list(min(full_balanced_endpoints))
            if full_balanced_endpoints
            else None
        ),
        "full_saturation_best_objective_hit_rate": (
            sum(
                metrics == min(full_balanced_endpoints)
                for metrics in full_balanced_endpoints
            )
            / len(full_balanced_endpoints)
            if full_balanced_endpoints
            else None
        ),
        "full_saturation_checkpoint_endpoint_hit_rates": (
            balanced_full_checkpoint_rates
        ),
        "batches": balanced_rows,
    }
    _derive_unique_assignments(
        jsonl_path, results_dir / "unique_assignments.json"
    )
    (results_dir / "batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    x = [cast(int, row["总attempts"]) for row in saturation_rows]
    rates = [cast(float, row["达到各批80次结果比例"]) for row in saturation_rows]
    cache_dir = output / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg", force=True)
    plt = importlib.import_module("matplotlib.pyplot")
    fig, axis = plt.subplots(figsize=(9, 5))
    axis.plot(x, rates, marker="o")
    axis.axhline(0.95, color="tab:red", linestyle="--", label="95% criterion")
    axis.set_xlabel("Total attempts")
    axis.set_ylabel("Rate matching each batch's 80-attempt result")
    axis.set_ylim(0, 1.05)
    axis.grid(alpha=0.3)
    axis.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / f"{network_prefix}_restart_saturation.png", dpi=160)
    plt.close(fig)

    global_hit_rates = [
        cast(float, row["全局最好目标命中率"])
        for row in saturation_rows
    ]
    fig, axis = plt.subplots(figsize=(9, 5))
    axis.plot(x, global_hit_rates, marker="o", color="tab:green")
    axis.set_xlabel("Total attempts")
    axis.set_ylabel("Batch hit rate for global best objective")
    axis.set_ylim(0, 1.05)
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(
        plots_dir / f"{network_prefix}_global_best_hit_rate.png", dpi=160
    )
    plt.close(fig)

    distribution: dict[tuple[int, int], int] = {}
    for objective, _assignments in batch_endpoints:
        point = (objective.steady_peak, objective.sum_square_load)
        distribution[point] = distribution.get(point, 0) + 1
    fig, axis = plt.subplots(figsize=(9, 5))
    for (zss, qss), count in sorted(distribution.items()):
        axis.scatter(zss, qss, s=40 + count * 15)
        axis.annotate(f"{count} batches", (zss, qss))
    axis.set_xlabel("Zss (us)")
    axis.set_ylabel("Qss (us^2)")
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(
        plots_dir / f"{network_prefix}_batch_objective_distribution.png",
        dpi=160,
    )
    plt.close(fig)
    if balanced_full_checkpoint_rates:
        balanced_rates = [
            balanced_full_checkpoint_rates[str(checkpoint)]
            for checkpoint in checkpoints
        ]
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.plot(checkpoints, balanced_rates, marker="o")
        axis.axhline(
            0.90, color="tab:red", linestyle="--", label="90% criterion"
        )
        axis.set_xlabel("Total attempts")
        axis.set_ylabel("Rate matching each balanced batch endpoint")
        axis.set_ylim(0, 1.05)
        axis.grid(alpha=0.3)
        axis.legend()
        fig.tight_layout()
        fig.savefig(
            plots_dir / f"{network_prefix}_balanced_restart_saturation.png",
            dpi=160,
        )
        plt.close(fig)
    return summary
