"""! @file cli.py
@brief 加载、GCLS 优化、报告和错误码的命令行编排。

@author 篠見由紀
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .exceptions import CanfdOptimizerError
from .optimization.gcls import run_gcls
from .parsers.project_loader import load_project
from .reporting.csv_writer import write_csv_reports
from .reporting.plotter import write_load_plots
from .reporting.summary_writer import write_summary


def build_parser() -> argparse.ArgumentParser:
    """! @brief 构造支持 optimize 子命令的参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="canfd-offset",
        description="Balance periodic CAN FD first-release offsets with GCLS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    optimize = subparsers.add_parser("optimize", help="optimize periodic message offsets")
    optimize.add_argument("--dbc", type=Path, required=True)
    optimize.add_argument("--arxml", type=Path, required=True)
    optimize.add_argument("--config", type=Path, required=True)
    optimize.add_argument("--output", type=Path, required=True)
    optimize.add_argument("--seed", type=int, default=0)
    optimize.add_argument("--restarts", type=int)
    optimize.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


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
        loaded = load_project(args.dbc, args.arxml, args.config)
        config = loaded.config
        if args.restarts is not None:
            if args.restarts < 0:
                parser.error("--restarts must be non-negative")
            config = replace(
                config,
                optimization=replace(
                    config.optimization, random_restarts=args.restarts
                ),
            )
        logger.info("Loaded %d periodic messages", len(loaded.network.messages))
        for field, source in loaded.network.field_sources:
            logger.info("Field source %s=%s", field, source)
        for warning in loaded.network.warnings:
            logger.warning(warning)
        result = run_gcls(
            loaded.network.messages,
            loaded.slot_map,
            config.optimization,
            config.model.average_load_limit,
            args.seed,
            weight_mode=loaded.network.weight_mode,
        )
        write_csv_reports(output, loaded.network, result, config.model.average_load_limit)
        write_load_plots(output, loaded.network, result, config.model.average_load_limit)
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
