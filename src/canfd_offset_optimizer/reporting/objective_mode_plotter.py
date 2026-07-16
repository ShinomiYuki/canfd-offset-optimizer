"""! @file objective_mode_plotter.py
@brief 绘制原始方案与三种物理目标模式的稳态平坦度对比。
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from ..models import AlgorithmComparisonResult, NetworkModel, ObjectiveMode
from .filenames import prefixed_report_name
from .objective_mode_writer import load_statistics


def write_objective_mode_plot(
    output_root: Path,
    network: NetworkModel,
    results: dict[ObjectiveMode, AlgorithmComparisonResult],
    report_prefix: str | None = None,
) -> Path:
    """! @brief 生成共享纵轴的稳态负载曲线和方差指标图。"""
    cache_dir = output_root / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg")
    plt: Any = importlib.import_module("matplotlib.pyplot")
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    balanced = results[ObjectiveMode.BALANCED]
    series = [("DBC原始方案", balanced.stage("original"))] + [
        (mode.value, results[mode].stage("gcls"))
        for mode in (ObjectiveMode.PEAK, ObjectiveMode.BALANCED, ObjectiveMode.VARIANCE)
    ]
    figure, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True, sharey=True)
    colors = ("#7F8C8D", "#3498DB", "#2ECC71", "#9B59B6")
    window = network.steady_window
    times_ms = tuple(
        (window.start_us + slot * window.slot_width_us) / 1_000
        for slot in range(window.slot_count)
    )
    for axis, (label, stage), color in zip(axes, series, colors, strict=True):
        loads = stage.steady_slot_loads
        _, variance, standard_deviation = load_statistics(loads)
        axis.plot(times_ms, loads, color=color, linewidth=1.2)
        axis.fill_between(times_ms, loads, color=color, alpha=0.18)
        axis.set_title(
            f"{label} | Zss={max(loads, default=0)} μs | "
            f"Qss={sum(load * load for load in loads)} | σ={standard_deviation:.2f} μs",
            loc="left",
            fontsize=9,
        )
        axis.grid(axis="y", alpha=0.2)
        axis.text(0.995, 0.88, f"Var={variance:.2f}", transform=axis.transAxes, ha="right")
    axes[-1].set_xlabel(
        f"稳态窗口实际时间（ms，每格 {window.slot_width_us / 1_000:g} ms）"
    )
    figure.supylabel("保守帧时间负载（μs）")
    figure.suptitle(f"{network.channel.name}：目标模式稳态平坦度对比")
    figure.tight_layout()
    plot_dir = output_root / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    path = plot_dir / prefixed_report_name(
        "steady_objective_mode_comparison.png", report_prefix
    )
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return path
