"""! @file cli.py
@brief 加载、GCLS 优化、报告和错误码的命令行编排。

@author 篠見由紀
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator, Sequence

from .config import ProjectConfig, RestartPolicy
from .diagnostics.cpsat_verify import run_cpsat_verification
from .diagnostics.candidate_pool_study import (
    DEFAULT_POOL_SIZES,
    run_candidate_pool_study,
)
from .diagnostics.restart_study import DEFAULT_CHECKPOINTS, run_restart_study
from .diagnostics.tolerance_study import DEFAULT_TOLERANCES, run_tolerance_scan
from .exceptions import CanfdOptimizerError
from .models import (
    AlgorithmComparisonResult,
    ObjectiveMode,
    OptimizationResult,
    RestartMode,
    WeightMode,
)
from .optimization.comparison import (
    compare_algorithms,
    extract_peak_optimization_result,
)
from .optimization.gcls import run_gcls
from .parsers.project_loader import LoadedProject, load_project
from .reporting.comparison_plotter import write_comparison_plots
from .reporting.comparison_writer import (
    write_comparison_csv_reports,
    write_comparison_summary,
)
from .reporting.congestion_plotter import write_congestion_plots
from .reporting.csv_writer import write_csv_reports
from .reporting.filenames import infer_report_prefix
from .reporting.objective_mode_plotter import write_objective_mode_plot
from .reporting.objective_mode_writer import (
    write_all_network_objective_report,
    write_objective_mode_reports,
)
from .reporting.plotter import write_load_plots
from .reporting.summary_writer import write_summary
from .reporting.summary_writer import combined_input_hash
from .reporting.restart_writer import configuration_hash, write_restart_jsonl
from .reporting.weight_mode_writer import (
    write_all_network_offsets_report,
    write_weight_mode_reports,
)


def build_parser() -> argparse.ArgumentParser:
    """! @brief 构造支持 optimize/compare 子命令的参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="canfd-offset",
        description="Balance periodic CAN FD first-release offsets with GCLS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    optimize = subparsers.add_parser("optimize", help="optimize periodic message offsets")
    compare = subparsers.add_parser("compare", help="compare optimization stages")
    compare_weights = subparsers.add_parser(
        "compare-weights",
        help="run payload-byte and physical frame-time comparisons",
    )
    analyze_restarts = subparsers.add_parser(
        "analyze-restarts", help="analyze Peak restart stability and saturation"
    )
    scan_tolerances = subparsers.add_parser(
        "scan-tolerances", help="scan balanced relative peak tolerances"
    )
    verify_cpsat = subparsers.add_parser(
        "verify-cpsat", help="verify balanced Qss with optional OR-Tools CP-SAT"
    )
    analyze_candidate_pools = subparsers.add_parser(
        "analyze-candidate-pools",
        help="compare diverse Peak candidate-pool sizes for Balanced search",
    )
    all_commands = (
        optimize,
        compare,
        compare_weights,
        analyze_restarts,
        scan_tolerances,
        verify_cpsat,
        analyze_candidate_pools,
    )
    for command in all_commands:
        command.add_argument("--dbc", type=Path, required=True)
        command.add_argument("--arxml", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--seed", type=int, default=0)
        command.add_argument("--restarts", type=int)
        command.add_argument(
            "--restart-mode",
            choices=tuple(mode.value for mode in RestartMode),
            help="override the normalized restart policy",
        )
        command.add_argument(
            "--restart-attempts",
            type=int,
            help="total attempts; required with --restart-mode fixed",
        )
        command.add_argument(
            "--channel",
            help="select an ARXML Controller SHORT-NAME and override network.channel",
        )
        command.add_argument(
            "--log-level",
            choices=("DEBUG", "INFO", "WARNING", "ERROR"),
            default="INFO",
        )
    compare.add_argument(
        "--weight-mode",
        choices=tuple(mode.value for mode in WeightMode),
        help="override model.weight_mode for this comparison",
    )
    for command in (optimize, compare):
        command.add_argument(
            "--objective-mode",
            choices=tuple(mode.value for mode in ObjectiveMode),
            help="override objective.mode for this run",
        )
    analyze_restarts.add_argument("--batch-count", type=int, default=30)
    analyze_restarts.add_argument("--max-attempts", type=int, default=80)
    analyze_restarts.add_argument(
        "--checkpoints",
        default=",".join(str(value) for value in DEFAULT_CHECKPOINTS),
    )
    analyze_restarts.add_argument("--resume", action="store_true")
    scan_tolerances.add_argument(
        "--tolerances",
        default=",".join(str(value) for value in DEFAULT_TOLERANCES),
        help="comma-separated relative values, for example 0,0.05,0.20",
    )
    verify_cpsat.add_argument("--tolerance", type=float, default=0.05)
    verify_cpsat.add_argument("--time-limit-seconds", type=float, default=300.0)
    verify_cpsat.add_argument("--solver-seed", type=int, default=0)
    analyze_candidate_pools.add_argument(
        "--pool-sizes",
        default=",".join(str(value) for value in DEFAULT_POOL_SIZES),
        help="comma-separated subset of 1,4,8,16,32",
    )
    return parser


def _with_restart_override(config: ProjectConfig, restarts: int | None) -> ProjectConfig:
    if restarts is None:
        return config
    if restarts < 0:
        raise ValueError("--restarts must be non-negative")
    return replace(
        config,
        optimization=replace(
            config.optimization,
            restart_policy=RestartPolicy.fixed(
                restarts + 1,
                source_kind="legacy",
                legacy_additional_restarts=restarts,
            ),
        ),
    )


def _with_restart_override_loaded(
    loaded: LoadedProject, restarts: int | None
) -> LoadedProject:
    """Apply ``--restarts`` while preserving its requested value and source for reports."""
    if restarts is None:
        return loaded
    config = _with_restart_override(loaded.config, restarts)
    sources = dict(loaded.network.field_sources)
    sources["random_restarts"] = "CLI --restarts override"
    overrides = dict(loaded.network.cli_overrides)
    overrides["random_restarts"] = str(restarts)
    warnings = loaded.network.warnings + (
        f"CLI overrides optimization.random_restarts to {restarts}",
        "--restarts is deprecated; use --restart-mode fixed --restart-attempts",
    )
    return replace(
        loaded,
        config=config,
        network=replace(
            loaded.network,
            field_sources=tuple(sorted(sources.items())),
            cli_overrides=tuple(sorted(overrides.items())),
            warnings=warnings,
        ),
    )


def _with_restart_policy_overrides(
    loaded: LoadedProject,
    legacy_restarts: int | None,
    mode_value: str | None,
    total_attempts: int | None,
) -> LoadedProject:
    """Normalize legacy/new CLI restart options into one audited policy."""
    existing = loaded.config.optimization.restart_policy
    if legacy_restarts is not None and (mode_value is not None or total_attempts is not None):
        raise ValueError("--restarts conflicts with --restart-mode/--restart-attempts")
    if legacy_restarts is not None:
        return _with_restart_override_loaded(loaded, legacy_restarts)
    if mode_value is None and total_attempts is None:
        return loaded
    if existing.source_kind == "legacy":
        raise ValueError("new restart CLI options conflict with YAML random_restarts")
    if mode_value is None:
        raise ValueError("--restart-attempts requires --restart-mode fixed")
    mode = RestartMode(mode_value)
    if mode is RestartMode.FIXED:
        if total_attempts is None or total_attempts <= 0:
            raise ValueError(
                "--restart-mode fixed requires positive --restart-attempts"
            )
        selected = RestartPolicy.fixed(total_attempts, source_kind="cli")
    else:
        if total_attempts is not None:
            raise ValueError(
                "--restart-attempts is only valid with --restart-mode fixed"
            )
        selected = replace(existing, mode=RestartMode.ADAPTIVE, total_attempts=None, source_kind="cli")
    sources = dict(loaded.network.field_sources)
    sources["restart_policy"] = "CLI --restart-mode override"
    overrides = dict(loaded.network.cli_overrides)
    overrides["restart_mode"] = selected.mode.value
    if selected.total_attempts is not None:
        overrides["restart_total_attempts"] = str(selected.total_attempts)
    return replace(
        loaded,
        config=replace(
            loaded.config,
            optimization=replace(
                loaded.config.optimization, restart_policy=selected
            ),
        ),
        network=replace(
            loaded.network,
            field_sources=tuple(sorted(sources.items())),
            cli_overrides=tuple(sorted(overrides.items())),
            warnings=loaded.network.warnings
            + (f"CLI selects restart_policy.mode={selected.mode.value}",),
        ),
    )


def _log_loaded(loaded: LoadedProject) -> None:
    logger = logging.getLogger(__name__)
    logger.info("Loaded %d periodic messages", len(loaded.network.messages))
    for field, source in loaded.network.field_sources:
        logger.info("Field source %s=%s", field, source)
    for warning in loaded.network.warnings:
        logger.warning(warning)


def _with_objective_mode(loaded: LoadedProject, mode: ObjectiveMode) -> LoadedProject:
    """Create an audited view of one loaded physical network for an objective experiment."""
    sources = dict(loaded.network.field_sources)
    sources["objective_mode"] = "compare-weights fixed physical objective experiment"
    warnings = loaded.network.warnings
    overrides = dict(loaded.network.cli_overrides)
    overrides["objective_mode_experiment"] = mode.value
    if loaded.config.objective.mode is not mode:
        warnings += (
            f"compare-weights selects physical objective.mode={mode.value}",
        )
    return replace(
        loaded,
        config=replace(
            loaded.config,
            objective=replace(loaded.config.objective, mode=mode),
        ),
        network=replace(
            loaded.network,
            warnings=warnings,
            field_sources=tuple(sorted(sources.items())),
            cli_overrides=tuple(sorted(overrides.items())),
        ),
    )


def _log_comparison(result: AlgorithmComparisonResult) -> None:
    logger = logging.getLogger(__name__)
    for stage in result.stages:
        logger.info(
            "Comparison stage %s objective=%s evaluations=%d accepted=%d",
            stage.name,
            stage.objective.as_tuple(),
            stage.evaluation_count,
            stage.accepted_moves,
        )
    for record in result.restart_records:
        logger.info(
            "Comparison restart seed=%d objective=%s",
            record.seed,
            record.objective.as_tuple(),
        )
    logger.info("Best comparison objective: %s", result.stage("gcls").objective.as_tuple())


def _run_comparison_bundle(
    output: Path,
    loaded: LoadedProject,
    config: ProjectConfig,
    seed: int,
    report_prefix: str,
    peak_reference_result: OptimizationResult | None = None,
) -> AlgorithmComparisonResult:
    result = compare_algorithms(
        loaded.network.messages,
        loaded.slot_map,
        config.optimization,
        config.model.average_load_limit,
        seed,
        loaded.network.weight_mode,
        config.objective,
        peak_reference_result,
    )
    write_comparison_csv_reports(
        output,
        loaded.network,
        result,
        config.model.average_load_limit,
        report_prefix,
    )
    write_comparison_plots(
        output,
        loaded.network,
        result,
        config.model.average_load_limit,
        report_prefix,
    )
    write_congestion_plots(output, loaded.network, result, report_prefix)
    write_comparison_summary(
        output, loaded.network, config, result, report_prefix
    )
    write_restart_jsonl(
        output / "results" / f"{report_prefix}_restart_records.jsonl",
        result.restart_records,
        experiment_id=(
            f"{report_prefix}-{loaded.network.weight_mode.value}-"
            f"{config.objective.mode.value}-{seed}"
        ),
        input_hash=combined_input_hash(loaded.network.input_files),
        configuration_hash_value=configuration_hash(config),
        network=report_prefix,
    )
    if result.peak_reference_restart_records:
        write_restart_jsonl(
            output
            / "results"
            / f"{report_prefix}_peak_reference_restart_records.jsonl",
            result.peak_reference_restart_records,
            experiment_id=(
                f"{report_prefix}-{loaded.network.weight_mode.value}-peak-reference-{seed}"
            ),
            input_hash=combined_input_hash(loaded.network.input_files),
            configuration_hash_value=configuration_hash(config),
            network=report_prefix,
            phase="peak_reference",
        )
    _log_comparison(result)
    return result


@contextmanager
def _additional_log_file(path: Path) -> Iterator[None]:
    """Mirror one weight-mode run into its own complete log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8", mode="w")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


def _configure_logging(output_root: Path, level_name: str) -> Path:
    """! @brief 初始化标准库日志并返回稳定 run.log 路径。"""
    log_dir = output_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run.log"
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level_name))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return log_path


def main(argv: Sequence[str] | None = None) -> int:
    """! @brief 执行命令行应用并返回进程退出码。

    @return 成功为 0，可定位输入/配置错误为 2，意外错误为 3。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    output: Path = args.output
    try:
        log_path = _configure_logging(output, args.log_level)
    except OSError as exc:
        print(f"error: cannot initialize output logging under {output}: {exc}", file=sys.stderr)
        return 2
    logger = logging.getLogger(__name__)
    try:
        report_prefix = infer_report_prefix(args.dbc, output.name)
        if args.restarts is not None and args.restarts < 0:
            parser.error("--restarts must be non-negative")
        if args.command in {
            "analyze-restarts",
            "scan-tolerances",
            "verify-cpsat",
            "analyze-candidate-pools",
        }:
            diagnostic_loaded = load_project(
                args.dbc,
                args.arxml,
                args.config,
                weight_mode_override=WeightMode.FRAME_TIME_US,
                channel_override=args.channel,
                objective_mode_override=(
                    ObjectiveMode.BALANCED
                    if args.command == "analyze-candidate-pools"
                    else ObjectiveMode.PEAK
                ),
            )
            diagnostic_loaded = _with_restart_policy_overrides(
                diagnostic_loaded,
                args.restarts,
                args.restart_mode,
                args.restart_attempts,
            )
            _log_loaded(diagnostic_loaded)
            diagnostic_policy = diagnostic_loaded.config.optimization.restart_policy
            diagnostic_attempts = (
                diagnostic_policy.total_attempts
                if diagnostic_policy.mode is RestartMode.FIXED
                else None
            )
            if args.command == "analyze-restarts":
                if (
                    args.restarts is not None
                    or args.restart_mode is not None
                    or args.restart_attempts is not None
                ):
                    raise CanfdOptimizerError(
                        "analyze-restarts controls attempts with --max-attempts; "
                        "do not combine restart policy CLI options"
                    )
                try:
                    checkpoints = tuple(
                        int(value.strip())
                        for value in args.checkpoints.split(",")
                        if value.strip()
                    )
                except ValueError as exc:
                    raise CanfdOptimizerError(
                        "--checkpoints must contain comma-separated integers"
                    ) from exc
                run_restart_study(
                    diagnostic_loaded,
                    output,
                    report_prefix,
                    base_seed=args.seed,
                    batch_count=args.batch_count,
                    max_attempts=args.max_attempts,
                    checkpoints=checkpoints,
                    resume=args.resume,
                )
            elif args.command == "scan-tolerances":
                try:
                    tolerances = tuple(
                        float(value.strip())
                        for value in args.tolerances.split(",")
                        if value.strip()
                    )
                except ValueError as exc:
                    raise CanfdOptimizerError(
                        "--tolerances must contain comma-separated numbers"
                    ) from exc
                run_tolerance_scan(
                    diagnostic_loaded,
                    output,
                    report_prefix,
                    seed=args.seed,
                    total_attempts=diagnostic_attempts,
                    tolerances=tolerances,
                )
            elif args.command == "verify-cpsat":
                run_cpsat_verification(
                    diagnostic_loaded,
                    output,
                    report_prefix,
                    seed=args.seed,
                    total_attempts=diagnostic_attempts,
                    tolerance=args.tolerance,
                    time_limit_seconds=args.time_limit_seconds,
                    solver_seed=args.solver_seed,
                )
            else:
                try:
                    pool_sizes = tuple(
                        int(value.strip())
                        for value in args.pool_sizes.split(",")
                        if value.strip()
                    )
                except ValueError as exc:
                    raise CanfdOptimizerError(
                        "--pool-sizes must contain comma-separated integers"
                    ) from exc
                run_candidate_pool_study(
                    diagnostic_loaded,
                    output,
                    report_prefix,
                    seed=args.seed,
                    total_attempts=diagnostic_attempts,
                    pool_sizes=pool_sizes,
                )
            logger.info("Diagnostic reports written under %s", output)
            return 0
        if args.command == "compare-weights":
            payload_output = output / WeightMode.PAYLOAD_BYTES.value
            with _additional_log_file(payload_output / "logs" / "run.log"):
                payload_loaded = load_project(
                    args.dbc,
                    args.arxml,
                    args.config,
                    weight_mode_override=WeightMode.PAYLOAD_BYTES,
                    channel_override=args.channel,
                )
                payload_loaded = _with_restart_policy_overrides(
                    payload_loaded,
                    args.restarts,
                    args.restart_mode,
                    args.restart_attempts,
                )
                payload_config = payload_loaded.config
                _log_loaded(payload_loaded)
                payload_result = _run_comparison_bundle(
                    payload_output,
                    payload_loaded,
                    payload_config,
                    args.seed,
                    report_prefix,
                )

            physical_base = load_project(
                args.dbc,
                args.arxml,
                args.config,
                weight_mode_override=WeightMode.FRAME_TIME_US,
                channel_override=args.channel,
            )
            physical_mode_results: dict[ObjectiveMode, AlgorithmComparisonResult] = {}
            physical_mode_configs: dict[ObjectiveMode, ProjectConfig] = {}
            physical_mode_loaded: dict[ObjectiveMode, LoadedProject] = {}
            peak_reference: OptimizationResult | None = None
            for objective_mode in (
                ObjectiveMode.PEAK,
                ObjectiveMode.BALANCED,
                ObjectiveMode.VARIANCE,
            ):
                mode_loaded = _with_objective_mode(physical_base, objective_mode)
                mode_loaded = _with_restart_policy_overrides(
                    mode_loaded,
                    args.restarts,
                    args.restart_mode,
                    args.restart_attempts,
                )
                mode_config = mode_loaded.config
                mode_output = (
                    output / WeightMode.FRAME_TIME_US.value
                    if objective_mode is ObjectiveMode.BALANCED
                    else output / "objective_modes" / objective_mode.value
                )
                with _additional_log_file(mode_output / "logs" / "run.log"):
                    logger.info("Starting physical objective mode %s", objective_mode.value)
                    _log_loaded(mode_loaded)
                    mode_result = _run_comparison_bundle(
                        mode_output,
                        mode_loaded,
                        mode_config,
                        args.seed,
                        report_prefix,
                        peak_reference,
                    )
                physical_mode_results[objective_mode] = mode_result
                physical_mode_configs[objective_mode] = mode_config
                physical_mode_loaded[objective_mode] = mode_loaded
                if objective_mode is ObjectiveMode.PEAK:
                    peak_reference = extract_peak_optimization_result(mode_result)
            physical_loaded = physical_mode_loaded[ObjectiveMode.BALANCED]
            physical_config = physical_mode_configs[ObjectiveMode.BALANCED]
            physical_result = physical_mode_results[ObjectiveMode.BALANCED]
            write_weight_mode_reports(
                output,
                payload_loaded.network,
                payload_config,
                payload_result,
                physical_loaded.network,
                physical_config,
                physical_result,
                report_prefix,
                physical_mode_results,
            )
            write_objective_mode_reports(
                output,
                physical_loaded.network,
                physical_mode_configs,
                physical_mode_results,
                report_prefix,
            )
            write_objective_mode_plot(
                output,
                physical_loaded.network,
                physical_mode_results,
                report_prefix,
            )
            if output.name.casefold() == report_prefix.casefold():
                aggregate_path = write_all_network_offsets_report(output.parent)
                logger.info("All-network message table written to %s", aggregate_path)
                objective_aggregate_path = write_all_network_objective_report(
                    output.parent
                )
                logger.info(
                    "All-network objective table written to %s",
                    objective_aggregate_path,
                )
            logger.info("Dual-weight reports written under %s", output)
            return 0
        weight_mode_override = (
            WeightMode(args.weight_mode)
            if args.command == "compare" and args.weight_mode is not None
            else None
        )
        objective_mode_override = (
            ObjectiveMode(args.objective_mode)
            if args.command in {"optimize", "compare"}
            and args.objective_mode is not None
            else None
        )
        loaded = load_project(
            args.dbc,
            args.arxml,
            args.config,
            weight_mode_override=weight_mode_override,
            channel_override=args.channel,
            objective_mode_override=objective_mode_override,
        )
        loaded = _with_restart_policy_overrides(
            loaded,
            args.restarts,
            args.restart_mode,
            args.restart_attempts,
        )
        config = loaded.config
        _log_loaded(loaded)
        if args.command == "compare":
            _run_comparison_bundle(output, loaded, config, args.seed, report_prefix)
        else:
            result = run_gcls(
                loaded.network.messages,
                loaded.slot_map,
                config.optimization,
                config.model.average_load_limit,
                args.seed,
                weight_mode=loaded.network.weight_mode,
                objective_config=config.objective,
            )
            write_csv_reports(
                output,
                loaded.network,
                result,
                config.model.average_load_limit,
                report_prefix,
            )
            write_load_plots(
                output,
                loaded.network,
                result,
                config.model.average_load_limit,
                report_prefix,
            )
            write_summary(
                output, loaded.network, config, result, report_prefix
            )
            write_restart_jsonl(
                output / "results" / f"{report_prefix}_restart_records.jsonl",
                result.restart_records,
                experiment_id=(
                    f"{report_prefix}-{loaded.network.weight_mode.value}-"
                    f"{result.objective.mode.value}-{args.seed}"
                ),
                input_hash=combined_input_hash(loaded.network.input_files),
                configuration_hash_value=configuration_hash(config),
                network=report_prefix,
            )
            if result.peak_reference_restart_records:
                write_restart_jsonl(
                    output
                    / "results"
                    / f"{report_prefix}_peak_reference_restart_records.jsonl",
                    result.peak_reference_restart_records,
                    experiment_id=(
                        f"{report_prefix}-{loaded.network.weight_mode.value}-"
                        f"peak-reference-{args.seed}"
                    ),
                    input_hash=combined_input_hash(loaded.network.input_files),
                    configuration_hash_value=configuration_hash(config),
                    network=report_prefix,
                    phase="peak_reference",
                )
            logger.info("Best objective: %s", result.objective.as_tuple())
        logger.info("Reports written under %s", output)
        return 0
    except CanfdOptimizerError as exc:
        logger.error("%s", exc, exc_info=True)
        print(f"error: {exc} (details: {log_path})", file=sys.stderr)
        return 2
    except OSError as exc:
        logger.error("output failure: %s", exc, exc_info=True)
        print(f"error: cannot write output: {exc} (details: {log_path})", file=sys.stderr)
        return 2
    except Exception as exc:  # CLI boundary records unexpected failures before returning.
        logger.critical("unexpected failure\n%s", traceback.format_exc())
        if args.log_level == "DEBUG":
            traceback.print_exc()
        else:
            print(f"unexpected error: {exc} (details: {log_path})", file=sys.stderr)
        return 3
