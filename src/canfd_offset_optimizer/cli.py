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

from .config import ProjectConfig
from .exceptions import CanfdOptimizerError
from .models import AlgorithmComparisonResult, WeightMode
from .optimization.comparison import compare_algorithms
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
from .reporting.plotter import write_load_plots
from .reporting.summary_writer import write_summary
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
    for command in (optimize, compare, compare_weights):
        command.add_argument("--dbc", type=Path, required=True)
        command.add_argument("--arxml", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--seed", type=int, default=0)
        command.add_argument("--restarts", type=int)
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
    return parser


def _with_restart_override(config: ProjectConfig, restarts: int | None) -> ProjectConfig:
    if restarts is None:
        return config
    if restarts < 0:
        raise ValueError("--restarts must be non-negative")
    return replace(
        config,
        optimization=replace(config.optimization, random_restarts=restarts),
    )


def _log_loaded(loaded: LoadedProject) -> None:
    logger = logging.getLogger(__name__)
    logger.info("Loaded %d periodic messages", len(loaded.network.messages))
    for field, source in loaded.network.field_sources:
        logger.info("Field source %s=%s", field, source)
    for warning in loaded.network.warnings:
        logger.warning(warning)


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
) -> AlgorithmComparisonResult:
    result = compare_algorithms(
        loaded.network.messages,
        loaded.slot_map,
        config.optimization,
        config.model.average_load_limit,
        seed,
        loaded.network.weight_mode,
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
    write_comparison_summary(output, loaded.network, config, result)
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
        if args.command == "compare-weights":
            mode_results: dict[
                WeightMode, tuple[LoadedProject, ProjectConfig, AlgorithmComparisonResult]
            ] = {}
            for mode in (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US):
                mode_output = output / mode.value
                with _additional_log_file(mode_output / "logs" / "run.log"):
                    logger.info("Starting weight mode %s", mode.value)
                    mode_loaded = load_project(
                        args.dbc,
                        args.arxml,
                        args.config,
                        weight_mode_override=mode,
                        channel_override=args.channel,
                    )
                    mode_config = _with_restart_override(
                        mode_loaded.config, args.restarts
                    )
                    _log_loaded(mode_loaded)
                    mode_result = _run_comparison_bundle(
                        mode_output,
                        mode_loaded,
                        mode_config,
                        args.seed,
                        report_prefix,
                    )
                    mode_results[mode] = (mode_loaded, mode_config, mode_result)
            payload_loaded, payload_config, payload_result = mode_results[
                WeightMode.PAYLOAD_BYTES
            ]
            physical_loaded, physical_config, physical_result = mode_results[
                WeightMode.FRAME_TIME_US
            ]
            write_weight_mode_reports(
                output,
                payload_loaded.network,
                payload_config,
                payload_result,
                physical_loaded.network,
                physical_config,
                physical_result,
                report_prefix,
            )
            if output.name.casefold() == report_prefix.casefold():
                aggregate_path = write_all_network_offsets_report(output.parent)
                logger.info("All-network message table written to %s", aggregate_path)
            logger.info("Dual-weight reports written under %s", output)
            return 0
        weight_mode_override = (
            WeightMode(args.weight_mode)
            if args.command == "compare" and args.weight_mode is not None
            else None
        )
        loaded = load_project(
            args.dbc,
            args.arxml,
            args.config,
            weight_mode_override=weight_mode_override,
            channel_override=args.channel,
        )
        config = _with_restart_override(loaded.config, args.restarts)
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
            write_summary(output, loaded.network, config, result)
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
