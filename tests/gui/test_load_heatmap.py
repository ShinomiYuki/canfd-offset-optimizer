from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import BatchOptimizationResult
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap


def _result_with_known_loads(batch_result: BatchOptimizationResult):
    result = batch_result.network_results[0].result
    assert result is not None
    return replace(
        result,
        steady_loads_before=tuple(range(100)),
        steady_loads_after=tuple(1_000 + index for index in range(100)),
    )


def test_heatmap_repeats_each_steady_series_without_mutating_result(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_known_loads(batch_result)
    original = result.original_steady_load
    optimized = result.optimized_steady_load
    heatmap = LoadHeatmap()
    qtbot.addWidget(heatmap)

    heatmap.set_result(result)

    assert heatmap.canvas.before_series == original * 4
    assert heatmap.canvas.after_series == optimized * 4
    assert len(heatmap.canvas.before_series) == 400
    assert heatmap.canvas.time_coordinates_ms == tuple(range(0, 2_000, 5))
    assert result.original_steady_load is original
    assert result.optimized_steady_load is optimized
    assert "500 ms 超周期重复展示 4 次" in heatmap.title_label.text()


def test_heatmap_startup_is_not_repeated_and_png_uses_current_view(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    result = _result_with_known_loads(batch_result)
    heatmap = LoadHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.resize(640, 320)
    heatmap.set_result(result)

    heatmap.window_combo.setCurrentIndex(1)

    assert not heatmap.display_range_combo.isEnabled()
    assert heatmap.canvas.before_series is result.original_startup_load
    assert heatmap.canvas.after_series is result.optimized_startup_load
    output = heatmap.export_png(tmp_path / "startup_heatmap.png")
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
