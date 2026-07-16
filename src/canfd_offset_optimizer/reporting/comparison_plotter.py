"""! @file comparison_plotter.py
@brief 从只读阶段快照生成启动与稳态多算法对比图。
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from ..models import AlgorithmComparisonResult, NetworkModel, WeightMode
from ..optimization.objective import slot_load_threshold_us
from .filenames import prefixed_report_name


def write_comparison_plots(
    output_root: Path,
    network: NetworkModel,
    result: AlgorithmComparisonResult,
    load_limit: float,
    report_prefix: str | None = None,
) -> tuple[Path, Path]:
    """! @brief 生成共享纵轴的 steady/startup 五阶段对比图。"""
    cache_dir = output_root / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg")
    plt = importlib.import_module("matplotlib.pyplot")

    plot_dir = output_root / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    physical = network.weight_mode is WeightMode.FRAME_TIME_US
    unit = "microseconds" if physical else "payload-byte weight"
    threshold = slot_load_threshold_us(
        network.steady_window.slot_width_us, load_limit
    )
    colors = ("#7F8C8D", "#95A5A6", "#3498DB", "#2ECC71", "#9B59B6")
    paths: list[Path] = []
    for window_name in ("steady", "startup"):
        figure, axes = plt.subplots(
            len(result.stages),
            1,
            figsize=(12, 2.2 * len(result.stages)),
            sharex=True,
            sharey=True,
        )
        for axis, stage, color in zip(axes, result.stages, colors, strict=True):
            loads = (
                stage.steady_slot_loads
                if window_name == "steady"
                else stage.startup_slot_loads
            )
            axis.bar(range(len(loads)), loads, color=color, width=0.85)
            if physical:
                axis.axhline(threshold, color="#C0392B", linestyle="--", linewidth=1)
            peak = stage.objective.steady_peak if window_name == "steady" else stage.objective.startup_peak
            axis.set_title(f"{stage.name} | peak={peak}", loc="left", fontsize=9)
            axis.grid(axis="y", alpha=0.2)
        axes[-1].set_xlabel("Slot index")
        figure.supylabel(f"Weighted load ({unit})")
        figure.suptitle(f"{window_name.capitalize()} load comparison")
        figure.tight_layout()
        path = plot_dir / prefixed_report_name(
            f"{window_name}_load_comparison.png", report_prefix
        )
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(path)
    return paths[0], paths[1]
