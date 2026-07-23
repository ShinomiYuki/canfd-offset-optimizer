from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics, QImage

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    FrameProtocol,
    GuiOptimizationResult,
    HeatmapSlotDetail,
    HeatmapWindowDetail,
    WeightMode,
)
from canfd_offset_optimizer.gui.heatmap_view_model import (
    HeatmapState,
    HeatmapWindowKind,
    build_heatmap_view_model,
    filter_congested_rows,
)
from canfd_offset_optimizer.gui.load_presentation import congestion_level
from canfd_offset_optimizer.gui.widgets import load_heatmap as heatmap_module
from canfd_offset_optimizer.gui.widgets.load_heatmap import (
    CELL_HORIZONTAL_PADDING,
    RIGHT_MARGIN,
    ROW_HEIGHT,
    ROW_LABEL_WIDTH,
    TOP_MARGIN,
    LoadHeatmap,
    calculate_heatmap_cell_width,
)


def _result(batch: BatchOptimizationResult, index: int = 0) -> GuiOptimizationResult:
    successful = [item.result for item in batch.network_results if item.result is not None]
    return successful[index]


def _repeat_window(
    detail: HeatmapWindowDetail, repeat_count: int
) -> HeatmapWindowDetail:
    def repeat(slots: tuple[HeatmapSlotDetail, ...]) -> tuple[HeatmapSlotDetail, ...]:
        result: list[HeatmapSlotDetail] = []
        for cycle in range(repeat_count):
            for slot in slots:
                index = cycle * len(slots) + slot.slot_index
                result.append(
                    replace(
                        slot,
                        slot_index=index,
                        start_us=index * detail.slot_width_us,
                        end_us=(index + 1) * detail.slot_width_us,
                    )
                )
        return tuple(result)

    return HeatmapWindowDetail(
        detail.slot_width_us,
        repeat(detail.original_slots),
        repeat(detail.optimized_slots),
    )


def _repeated_steady_result(
    result: GuiOptimizationResult, repeat_count: int
) -> GuiOptimizationResult:
    assert result.steady_heatmap is not None
    return replace(
        result,
        steady_loads_before=result.steady_loads_before * repeat_count,
        steady_loads_after=result.steady_loads_after * repeat_count,
        steady_counts_before=result.steady_counts_before * repeat_count,
        steady_counts_after=result.steady_counts_after * repeat_count,
        steady_heatmap=_repeat_window(result.steady_heatmap, repeat_count),
    )


def _show(qtbot, heatmap: LoadHeatmap, width: int = 760, height: int = 720) -> None:
    qtbot.addWidget(heatmap)
    heatmap.resize(width, height)
    heatmap.show()
    qtbot.wait(20)


def test_content_width_grows_with_slot_count_without_shrinking_cells(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    base = _result(batch_result)
    long_result = _repeated_steady_result(base, 4)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)

    heatmap.set_result(base)
    width_100 = heatmap.canvas.content_width
    cell_100 = heatmap.canvas.cell_width
    assert width_100 == ROW_LABEL_WIDTH + 100 * cell_100 + RIGHT_MARGIN

    heatmap.set_result(long_result)
    width_400 = heatmap.canvas.content_width
    assert heatmap.canvas.cell_width == cell_100
    assert width_400 == ROW_LABEL_WIDTH + 400 * cell_100 + RIGHT_MARGIN
    assert width_400 - ROW_LABEL_WIDTH - RIGHT_MARGIN == 4 * (
        width_100 - ROW_LABEL_WIDTH - RIGHT_MARGIN
    )


def test_cell_width_is_font_measured_and_readable(qapp) -> None:
    metrics = QFontMetrics(qapp.font())
    width = calculate_heatmap_cell_width(
        metrics,
        maximum_frame_count=12,
        maximum_load=12_345,
        load_unit="μs",
    )
    assert width >= metrics.horizontalAdvance("12 帧") + CELL_HORIZONTAL_PADDING
    assert width >= metrics.horizontalAdvance("12345 μs") + CELL_HORIZONTAL_PADDING


def test_wide_content_enables_horizontal_scrolling(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, width=640)
    heatmap.set_result(_result(batch_result))
    qtbot.wait(20)

    assert heatmap.canvas.content_width > heatmap.scroll_area.viewport().width()
    assert heatmap.scroll_area.horizontalScrollBar().maximum() > 0


def test_original_and_optimized_share_the_exact_axis(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(_result(batch_result), HeatmapWindowKind.STEADY)
    assert len(view.original_cells) == len(view.optimized_cells) == 100
    assert tuple((cell.start_us, cell.end_us) for cell in view.original_cells) == tuple(
        (cell.start_us, cell.end_us) for cell in view.optimized_cells
    )


def test_payload_and_frame_time_cell_text_use_result_units(
    batch_result: BatchOptimizationResult,
) -> None:
    base = _result(batch_result)
    payload = replace(
        base,
        weight_mode=WeightMode.PAYLOAD_BYTES,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    frame_time = replace(
        base,
        weight_mode=WeightMode.FRAME_TIME_US,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    payload_view = build_heatmap_view_model(payload, HeatmapWindowKind.STEADY)
    frame_view = build_heatmap_view_model(frame_time, HeatmapWindowKind.STEADY)
    payload_cell = next(cell for cell in payload_view.original_cells if cell.frame_count)
    frame_cell = next(cell for cell in frame_view.original_cells if cell.frame_count)
    assert payload_cell.text == f"{payload_cell.frame_count} 帧\n{payload_cell.total_load} B"
    assert frame_cell.text == f"{frame_cell.frame_count} 帧\n{frame_cell.total_load} μs"


def test_zero_frame_cell_is_blank_and_has_no_members(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(_result(batch_result), HeatmapWindowKind.STEADY)
    cell = next(cell for cell in view.original_cells if cell.frame_count == 0)
    assert cell.text == ""
    assert cell.messages == ()
    assert "帧数：0" in cell.tooltip


def test_congestion_levels_keep_four_and_five_plus_separate() -> None:
    assert [congestion_level(value) for value in (0, 1, 2, 3, 4, 5, 9)] == [
        0,
        1,
        2,
        3,
        4,
        5,
        5,
    ]


def test_only_four_and_five_plus_slots_enter_details(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(_result(batch_result), HeatmapWindowKind.STEADY)
    counts = {row.frame_count for row in view.congested_rows}
    assert 4 in counts
    assert 5 in counts
    assert all(count >= 4 for count in counts)
    assert not any(row.frame_count == 3 for row in view.congested_rows)


def test_five_frame_slot_lists_exactly_five_real_messages(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(_result(batch_result), HeatmapWindowKind.STEADY)
    cell = next(cell for cell in view.original_cells if cell.frame_count == 5)
    rows = tuple(
        row
        for row in view.congested_rows
        if row.state is cell.state and row.slot_index == cell.slot_index
    )
    assert len(cell.messages) == len(rows) == 5
    assert [row.message.message_name for row in rows] == [
        message.message_name for message in cell.messages
    ]


def test_detail_can_ids_and_state_specific_offsets_are_exact(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    view = build_heatmap_view_model(result, HeatmapWindowKind.STEADY)
    by_name = {row.message_name: row for row in result.assignments}
    original = next(row for row in view.congested_rows if row.state is HeatmapState.ORIGINAL)
    optimized = next(
        row for row in view.congested_rows if row.state is HeatmapState.OPTIMIZED
    )
    assert original.can_id_text == f"0x{original.message.can_id:X}"
    assert optimized.can_id_text == f"0x{optimized.message.can_id:X}"
    assert original.message.offset_us == by_name[original.message.message_name].original_offset_us
    assert optimized.message.offset_us == by_name[
        optimized.message.message_name
    ].optimized_offset_us


def test_detail_units_follow_the_heatmap_weight(
    batch_result: BatchOptimizationResult,
) -> None:
    base = _result(batch_result)
    payload = replace(base, weight_mode=WeightMode.PAYLOAD_BYTES)
    frame = replace(
        base,
        weight_mode=WeightMode.FRAME_TIME_US,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    assert build_heatmap_view_model(
        payload, HeatmapWindowKind.STEADY
    ).congested_rows[0].total_load_text.endswith(" B")
    assert build_heatmap_view_model(
        frame, HeatmapWindowKind.STEADY
    ).congested_rows[0].total_load_text.endswith(" μs")


def test_congestion_filter_modes(batch_result: BatchOptimizationResult) -> None:
    rows = build_heatmap_view_model(
        _result(batch_result), HeatmapWindowKind.STEADY
    ).congested_rows
    assert all(row.frame_count >= 4 for row in filter_congested_rows(rows, "all"))
    assert all(row.frame_count == 4 for row in filter_congested_rows(rows, "four"))
    assert all(row.frame_count >= 5 for row in filter_congested_rows(rows, "five_plus"))


def test_switching_network_refreshes_heatmap_and_details_together(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    first = _result(batch_result, 0)
    second = _result(batch_result, 1)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_batch(batch_result)
    heatmap.set_result(first)
    first_names = {row.message.message_name for row in heatmap.detail_rows}

    heatmap.set_result(second)
    assert heatmap.view_model is not None
    assert heatmap.view_model.network_id == second.network_id
    assert heatmap.current_network_id == second.network_id
    assert {row.message.message_name for row in heatmap.detail_rows} != first_names
    assert all(
        row.message.message_name.startswith(second.network_name)
        for row in heatmap.detail_rows
    )


def test_switching_window_refreshes_heatmap_and_details_together(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result(batch_result)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(result)
    assert heatmap.view_model is not None
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STEADY

    heatmap.window_combo.setCurrentIndex(1)
    assert heatmap.view_model is not None
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STARTUP
    assert heatmap.canvas.before_series == result.original_startup_load
    assert heatmap.canvas.display_duration_ms == 40
    assert heatmap.scroll_area.horizontalScrollBar().value() == 0


def test_many_detail_records_use_vertical_scrolling(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, height=600)
    heatmap.set_result(_result(batch_result))
    heatmap.details_table.setFixedHeight(180)
    qtbot.wait(20)
    assert heatmap.details_table.rowCount() > 10
    assert heatmap.details_table.verticalScrollBar().maximum() > 0


def test_clicking_congested_cell_selects_matching_detail_group(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert heatmap.view_model is not None
    cell = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count >= 4
    )
    point = QPoint(
        cell.slot_index * heatmap.canvas.cell_width + heatmap.canvas.cell_width // 2,
        TOP_MARGIN + ROW_HEIGHT // 2,
    )
    qtbot.mouseClick(heatmap.canvas, Qt.MouseButton.LeftButton, pos=point)
    selected = heatmap.details_table.item(heatmap.details_table.currentRow(), 0)
    assert selected is not None
    assert selected.data(Qt.ItemDataRole.UserRole + 1) == HeatmapState.ORIGINAL.value
    assert selected.data(Qt.ItemDataRole.UserRole + 2) == cell.slot_index


def test_clicking_detail_scrolls_and_highlights_heatmap(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, width=620)
    heatmap.set_result(_repeated_steady_result(_result(batch_result), 4))
    last_row = heatmap.details_table.rowCount() - 1
    item = heatmap.details_table.item(last_row, 0)
    assert item is not None
    slot_index = int(item.data(Qt.ItemDataRole.UserRole + 2))
    heatmap._locate_cell_from_detail(last_row, 0)
    assert heatmap.scroll_area.horizontalScrollBar().value() > 0
    assert heatmap.canvas._highlight is not None
    assert heatmap.canvas._highlight[1] == slot_index


def test_png_export_contains_full_content_not_current_viewport(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, width=620)
    heatmap.set_result(_result(batch_result))
    bar = heatmap.scroll_area.horizontalScrollBar()
    bar.setValue(bar.maximum())
    output = heatmap.export_png(tmp_path / "complete_heatmap.png")
    image = QImage(str(output))
    assert not image.isNull()
    assert image.width() == max(heatmap.canvas.content_width, 720)
    assert image.width() > heatmap.scroll_area.viewport().width()


def test_png_export_rejects_platform_unsafe_width(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path, monkeypatch
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    monkeypatch.setattr(heatmap_module, "MAX_EXPORT_WIDTH", 100)
    with pytest.raises(ValueError, match="当前热力图过宽，无法以单张 PNG 导出"):
        heatmap.export_png(tmp_path / "too_wide.png")


def test_horizontal_scrolling_is_view_only_and_emits_no_run_signal(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, width=620)
    heatmap.set_result(_result(batch_result))
    selected: list[str] = []
    exported: list[bool] = []
    heatmap.network_selected.connect(selected.append)
    heatmap.export_requested.connect(lambda: exported.append(True))
    bar = heatmap.scroll_area.horizontalScrollBar()
    bar.setValue(bar.maximum() // 2)
    qtbot.wait(10)
    assert selected == []
    assert exported == []


def test_empty_congestion_state_is_explicit(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    base = _result(batch_result)
    assert base.steady_heatmap is not None

    def empty_slots(slots: tuple[HeatmapSlotDetail, ...]) -> tuple[HeatmapSlotDetail, ...]:
        return tuple(replace(slot, frame_count=0, total_load=0, messages=()) for slot in slots)

    detail = HeatmapWindowDetail(
        base.steady_heatmap.slot_width_us,
        empty_slots(base.steady_heatmap.original_slots),
        empty_slots(base.steady_heatmap.optimized_slots),
    )
    empty = replace(
        base,
        steady_loads_before=(0,) * 100,
        steady_loads_after=(0,) * 100,
        steady_counts_before=(0,) * 100,
        steady_counts_after=(0,) * 100,
        steady_heatmap=detail,
    )
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(empty)
    assert heatmap.details_table.isHidden()
    assert not heatmap.details_empty_label.isHidden()
    assert "不存在同时释放 4 帧及以上" in heatmap.details_empty_label.text()


def test_heatmap_network_selector_emits_successful_network_identity(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    selected: list[str] = []
    heatmap.network_selected.connect(selected.append)
    successful = [item for item in batch_result.network_results if item.result is not None]
    heatmap.set_batch(batch_result)
    heatmap.set_result(successful[0].result)
    heatmap.network_combo.setCurrentIndex(
        heatmap.network_combo.findData(successful[1].network_id)
    )
    assert selected == [successful[1].network_id]

def test_startup_png_uses_current_shorter_window(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap, width=620)
    heatmap.set_result(_result(batch_result))
    steady_width = heatmap.canvas.content_width
    heatmap.window_combo.setCurrentIndex(1)
    startup_width = heatmap.canvas.content_width
    output = heatmap.export_png(tmp_path / "startup_complete.png")
    image = QImage(str(output))
    assert startup_width < steady_width
    assert image.width() == max(startup_width, 720)
    assert heatmap.view_model is not None
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STARTUP


def test_widget_weight_change_refreshes_cell_and_table_units_together(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    base = _result(batch_result)
    payload = replace(
        base,
        weight_mode=WeightMode.PAYLOAD_BYTES,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    frame = replace(
        base,
        weight_mode=WeightMode.FRAME_TIME_US,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(payload)
    assert heatmap.view_model is not None
    assert next(cell for cell in heatmap.view_model.original_cells if cell.frame_count).text.endswith(" B")
    assert heatmap.details_table.item(0, 3).text().endswith(" B")

    heatmap.set_result(frame)
    assert heatmap.view_model is not None
    assert next(cell for cell in heatmap.view_model.original_cells if cell.frame_count).text.endswith(" μs")
    assert heatmap.details_table.item(0, 3).text().endswith(" μs")


def test_detail_headers_support_numeric_sorting(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    heatmap.details_table.sortItems(2, Qt.SortOrder.DescendingOrder)
    first = int(heatmap.details_table.item(0, 2).text())
    last = int(
        heatmap.details_table.item(heatmap.details_table.rowCount() - 1, 2).text()
    )
    assert first >= last
