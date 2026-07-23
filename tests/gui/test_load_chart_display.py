from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    WeightMode,
)
from canfd_offset_optimizer.gui.widgets.load_chart import LoadChart, _CurveCanvas
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap


def _result_with_steady_slots(
    batch_result: BatchOptimizationResult, slot_count: int
):
    base = batch_result.network_results[0].result
    assert base is not None
    return replace(
        base,
        steady_loads_before=tuple(range(slot_count)),
        steady_loads_after=tuple(
            1_000 + index for index in range(slot_count)
        ),
        steady_counts_before=(0,) * slot_count,
        steady_counts_after=(0,) * slot_count,
        steady_heatmap=None,
        slot_width_us=5_000,
    )


@pytest.mark.parametrize(
    ("hyperperiod_ms", "slot_count"),
    ((100, 20), (500, 100), (1_000, 200), (2_000, 400)),
)
@pytest.mark.parametrize("repeat_count", (1, 2, 4))
def test_steady_display_repeats_one_real_hyperperiod(
    qtbot,
    batch_result: BatchOptimizationResult,
    hyperperiod_ms: int,
    slot_count: int,
    repeat_count: int,
) -> None:
    result = _result_with_steady_slots(batch_result, slot_count)
    original_core = result.original_steady_load
    optimized_core = result.optimized_steady_load
    chart = LoadChart()
    qtbot.addWidget(chart)

    chart.set_result(result)
    chart.display_range_combo.setCurrentIndex(
        chart.display_range_combo.findData(repeat_count)
    )

    assert result.load_window_metadata.steady_hyperperiod_ms == hyperperiod_ms
    assert chart.display_range_combo.currentData() == repeat_count
    assert (
        chart.display_range_combo.currentText()
        == f"{repeat_count} 个超周期（{hyperperiod_ms * repeat_count} ms）"
    )
    assert chart.canvas.display_duration_ms == hyperperiod_ms * repeat_count
    assert len(chart.canvas.before_series) == slot_count * repeat_count
    assert len(chart.canvas.after_series) == slot_count * repeat_count
    assert chart.canvas.time_coordinates_ms == tuple(
        index * 5 for index in range(slot_count * repeat_count)
    )
    for segment in range(repeat_count):
        start = segment * slot_count
        assert (
            chart.canvas.before_series[start : start + slot_count]
            == original_core
        )
        assert (
            chart.canvas.after_series[start : start + slot_count]
            == optimized_core
        )
    assert result.original_steady_load is original_core
    assert result.optimized_steady_load is optimized_core
    assert (
        f"稳态负载，{hyperperiod_ms} ms 超周期重复展示 {repeat_count} 次"
        in chart.chart_title_label.text()
    )


def test_default_display_is_four_real_hyperperiods(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_steady_slots(batch_result, 400)
    chart = LoadChart()
    qtbot.addWidget(chart)

    chart.set_result(result)

    assert chart.display_range_combo.currentData() == 4
    assert chart.display_range_combo.currentText() == "4 个超周期（8000 ms）"
    assert chart.canvas.display_duration_ms == 8_000
    assert len(chart.canvas.before_series) == 1_600
    assert chart.canvas.time_coordinates_ms[-1] == 7_995


def test_startup_window_uses_only_real_core_range_without_repetition(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result_with_steady_slots(batch_result, 400)
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
    assert (
        chart.canvas.display_duration_ms
        == result.load_window_metadata.startup_duration_ms
    )
    assert chart.canvas.time_coordinates_ms == tuple(
        index * result.load_window_metadata.slot_width_ms
        for index in range(len(startup_before))
    )
    assert "启动负载，核心真实范围" in chart.chart_title_label.text()
    assert "超周期重复展示" not in chart.chart_title_label.text()


def test_set_series_validation_is_atomic() -> None:
    canvas = _CurveCanvas()
    canvas.set_series(
        (1, 2, 3),
        (4, 5, 6),
        slot_width_ms=5,
        display_duration_ms=15,
        period_ms=15,
    )
    snapshot = (
        canvas.before_series,
        canvas.after_series,
        canvas.time_coordinates_ms,
        canvas.display_duration_ms,
        canvas._period_ms,
    )

    with pytest.raises(
        ValueError, match="display duration cannot truncate"
    ):
        canvas.set_series(
            (10, 11, 12, 13),
            (20, 21, 22, 23),
            slot_width_ms=5,
            display_duration_ms=10,
            period_ms=20,
        )

    assert (
        canvas.before_series,
        canvas.after_series,
        canvas.time_coordinates_ms,
        canvas.display_duration_ms,
        canvas._period_ms,
    ) == snapshot


@pytest.mark.parametrize(
    ("before", "after"),
    (
        ((1, 2), (1,)),
        ((1, float("inf")), (1, 2)),
        ((1, -1), (1, 2)),
    ),
)
def test_set_series_rejects_invalid_values_without_partial_update(
    before: tuple[float, ...], after: tuple[float, ...]
) -> None:
    canvas = _CurveCanvas()
    canvas.set_series((1,), (2,))
    snapshot = (canvas.before_series, canvas.after_series)

    with pytest.raises(ValueError):
        canvas.set_series(before, after)  # type: ignore[arg-type]

    assert (canvas.before_series, canvas.after_series) == snapshot


def test_png_exports_the_current_complete_repeat_range(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    chart = LoadChart()
    qtbot.addWidget(chart)
    chart.resize(640, 360)
    chart.set_result(_result_with_steady_slots(batch_result, 100))
    chart.display_range_combo.setCurrentIndex(
        chart.display_range_combo.findData(10)
    )

    output = chart.export_png(tmp_path / "load_10_periods.png")

    assert chart.canvas.display_duration_ms == 5_000
    assert len(chart.canvas.before_series) == 1_000
    assert chart.canvas.time_coordinates_ms[-1] == 4_995
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_classic_chart_and_heatmap_show_byte_units_without_microseconds(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    classic = replace(
        _result_with_steady_slots(batch_result, 100),
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

    for label in (
        chart.weight_basis_label.text(),
        heatmap.weight_basis_label.text(),
    ):
        assert "Payload 长度近似权重（payload_bytes）" in label
        assert "Byte/slot" in label
        assert "μs" not in label
