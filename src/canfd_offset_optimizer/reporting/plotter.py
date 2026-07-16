"""! @file plotter.py
@brief 仅消费结果数组并输出启动与稳态负载图。

@author 篠見由紀
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from ..models import NetworkModel, OptimizationResult, WeightMode
from ..optimization.objective import slot_load_threshold_us
from .filenames import prefixed_report_name


def write_load_plots(
    output_root: Path,
    network: NetworkModel,
    result: OptimizationResult,
    load_limit: float,
    report_prefix: str | None = None,
) -> tuple[Path, Path]:
    """! @brief 生成 `steady_load.png` 和 `startup_load.png`。"""
    cache_dir = output_root / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    backend_module = "matplotlib"
    pyplot_module = f"{backend_module}.pyplot"
    matplotlib = importlib.import_module(backend_module)
    matplotlib.use("Agg")
    plt = importlib.import_module(pyplot_module)

    plot_dir = output_root / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    physical_time_weight = network.weight_mode is WeightMode.FRAME_TIME_US
    threshold = slot_load_threshold_us(network.steady_window.slot_width_us, load_limit)
    paths: list[Path] = []
    for label, loads in (
        ("steady", result.steady_slot_loads),
        ("startup", result.startup_slot_loads),
    ):
        figure, axis = plt.subplots(figsize=(10, 4))
        axis.bar(range(len(loads)), loads, color="#3572A5")
        if physical_time_weight:
            axis.axhline(
                threshold,
                color="#C0392B",
                linestyle="--",
                label=f"{load_limit:.0%} slot limit",
            )
        axis.set_xlabel("Slot index")
        unit = "us" if physical_time_weight else network.weight_mode.value
        axis.set_ylabel(f"Weighted load ({unit})")
        axis.set_title(f"{label.capitalize()} slot load")
        if physical_time_weight:
            axis.legend()
        figure.tight_layout()
        path = plot_dir / prefixed_report_name(f"{label}_load.png", report_prefix)
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(path)
    return paths[0], paths[1]
