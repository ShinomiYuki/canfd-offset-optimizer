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
    CongestionTableMode,
    HeatmapCellSelection,
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


def _click_cell(qtbot, heatmap: LoadHeatmap, state: HeatmapState, slot_index: int) -> None:
    row = 0 if state is HeatmapState.ORIGINAL else 1
    point = QPoint(
        slot_index * heatmap.canvas.cell_width + heatmap.canvas.cell_width // 2,
        TOP_MARGIN + row * ROW_HEIGHT + ROW_HEIGHT // 2,
    )
    qtbot.mouseClick(heatmap.canvas, Qt.MouseButton.LeftButton, pos=point)


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


def test_cell_selection_identity_rejects_other_network_and_window(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(
        _result(batch_result), HeatmapWindowKind.STEADY
    )
    valid = view.selection_for(HeatmapState.ORIGINAL, 7)
    assert view.cell_for(valid) is view.original_cells[7]
    with pytest.raises(ValueError, match="another network"):
        view.cell_for(replace(valid, network_id="other-network"))
    with pytest.raises(ValueError, match="another window"):
        view.cell_for(
            replace(valid, window_kind=HeatmapWindowKind.STARTUP)
        )


def test_cell_member_count_inconsistency_is_rejected(
    batch_result: BatchOptimizationResult,
) -> None:
    view = build_heatmap_view_model(
        _result(batch_result), HeatmapWindowKind.STEADY
    )
    cell = next(cell for cell in view.original_cells if cell.frame_count == 2)
    with pytest.raises(ValueError, match="members do not match frame_count"):
        replace(cell, frame_count=3)


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
    assert payload_cell.text == (
        f"{payload_cell.frame_count} \u5e27\n{payload_cell.total_load} B\n\u4fdd\u5b88 \u2014"
    )
    assert frame_cell.text == (
        f"{frame_cell.frame_count} \u5e27\n{frame_cell.total_load} \u03bcs\n\u4fdd\u5b88 \u2014"
    )


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
    assert heatmap.view_model is not None
    selected = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 2
    )
    _click_cell(qtbot, heatmap, selected.state, selected.slot_index)
    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT

    heatmap.set_result(second)
    assert heatmap.view_model is not None
    assert heatmap.view_model.network_id == second.network_id
    assert heatmap.current_network_id == second.network_id
    assert {row.message.message_name for row in heatmap.detail_rows} != first_names
    assert all(
        row.message.message_name.startswith(second.network_name)
        for row in heatmap.detail_rows
    )
    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None
    assert heatmap.canvas.highlighted_cell is None


def test_switching_window_refreshes_heatmap_and_details_together(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result(batch_result)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(result)
    assert heatmap.view_model is not None
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STEADY
    selected = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 2
    )
    _click_cell(qtbot, heatmap, selected.state, selected.slot_index)
    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT

    heatmap.window_combo.setCurrentIndex(1)
    assert heatmap.view_model is not None
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STARTUP
    assert heatmap.canvas.before_series == result.original_startup_load
    assert heatmap.canvas.display_duration_ms == 40
    assert heatmap.scroll_area.horizontalScrollBar().value() == 0
    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None
    assert heatmap.canvas.highlighted_cell is None

    startup = next(
        cell for cell in heatmap.view_model.optimized_cells if cell.frame_count > 0
    )
    _click_cell(qtbot, heatmap, startup.state, startup.slot_index)
    heatmap.window_combo.setCurrentIndex(0)
    assert heatmap.view_model.window_kind is HeatmapWindowKind.STEADY
    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None


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


def test_rebinding_same_network_result_clears_selected_slot(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    result = _result(batch_result)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(result)
    assert heatmap.view_model is not None
    cell = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 2
    )
    _click_cell(qtbot, heatmap, cell.state, cell.slot_index)
    assert heatmap.selected_cell is not None

    heatmap.set_result(replace(result, elapsed_seconds=result.elapsed_seconds + 1.0))

    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None
    assert heatmap.canvas.highlighted_cell is None
    assert all(row.frame_count >= 4 for row in heatmap.visible_detail_rows)


def test_initial_mode_keeps_all_congested_summary(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))

    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None
    assert heatmap.show_all_button.isHidden()
    assert heatmap.congestion_filter.isEnabled()
    assert heatmap.details_table.rowCount() == len(heatmap.detail_rows)
    assert all(row.frame_count >= 4 for row in heatmap.visible_detail_rows)
    assert not any(row.frame_count == 3 for row in heatmap.visible_detail_rows)


@pytest.mark.parametrize(
    ("state", "frame_count"),
    (
        (HeatmapState.ORIGINAL, 0),
        (HeatmapState.ORIGINAL, 1),
        (HeatmapState.ORIGINAL, 2),
        (HeatmapState.ORIGINAL, 3),
        (HeatmapState.ORIGINAL, 4),
        (HeatmapState.ORIGINAL, 5),
        (HeatmapState.OPTIMIZED, 0),
        (HeatmapState.OPTIMIZED, 1),
        (HeatmapState.OPTIMIZED, 2),
        (HeatmapState.OPTIMIZED, 4),
        (HeatmapState.OPTIMIZED, 5),
    ),
)
def test_clicking_any_heatmap_cell_shows_only_that_slot(
    qtbot,
    batch_result: BatchOptimizationResult,
    state: HeatmapState,
    frame_count: int,
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert heatmap.view_model is not None
    cell = next(
        cell
        for cell in heatmap.view_model.cells_for(state)
        if cell.frame_count == frame_count
    )

    _click_cell(qtbot, heatmap, state, cell.slot_index)

    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT
    assert heatmap.selected_cell == HeatmapCellSelection(
        heatmap.view_model.network_id,
        heatmap.view_model.window_kind,
        state,
        cell.slot_index,
    )
    assert heatmap.canvas.highlighted_cell == (state, cell.slot_index)
    assert heatmap.details_table.rowCount() == frame_count
    assert len(heatmap.visible_detail_rows) == frame_count
    assert {
        (row.state, row.slot_index) for row in heatmap.visible_detail_rows
    } <= {(state, cell.slot_index)}
    assert [row.message for row in heatmap.visible_detail_rows] == list(cell.messages)
    assert not heatmap.congestion_filter.isEnabled()
    assert not heatmap.show_all_button.isHidden()
    assert f"{frame_count} 帧" in heatmap.detail_context_label.text()
    assert f"{cell.total_load} {cell.load_unit}" in heatmap.detail_context_label.text()
    if frame_count == 0:
        assert heatmap.details_table.isHidden()
        assert "当前时隙没有报文释放" in heatmap.details_empty_label.text()
    else:
        assert not heatmap.details_table.isHidden()


def test_clicking_optimized_three_frame_cell_shows_three_formal_members(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    base = _result(batch_result)
    assert base.steady_heatmap is not None
    source = next(
        slot
        for slot in base.steady_heatmap.original_slots
        if slot.frame_count == 3
    )
    target_index = next(
        slot.slot_index
        for slot in base.steady_heatmap.optimized_slots
        if slot.frame_count != 3
    )
    optimized_offsets = {
        assignment.message_name: assignment.optimized_offset_us
        for assignment in base.assignments
    }
    members = tuple(
        replace(
            message,
            offset_us=optimized_offsets[message.message_name],
        )
        for message in source.messages
    )
    optimized_slots = list(base.steady_heatmap.optimized_slots)
    optimized_slots[target_index] = replace(
        optimized_slots[target_index],
        frame_count=3,
        total_load=source.total_load,
        messages=members,
    )
    loads_after = list(base.steady_loads_after)
    counts_after = list(base.steady_counts_after)
    loads_after[target_index] = source.total_load
    counts_after[target_index] = 3
    result = replace(
        base,
        steady_loads_after=tuple(loads_after),
        steady_counts_after=tuple(counts_after),
        steady_heatmap=HeatmapWindowDetail(
            base.steady_heatmap.slot_width_us,
            base.steady_heatmap.original_slots,
            tuple(optimized_slots),
        ),
    )
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(result)

    _click_cell(qtbot, heatmap, HeatmapState.OPTIMIZED, target_index)

    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT
    assert len(heatmap.visible_detail_rows) == 3
    assert [row.message for row in heatmap.visible_detail_rows] == list(members)
    assert all(
        row.state is HeatmapState.OPTIMIZED
        and row.slot_index == target_index
        for row in heatmap.visible_detail_rows
    )


def test_clicking_new_cell_replaces_previous_slot_rows(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert heatmap.view_model is not None
    original = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 3
    )
    optimized = next(
        cell for cell in heatmap.view_model.optimized_cells if cell.frame_count == 2
    )

    _click_cell(qtbot, heatmap, original.state, original.slot_index)
    first_names = {
        row.message.message_name for row in heatmap.visible_detail_rows
    }
    assert len(first_names) == 3
    _click_cell(qtbot, heatmap, optimized.state, optimized.slot_index)

    assert heatmap.selected_cell is not None
    assert heatmap.selected_cell.state is HeatmapState.OPTIMIZED
    assert heatmap.selected_cell.slot_index == optimized.slot_index
    assert heatmap.canvas.highlighted_cell == (
        HeatmapState.OPTIMIZED,
        optimized.slot_index,
    )
    assert len(heatmap.visible_detail_rows) == 2
    assert {
        row.message.message_name for row in heatmap.visible_detail_rows
    } != first_names


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
    state = HeatmapState(str(item.data(Qt.ItemDataRole.UserRole + 1)))
    count_item = heatmap.details_table.item(last_row, 2)
    assert count_item is not None
    expected_count = int(count_item.text())
    heatmap._locate_cell_from_detail(last_row, 0)
    assert heatmap.scroll_area.horizontalScrollBar().value() > 0
    assert heatmap.canvas.highlighted_cell == (state, slot_index)
    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT
    assert heatmap.selected_cell is not None
    assert heatmap.selected_cell.state is state
    assert heatmap.selected_cell.slot_index == slot_index
    assert heatmap.details_table.rowCount() == expected_count
    assert all(
        row.state is state and row.slot_index == slot_index
        for row in heatmap.visible_detail_rows
    )


def test_original_and_optimized_same_slot_use_distinct_selection_and_members(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert heatmap.view_model is not None
    slot_index = next(
        index
        for index, (original, optimized) in enumerate(
            zip(
                heatmap.view_model.original_cells,
                heatmap.view_model.optimized_cells,
                strict=True,
            )
        )
        if original.frame_count != optimized.frame_count
        and original.frame_count > 0
        and optimized.frame_count > 0
    )
    original = heatmap.view_model.original_cells[slot_index]
    optimized = heatmap.view_model.optimized_cells[slot_index]

    _click_cell(qtbot, heatmap, HeatmapState.ORIGINAL, slot_index)
    original_names = [
        row.message.message_name for row in heatmap.visible_detail_rows
    ]
    original_offsets = [row.message.offset_us for row in heatmap.visible_detail_rows]
    _click_cell(qtbot, heatmap, HeatmapState.OPTIMIZED, slot_index)
    optimized_names = [
        row.message.message_name for row in heatmap.visible_detail_rows
    ]
    optimized_offsets = [row.message.offset_us for row in heatmap.visible_detail_rows]

    assert len(original_names) == original.frame_count
    assert len(optimized_names) == optimized.frame_count
    assert original_names != optimized_names
    assert original_offsets != optimized_offsets
    assert heatmap.selected_cell is not None
    assert heatmap.selected_cell.state is HeatmapState.OPTIMIZED
    assert heatmap.canvas.highlighted_cell == (
        HeatmapState.OPTIMIZED,
        slot_index,
    )


def test_show_all_restores_previous_congestion_filter_and_clears_highlight(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    heatmap.congestion_filter.setCurrentIndex(
        heatmap.congestion_filter.findData("five_plus")
    )
    expected = tuple(
        row for row in heatmap.detail_rows if row.frame_count >= 5
    )
    assert heatmap.visible_detail_rows == expected
    assert heatmap.view_model is not None
    two_frame = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 2
    )

    _click_cell(qtbot, heatmap, two_frame.state, two_frame.slot_index)
    assert len(heatmap.visible_detail_rows) == 2
    assert heatmap.congestion_filter.currentData() == "five_plus"
    heatmap.show_all_button.click()

    assert heatmap.table_mode is CongestionTableMode.ALL_CONGESTED
    assert heatmap.selected_cell is None
    assert heatmap.canvas.highlighted_cell is None
    assert heatmap.congestion_filter.isEnabled()
    assert heatmap.congestion_filter.currentData() == "five_plus"
    assert heatmap.visible_detail_rows == expected


def test_clicking_message_row_in_selected_mode_keeps_same_slot(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert heatmap.view_model is not None
    cell = next(
        cell for cell in heatmap.view_model.optimized_cells if cell.frame_count == 5
    )
    _click_cell(qtbot, heatmap, cell.state, cell.slot_index)
    selection = heatmap.selected_cell
    names = [row.message.message_name for row in heatmap.visible_detail_rows]

    heatmap._locate_cell_from_detail(2, 4)

    assert heatmap.selected_cell == selection
    assert heatmap.canvas.highlighted_cell == (cell.state, cell.slot_index)
    assert [row.message.message_name for row in heatmap.visible_detail_rows] == names


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


def test_cell_click_emits_once_and_does_not_rebuild_heatmap(
    qtbot, batch_result: BatchOptimizationResult, monkeypatch
) -> None:
    calls = 0
    real_builder = heatmap_module.build_heatmap_view_model

    def counted_builder(
        result: GuiOptimizationResult,
        kind: HeatmapWindowKind,
        timing_config=None,
    ):
        nonlocal calls
        calls += 1
        return real_builder(result, kind, timing_config)

    monkeypatch.setattr(heatmap_module, "build_heatmap_view_model", counted_builder)
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(_result(batch_result))
    assert calls == 1
    assert heatmap.view_model is not None
    emitted: list[tuple[str, int]] = []
    heatmap.canvas.cell_clicked.connect(
        lambda state, slot: emitted.append((state, slot))
    )
    cell = next(
        cell for cell in heatmap.view_model.optimized_cells if cell.frame_count == 2
    )

    _click_cell(qtbot, heatmap, cell.state, cell.slot_index)

    assert emitted == [(cell.state.value, cell.slot_index)]
    assert calls == 1
    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT


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


def test_no_congested_slots_still_allows_two_frame_detail(
    qtbot, batch_result: BatchOptimizationResult
) -> None:
    base = _result(batch_result)
    assert base.steady_heatmap is not None

    def cap_slots(
        slots: tuple[HeatmapSlotDetail, ...],
    ) -> tuple[HeatmapSlotDetail, ...]:
        return tuple(
            replace(
                slot,
                frame_count=min(slot.frame_count, 2),
                messages=slot.messages[:2],
            )
            for slot in slots
        )

    detail = HeatmapWindowDetail(
        base.steady_heatmap.slot_width_us,
        cap_slots(base.steady_heatmap.original_slots),
        cap_slots(base.steady_heatmap.optimized_slots),
    )
    capped = replace(
        base,
        steady_counts_before=tuple(slot.frame_count for slot in detail.original_slots),
        steady_counts_after=tuple(slot.frame_count for slot in detail.optimized_slots),
        steady_heatmap=detail,
    )
    heatmap = LoadHeatmap()
    _show(qtbot, heatmap)
    heatmap.set_result(capped)
    assert heatmap.detail_rows == ()
    assert heatmap.details_table.isHidden()
    assert heatmap.view_model is not None
    cell = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 2
    )

    _click_cell(qtbot, heatmap, cell.state, cell.slot_index)

    assert heatmap.table_mode is CongestionTableMode.SELECTED_SLOT
    assert heatmap.details_table.rowCount() == 2
    assert len(heatmap.visible_detail_rows) == 2


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
    assert next(cell for cell in heatmap.view_model.original_cells if cell.frame_count).text.splitlines()[1].endswith(" B")
    assert heatmap.details_table.item(0, 3).text().endswith(" B")
    payload_cell = next(
        cell for cell in heatmap.view_model.original_cells if cell.frame_count == 3
    )
    _click_cell(qtbot, heatmap, payload_cell.state, payload_cell.slot_index)
    assert " B | \u4fdd\u5b88 " in heatmap.detail_context_label.text()

    heatmap.set_result(frame)
    assert heatmap.view_model is not None
    assert next(cell for cell in heatmap.view_model.original_cells if cell.frame_count).text.splitlines()[1].endswith(" \u03bcs")
    assert heatmap.details_table.item(0, 3).text().endswith(" μs")
    frame_cell = next(
        cell for cell in heatmap.view_model.optimized_cells if cell.frame_count == 2
    )
    _click_cell(qtbot, heatmap, frame_cell.state, frame_cell.slot_index)
    assert " \u03bcs | \u4fdd\u5b88 " in heatmap.detail_context_label.text()


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
