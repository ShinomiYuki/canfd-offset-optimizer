from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    WeightMode,
)
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap
from canfd_offset_optimizer.gui.widgets.load_chart import LoadChart


def _result_with_100_steady_slots(batch_result: BatchOptimizationResult):
    base = batch_result.network_results[0].result
    assert base is not None
    return replace(
        base,
        steady_loads_before=tuple(range(100)),
        steady_loads_after=tuple(1_000 + index for index in range(100)),
    )


def test_steady_display_repeats_immutable_core_arrays_by_selected_range(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_100_steady_slots(batch_result)
    original_core = result.original_steady_load
    optimized_core = result.optimized_steady_load
    chart = LoadChart()
    qtbot.addWidget(chart)

    chart.set_result(result)

    assert chart.display_range_combo.currentData() == 2_000
    assert chart.canvas.display_duration_ms == 2_000
    assert chart.canvas.time_coordinates_ms == tuple(range(0, 2_000, 5))
    assert len(chart.canvas.before_series) == 400
    assert len(chart.canvas.after_series) == 400
    for segment in range(4):
        start = segment * 100
        assert chart.canvas.before_series[start : start + 100] == original_core
        assert chart.canvas.after_series[start : start + 100] == optimized_core
    assert result.original_steady_load is original_core
    assert result.optimized_steady_load is optimized_core
    assert "稳态负载，500 ms 超周期重复展示 4 次" in chart.chart_title_label.text()

    chart.display_range_combo.setCurrentIndex(chart.display_range_combo.findData(500))

    assert chart._result is result  # display-only refresh; no backend request is created
    assert chart.canvas.before_series == original_core
    assert chart.canvas.after_series == optimized_core
    assert len(chart.canvas.before_series) == 100
    assert chart.canvas.time_coordinates_ms == tuple(range(0, 500, 5))
    assert result.original_steady_load is original_core
    assert result.optimized_steady_load is optimized_core


def test_startup_window_uses_only_real_core_range_without_repetition(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_100_steady_slots(batch_result)
    startup_before = result.original_startup_load
    startup_after = result.optimized_startup_load
    chart = LoadChart()
    qtbot.addWidget(chart)
    chart.set_result(result)

    chart.window_combo.setCurrentIndex(1)

    assert not chart.display_range_label.isEnabled()
    assert not chart.display_range_combo.isEnabled()
    assert chart.canvas.before_series is startup_before
    assert chart.canvas.after_series is startup_after
    assert len(chart.canvas.before_series) == len(startup_before)
    assert chart.canvas.display_duration_ms == len(startup_before) * 5
    assert chart.canvas.time_coordinates_ms == tuple(
        range(0, len(startup_before) * 5, 5)
    )
    assert "启动负载，核心真实范围" in chart.chart_title_label.text()
    assert "超周期重复展示" not in chart.chart_title_label.text()


def test_png_exports_the_current_complete_display_range(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    chart = LoadChart()
    qtbot.addWidget(chart)
    chart.resize(640, 360)
    chart.set_result(_result_with_100_steady_slots(batch_result))
    chart.display_range_combo.setCurrentIndex(
        chart.display_range_combo.findData(5_000)
    )

    output = chart.export_png(tmp_path / "load_5000ms.png")

    assert chart.canvas.display_duration_ms == 5_000
    assert len(chart.canvas.before_series) == 1_000
    assert chart.canvas.time_coordinates_ms[-1] == 4_995
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_classic_chart_and_heatmap_show_byte_units_without_microseconds(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    classic = replace(
        _result_with_100_steady_slots(batch_result),
        weight_mode=WeightMode.PAYLOAD_BYTES,
        frame_protocol=FrameProtocol.CLASSIC_CAN,
        classic_weight_model=CLASSIC_WEIGHT_MODEL,
    )
    chart = LoadChart()
    heatmap = LoadHeatmap()
    qtbot.addWidget(chart)
    qtbot.addWidget(heatmap)
    chart.set_result(classic)
    heatmap.set_result(classic)

    for label in (chart.weight_basis_label.text(), heatmap.weight_basis_label.text()):
        assert "Payload 长度近似权重（payload_bytes）" in label
        assert "Byte/slot" in label
        assert "μs" not in label
