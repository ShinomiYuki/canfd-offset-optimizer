"""! @file test_comparison.py
@brief 五阶段算法比较、可复现性和报告只读性的回归测试。
"""

import csv
import json
from dataclasses import replace
from pathlib import Path

from canfd_offset_optimizer.config import (
    ModelConfig,
    ObjectiveConfig,
    OptimizationConfig,
    ProjectConfig,
)
from canfd_offset_optimizer.models import (
    CanMessage,
    ChannelConfig,
    NetworkModel,
    ObjectiveMode,
    WeightMode,
)
from canfd_offset_optimizer.optimization.comparison import compare_algorithms
from canfd_offset_optimizer.reporting.comparison_writer import (
    write_comparison_csv_reports,
    write_comparison_summary,
)
from canfd_offset_optimizer.reporting.comparison_plotter import write_comparison_plots
from canfd_offset_optimizer.reporting.congestion_plotter import (
    build_window_congestion_data,
    congestion_level,
    write_congestion_plots,
)
from canfd_offset_optimizer.reporting.objective_mode_plotter import (
    write_objective_mode_plot,
)
from canfd_offset_optimizer.reporting.objective_mode_writer import (
    write_all_network_objective_report,
    write_objective_mode_reports,
)
from canfd_offset_optimizer.reporting.weight_mode_writer import write_weight_mode_reports
from canfd_offset_optimizer.timeline.slot_map import (
    SlotMap,
    build_windows,
    precompute_slot_map,
)
from canfd_offset_optimizer.timeline.state import SearchState


def _fixture() -> tuple[tuple[CanMessage, ...], SlotMap]:
    offsets = tuple(range(15_000, 100_001, 5_000))
    specs = (
        ("A", 0x100, 10_000, 8, 15_000),
        ("B", 0x200, 20_000, 16, 20_000),
        ("C", 0x300, 50_000, 32, 25_000),
    )
    messages = tuple(
        CanMessage(
            name,
            can_id,
            False,
            cycle,
            payload,
            offsets,
            original,
            "ECU",
            index,
            payload,
        )
        for index, (name, can_id, cycle, payload, original) in enumerate(specs)
    )
    startup, steady, _ = build_windows(messages, 5_000, 100_000)
    return messages, precompute_slot_map(messages, startup, steady)


def _network(messages: tuple[CanMessage, ...], slot_map: SlotMap) -> NetworkModel:
    return NetworkModel(
        messages,
        ChannelConfig("CAN1", None, None, None),
        slot_map.steady_window.end_us - slot_map.steady_window.start_us,
        slot_map.startup_window,
        slot_map.steady_window,
        WeightMode.PAYLOAD_BYTES,
    )


def test_five_stage_comparison_is_legal_monotonic_and_reproducible() -> None:
    messages, slot_map = _fixture()
    config = OptimizationConfig(random_restarts=2, conflict_candidate_cap=3)
    first = compare_algorithms(
        messages, slot_map, config, seed=77, weight_mode=WeightMode.PAYLOAD_BYTES
    )
    second = compare_algorithms(
        tuple(reversed(messages)),
        slot_map,
        config,
        seed=77,
        weight_mode=WeightMode.PAYLOAD_BYTES,
    )
    assert tuple(stage.name for stage in first.stages) == (
        "original",
        "minimum",
        "greedy",
        "greedy_1opt",
        "gcls",
    )
    assert first.stage("greedy_1opt").objective <= first.stage("greedy").objective
    assert first.stage("gcls").objective <= first.stage("greedy_1opt").objective
    assert all(
        assignment.offset_us in messages[0].allowed_offsets_us
        for stage in first.stages
        for assignment in stage.assignments
    )
    for stage in first.stages:
        rebuilt = SearchState(messages, slot_map)
        rebuilt.apply_assignments(stage.offset_by_name())
        assert tuple(rebuilt.steady_slot_loads) == stage.steady_slot_loads
        assert tuple(rebuilt.startup_slot_loads) == stage.startup_slot_loads
        assert tuple(rebuilt.steady_slot_counts) == stage.steady_slot_counts
        assert tuple(rebuilt.startup_slot_counts) == stage.startup_slot_counts
    assert [
        (stage.name, stage.assignments, stage.objective, stage.steady_slot_loads)
        for stage in first.stages
    ] == [
        (stage.name, stage.assignments, stage.objective, stage.steady_slot_loads)
        for stage in second.stages
    ]
    assert first.restart_records == second.restart_records


def test_comparison_writers_do_not_modify_snapshots(tmp_path: Path) -> None:
    messages, slot_map = _fixture()
    config = ProjectConfig(
        optimization=OptimizationConfig(random_restarts=0, conflict_candidate_cap=3),
        model=ModelConfig(weight_mode=WeightMode.PAYLOAD_BYTES),
    )
    result = compare_algorithms(
        messages,
        slot_map,
        config.optimization,
        weight_mode=WeightMode.PAYLOAD_BYTES,
    )
    network = _network(messages, slot_map)
    before = result
    write_comparison_csv_reports(tmp_path, network, result, 0.75)
    write_comparison_summary(tmp_path, network, config, result)
    write_comparison_plots(tmp_path, network, result, 0.75)
    congestion_paths = write_congestion_plots(tmp_path, network, result)
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in congestion_paths)
    assert result == before


def test_weight_mode_writer_does_not_modify_either_snapshot(tmp_path: Path) -> None:
    payload_messages, slot_map = _fixture()
    physical_messages = tuple(
        replace(message, frame_time_us=message.payload_bytes + 100)
        for message in payload_messages
    )
    optimization = OptimizationConfig(random_restarts=0, conflict_candidate_cap=3)
    payload_result = compare_algorithms(
        payload_messages,
        slot_map,
        optimization,
        weight_mode=WeightMode.PAYLOAD_BYTES,
    )
    physical_result = compare_algorithms(
        physical_messages,
        slot_map,
        optimization,
        weight_mode=WeightMode.FRAME_TIME_US,
    )
    payload_network = _network(payload_messages, slot_map)
    physical_network = replace(
        payload_network,
        messages=physical_messages,
        channel=ChannelConfig("CAN1", 500_000, 2_000_000, True),
        weight_mode=WeightMode.FRAME_TIME_US,
    )
    payload_config = ProjectConfig(
        optimization=optimization,
        model=ModelConfig(weight_mode=WeightMode.PAYLOAD_BYTES),
    )
    physical_config = ProjectConfig(
        optimization=optimization,
        model=ModelConfig(weight_mode=WeightMode.FRAME_TIME_US),
    )
    before = payload_result, physical_result
    paths = write_weight_mode_reports(
        tmp_path,
        payload_network,
        payload_config,
        payload_result,
        physical_network,
        physical_config,
        physical_result,
    )
    assert all(path.is_file() for path in paths)
    assert (payload_result, physical_result) == before


def test_congestion_plot_data_matches_snapshots_and_release_rules() -> None:
    messages, slot_map = _fixture()
    network = _network(messages, slot_map)
    result = compare_algorithms(
        messages,
        slot_map,
        OptimizationConfig(random_restarts=0, conflict_candidate_cap=3),
        weight_mode=WeightMode.PAYLOAD_BYTES,
    )
    assert [congestion_level(value) for value in (0, 1, 2, 3, 4, 5, 17)] == [
        0,
        1,
        2,
        3,
        3,
        4,
        4,
    ]
    for window_name in ("startup", "steady"):
        data = build_window_congestion_data(network, result, window_name)
        for plot_stage, result_stage in zip(data.stages, result.stages, strict=True):
            expected_counts = (
                result_stage.startup_slot_counts
                if window_name == "startup"
                else result_stage.steady_slot_counts
            )
            expected_loads = (
                result_stage.startup_slot_loads
                if window_name == "startup"
                else result_stage.steady_slot_loads
            )
            assert plot_stage.counts == expected_counts
            assert plot_stage.loads == expected_loads
            for series in plot_stage.releases:
                assert all(
                    data.window.start_us <= release < data.window.end_us
                    for release in series.release_times_us
                )
                if window_name == "steady":
                    assert len(series.release_times_us) == (
                        network.hyperperiod_us // series.message.cycle_time_us
                    )


def test_objective_mode_reports_are_read_only_and_complete(tmp_path: Path) -> None:
    payload_messages, slot_map = _fixture()
    messages = tuple(
        replace(message, frame_time_us=message.payload_bytes + 100)
        for message in payload_messages
    )
    optimization = OptimizationConfig(random_restarts=0, conflict_candidate_cap=3)
    results = {
        mode: compare_algorithms(
            messages,
            slot_map,
            optimization,
            weight_mode=WeightMode.FRAME_TIME_US,
            objective_config=ObjectiveConfig(mode),
        )
        for mode in (ObjectiveMode.PEAK, ObjectiveMode.BALANCED, ObjectiveMode.VARIANCE)
    }
    configs = {
        mode: ProjectConfig(
            optimization=optimization,
            model=ModelConfig(weight_mode=WeightMode.FRAME_TIME_US),
            objective=ObjectiveConfig(mode),
        )
        for mode in results
    }
    network = replace(
        _network(messages, slot_map),
        channel=ChannelConfig("CAN1", 500_000, 2_000_000, True),
        weight_mode=WeightMode.FRAME_TIME_US,
    )
    before = tuple(results.items())
    network_root = tmp_path / "CAN1"
    paths = write_objective_mode_reports(
        network_root, network, configs, results, "CAN1"
    )
    plot = write_objective_mode_plot(network_root, network, results, "CAN1")
    aggregate = write_all_network_objective_report(tmp_path)
    assert all(path.is_file() and path.stat().st_size > 0 for path in (*paths, plot))
    assert plot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert aggregate.read_bytes().startswith(b"\xef\xbb\xbf")
    assert tuple(results.items()) == before
    with paths[0].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["result"] for row in rows] == [
        "original",
        "peak",
        "balanced",
        "variance",
    ]
    assert {row["weight_mode"] for row in rows} == {"frame_time_us"}
    summary = json.loads(paths[2].read_text(encoding="utf-8"))
    cross = summary["cross_evaluation"]
    assert set(cross["results"]) == {"original", "peak", "balanced", "variance"}
    assert cross["balanced_vs_peak"]["recommended_offset_difference_count"] >= 0
    assert cross["balanced_vs_peak"]["steady_phase_difference_count"] >= 0
