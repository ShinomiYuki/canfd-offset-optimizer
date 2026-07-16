"""! @file congestion_plotter.py
@brief 生成按离散时隙解释的拥挤热力图和报文释放时间线。

@details 本模块只读取优化阶段快照，并复用 timeline.release_times 枚举释放事件；
不计算物理总线占用率，也不修改或重新优化 Offset 分配。
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..models import (
    AlgorithmComparisonResult,
    CanMessage,
    NetworkModel,
    TimeWindow,
    WeightMode,
)
from ..timeline.slot_map import release_times
from .filenames import prefixed_report_name


WindowName = Literal["startup", "steady"]

_STAGE_LABELS = {
    "original": "DBC 原始",
    "minimum": "全部最小",
    "greedy": "Greedy",
    "greedy_1opt": "Greedy + 1-opt",
    "gcls": "GCLS",
}


@dataclass(frozen=True, slots=True)
class MessageReleaseSeries:
    """! @brief 一条报文在一个窗口内的全部释放时刻。"""

    message: CanMessage
    release_times_us: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StageCongestionData:
    """! @brief 一个算法阶段在指定窗口内的只读绘图数据。"""

    name: str
    label: str
    counts: tuple[int, ...]
    loads: tuple[int, ...]
    releases: tuple[MessageReleaseSeries, ...]


@dataclass(frozen=True, slots=True)
class WindowCongestionData:
    """! @brief 一个启动或稳态窗口的全部阶段绘图数据。"""

    name: WindowName
    window: TimeWindow
    stages: tuple[StageCongestionData, ...]

    def stage(self, name: str) -> StageCongestionData:
        """! @brief 按稳定阶段名查询绘图数据。"""
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)


def congestion_level(release_count: int) -> int:
    """! @brief 将释放帧数映射到固定的白、绿、黄、橙、红五档。"""
    if release_count < 0:
        raise ValueError("release_count must be non-negative")
    if release_count <= 2:
        return release_count
    if release_count <= 4:
        return 3
    return 4


def build_window_congestion_data(
    network: NetworkModel,
    result: AlgorithmComparisonResult,
    window_name: WindowName,
) -> WindowCongestionData:
    """! @brief 从不可变阶段快照构造并交叉校验纯绘图数据。

    @invariant 由释放事件重建的时隙计数和负载必须与阶段快照完全一致。
    """
    window = (
        network.startup_window if window_name == "startup" else network.steady_window
    )
    stages: list[StageCongestionData] = []
    for stage in result.stages:
        offsets = stage.offset_by_name()
        counts = [0] * window.slot_count
        loads = [0] * window.slot_count
        series: list[MessageReleaseSeries] = []
        for message in result.messages:
            releases = release_times(message, offsets[message.name], window)
            series.append(MessageReleaseSeries(message, releases))
            for release_us in releases:
                slot_index = (release_us - window.start_us) // window.slot_width_us
                counts[slot_index] += 1
                loads[slot_index] += message.frame_time_us
        expected_counts = (
            stage.startup_slot_counts
            if window_name == "startup"
            else stage.steady_slot_counts
        )
        expected_loads = (
            stage.startup_slot_loads
            if window_name == "startup"
            else stage.steady_slot_loads
        )
        if tuple(counts) != expected_counts or tuple(loads) != expected_loads:
            raise ValueError(
                f"stage {stage.name} {window_name} snapshot does not match releases"
            )
        stages.append(
            StageCongestionData(
                stage.name,
                _STAGE_LABELS[stage.name],
                tuple(counts),
                tuple(loads),
                tuple(series),
            )
        )
    return WindowCongestionData(window_name, window, tuple(stages))


def _load_matplotlib(output_root: Path) -> tuple[Any, Any, Any, Any]:
    cache_dir = output_root / "logs" / ".matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg")
    plt = importlib.import_module("matplotlib.pyplot")
    colors = importlib.import_module("matplotlib.colors")
    patches = importlib.import_module("matplotlib.patches")
    lines = importlib.import_module("matplotlib.lines")
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    return plt, colors, patches, lines


def _window_label(window_name: WindowName) -> str:
    return "启动窗口" if window_name == "startup" else "稳态窗口"


def _load_text(network: NetworkModel, load: int) -> str:
    if network.weight_mode is WeightMode.PAYLOAD_BYTES:
        return f"{load}B"
    if network.weight_mode is WeightMode.FRAME_TIME_US:
        return f"{load}μs*"
    return f"权重{load}"


def _slot_tick_data(window: TimeWindow) -> tuple[list[int], list[str]]:
    tick_step = max(1, 10_000 // window.slot_width_us)
    indices = list(range(0, window.slot_count, tick_step))
    labels = [
        f"{(window.start_us + index * window.slot_width_us) / 1_000:g}"
        for index in indices
    ]
    return indices, labels


def _write_heatmap(
    path: Path,
    network: NetworkModel,
    data: WindowCongestionData,
    plt: Any,
    colors: Any,
    patches: Any,
) -> None:
    categories = [
        [congestion_level(count) for count in stage.counts] for stage in data.stages
    ]
    color_values = ("#FFFFFF", "#B7E4C7", "#FFE082", "#FFB74D", "#EF5350")
    color_map = colors.ListedColormap(color_values)
    figure_width = max(13.0, data.window.slot_count * 0.72)
    figure, axis = plt.subplots(figsize=(figure_width, 5.8))
    axis.imshow(
        categories,
        aspect="auto",
        interpolation="nearest",
        cmap=color_map,
        vmin=-0.5,
        vmax=4.5,
    )
    for row, stage in enumerate(data.stages):
        for column, (count, load) in enumerate(
            zip(stage.counts, stage.loads, strict=True)
        ):
            if count == 0:
                continue
            text_color = "white" if congestion_level(count) == 4 else "#202020"
            axis.text(
                column,
                row,
                f"{count}帧\n{_load_text(network, load)}",
                ha="center",
                va="center",
                fontsize=7,
                color=text_color,
            )
    indices, labels = _slot_tick_data(data.window)
    axis.set_xticks(indices, labels)
    axis.set_yticks(
        range(len(data.stages)), [stage.label for stage in data.stages]
    )
    axis.set_xticks(
        [index - 0.5 for index in range(data.window.slot_count + 1)], minor=True
    )
    axis.set_yticks(
        [index - 0.5 for index in range(len(data.stages) + 1)], minor=True
    )
    axis.grid(which="minor", color="#D0D0D0", linewidth=0.6)
    axis.tick_params(which="minor", bottom=False, left=False)
    slot_width_ms = data.window.slot_width_us / 1_000
    axis.set_xlabel(
        "时隙开始时间 (ms)  |  "
        f"窗口 [{data.window.start_us / 1_000:g}, {data.window.end_us / 1_000:g}) ms"
    )
    axis.set_title(
        f"{_window_label(data.name)}报文拥挤热力图\n"
        f"每格 {slot_width_ms:g} ms；颜色表示同一时隙释放帧数，格内显示帧数和负载",
        pad=14,
    )
    legend_items = [
        patches.Patch(facecolor=color, edgecolor="#B0B0B0", label=label)
        for color, label in zip(
            color_values,
            ("0 帧", "1 帧", "2 帧", "3～4 帧", "5 帧及以上"),
            strict=True,
        )
    ]
    axis.legend(
        handles=legend_items,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=5,
        frameon=False,
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def _collision_color(count: int) -> str:
    return {2: "#FFE082", 3: "#FFB74D", 4: "#FFB74D"}.get(count, "#EF5350")


def _write_timeline(
    path: Path,
    network: NetworkModel,
    data: WindowCongestionData,
    plt: Any,
    patches: Any,
    lines: Any,
) -> None:
    shown_stages = (data.stage("original"), data.stage("gcls"))
    release_series = shown_stages[0].releases
    message_count = len(release_series)
    figure_height = max(8.0, message_count * 0.48)
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(19, figure_height),
        sharex=True,
        sharey=True,
    )
    start_ms = data.window.start_us / 1_000
    end_ms = data.window.end_us / 1_000
    slot_width_ms = data.window.slot_width_us / 1_000
    stage_colors = ("#607D8B", "#7E57C2")
    for axis, stage, marker_color in zip(
        axes, shown_stages, stage_colors, strict=True
    ):
        for slot_index, count in enumerate(stage.counts):
            slot_start_ms = start_ms + slot_index * slot_width_ms
            axis.axvline(slot_start_ms, color="#EEEEEE", linewidth=0.6, zorder=0)
            if count >= 2:
                axis.axvspan(
                    slot_start_ms,
                    slot_start_ms + slot_width_ms,
                    color=_collision_color(count),
                    alpha=0.25,
                    zorder=0,
                )
        for row, series in enumerate(stage.releases):
            times_ms = [release / 1_000 for release in series.release_times_us]
            marker_size = 28 + series.message.payload_bytes * 1.8
            axis.scatter(
                times_ms,
                [row] * len(times_ms),
                s=marker_size,
                color=marker_color,
                edgecolor="white",
                linewidth=0.6,
                zorder=3,
            )
        crowded_slots = sum(count >= 2 for count in stage.counts)
        maximum_count = max(stage.counts, default=0)
        peak_load = max(stage.loads, default=0)
        axis.set_title(
            f"{stage.label}\n"
            f"最拥挤 {maximum_count} 帧｜拥挤时隙 {crowded_slots} 个｜"
            f"峰值 {_load_text(network, peak_load)}"
        )
        axis.set_xlim(start_ms, end_ms)
        axis.set_xlabel("时间 (ms)")
        axis.grid(axis="y", color="#EEEEEE", linewidth=0.6)
    row_labels = [
        f"{series.message.name}  0x{series.message.can_id:X}"
        for series in release_series
    ]
    axes[0].set_yticks(range(message_count), row_labels)
    axes[0].invert_yaxis()
    axes[0].set_ylabel("报文")
    axes[1].tick_params(labelleft=False)
    figure.suptitle(
        f"{_window_label(data.name)}报文发送时间线\n"
        f"黄色/橙色/红色区域表示同一 {slot_width_ms:g} ms 时隙有多帧释放",
        y=1.01,
    )
    payload_lengths = sorted(
        {series.message.payload_bytes for series in release_series}
    )
    payload_legend = [
        lines.Line2D(
            [],
            [],
            linestyle="",
            marker="o",
            markersize=(28 + payload * 1.8) ** 0.5,
            markerfacecolor="#607D8B",
            markeredgecolor="white",
            label=f"{payload} Byte",
        )
        for payload in payload_lengths
    ]
    collision_legend = [
        patches.Patch(facecolor="#FFE082", alpha=0.4, label="2 帧拥挤"),
        patches.Patch(facecolor="#FFB74D", alpha=0.4, label="3～4 帧拥挤"),
        patches.Patch(facecolor="#EF5350", alpha=0.4, label="5 帧以上拥挤"),
    ]
    figure.legend(
        handles=[*payload_legend, *collision_legend],
        loc="lower center",
        ncol=min(8, len(payload_legend) + len(collision_legend)),
        frameon=False,
        bbox_to_anchor=(0.5, -0.04),
    )
    figure.tight_layout(rect=(0, 0.07, 1, 0.98))
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def write_congestion_plots(
    output_root: Path,
    network: NetworkModel,
    result: AlgorithmComparisonResult,
    report_prefix: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    """! @brief 生成 startup/steady 热力图和原始/GCLS 时间线。"""
    plt, colors, patches, lines = _load_matplotlib(output_root)
    plot_dir = output_root / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for window_name in ("steady", "startup"):
        data = build_window_congestion_data(network, result, window_name)
        heatmap_path = plot_dir / prefixed_report_name(
            f"{window_name}_congestion_heatmap.png", report_prefix
        )
        timeline_path = plot_dir / prefixed_report_name(
            f"{window_name}_message_timeline.png", report_prefix
        )
        _write_heatmap(heatmap_path, network, data, plt, colors, patches)
        _write_timeline(timeline_path, network, data, plt, patches, lines)
        paths.extend((heatmap_path, timeline_path))
    return paths[0], paths[1], paths[2], paths[3]
