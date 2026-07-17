from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import BatchOptimizationResult
from canfd_offset_optimizer.gui.load_presentation import congestion_level
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap


def _result_with_known_loads(batch_result: BatchOptimizationResult):
    result = batch_result.network_results[0].result
    assert result is not None
    return replace(
        result,
        steady_loads_before=tuple(range(100)),
        steady_loads_after=tuple(1_000 + index for index in range(100)),
    )


def test_heatmap_uses_one_real_steady_window_and_core_congestion_counts(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_known_loads(batch_result)
    original = result.original_steady_load
    optimized = result.optimized_steady_load
    heatmap = LoadHeatmap()
    qtbot.addWidget(heatmap)

    heatmap.set_result(result)

    assert heatmap.canvas.before_series is original
    assert heatmap.canvas.after_series is optimized
    assert heatmap.canvas.counts_before is result.original_steady_count
    assert heatmap.canvas.counts_after is result.optimized_steady_count
    assert len(heatmap.canvas.before_series) == 100
    assert heatmap.canvas.display_duration_ms == 500
    assert heatmap.canvas.time_coordinates_ms == tuple(range(0, 500, 5))
    assert result.original_steady_load is original
    assert result.optimized_steady_load is optimized
    assert "核心真实范围 500 ms" in heatmap.title_label.text()
    assert "重复" not in heatmap.title_label.text()
    assert not hasattr(heatmap, "display_range_combo")


def test_congestion_levels_use_requested_fixed_thresholds() -> None:
    assert [congestion_level(value) for value in (0, 1, 2, 3, 4, 5, 9)] == [
        0,
        1,
        2,
        3,
        4,
        5,
        5,
    ]


def test_heatmap_startup_is_not_repeated_and_png_uses_current_view(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    result = _result_with_known_loads(batch_result)
    heatmap = LoadHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.resize(640, 320)
    heatmap.set_result(result)

    heatmap.window_combo.setCurrentIndex(1)

    assert heatmap.canvas.before_series is result.original_startup_load
    assert heatmap.canvas.after_series is result.optimized_startup_load
    assert heatmap.canvas.counts_before is result.original_startup_count
    assert heatmap.canvas.counts_after is result.optimized_startup_count
    output = heatmap.export_png(tmp_path / "startup_heatmap.png")
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_heatmap_network_selector_emits_successful_network_identity(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    qtbot.addWidget(heatmap)
    selected: list[str] = []
    heatmap.network_selected.connect(selected.append)
    successful = [item for item in batch_result.network_results if item.result is not None]

    heatmap.set_batch(batch_result)
    heatmap.set_result(successful[0].result)

    assert heatmap.network_combo.isEnabled()
    assert heatmap.network_combo.count() == len(successful)
    assert heatmap.network_combo.currentData() == successful[0].network_id
    heatmap.network_combo.setCurrentIndex(
        heatmap.network_combo.findData(successful[1].network_id)
    )
    assert selected == [successful[1].network_id]
