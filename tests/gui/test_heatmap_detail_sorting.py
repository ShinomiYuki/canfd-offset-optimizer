from dataclasses import replace

import pytest
from PySide6.QtCore import Qt

from canfd_offset_optimizer.gui.contracts import (
    FrameProtocol,
    HeatmapMessageDetail,
    NetworkTimingConfig,
    TimingConfigSource,
)
from canfd_offset_optimizer.gui.heatmap_view_model import (
    HeatmapCellView,
    HeatmapState,
    HeatmapWindowKind,
    build_heatmap_view_model,
    message_rows_for_cell,
    ordered_detail_cells,
)
from canfd_offset_optimizer.gui.widgets import load_heatmap as heatmap_module
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap
from canfd_offset_optimizer.timing.conservative_service import ConservativeEstimateStatus


def _cell(index, times, state=HeatmapState.ORIGINAL):
    messages = tuple(
        HeatmapMessageDetail(
            # Identical identity deliberately represents repeated releases.
            "Repeated",
            0x101,
            False,
            1_000,
            0,
            payload_bytes=8,
            conservative_service_time_us=value,
            conservative_total_bits_upper_bound=1 if value is not None else None,
            conservative_nominal_bits_upper_bound=1 if value is not None else None,
            conservative_data_bits_upper_bound=0 if value is not None else None,
            conservative_status=(
                ConservativeEstimateStatus.COMPLETE
                if value is not None
                else ConservativeEstimateStatus.UNAVAILABLE
            ),
            conservative_unavailable_reason=None if value is not None else "unknown_protocol",
        )
        for value in times
    )
    known = [t for t in times if t is not None]
    return HeatmapCellView(
        state,
        index,
        index * 5_000,
        (index + 1) * 5_000,
        len(times),
        8 * len(times),
        messages,
        "B",
        sum(known) if known or not times else None,
        len(known),
        len(times),
    )


@pytest.fixture
def detail_view(batch_result):
    result = next(r.result for r in batch_result.network_results if r.result is not None)
    base = build_heatmap_view_model(result, HeatmapWindowKind.STEADY)
    # Three longer frames exceed six short frames; 0 and ties are intentional.
    original = (
        _cell(0, (480, 400, 420)),
        _cell(1, (100,) * 6),
        _cell(2, (None, 180)),
        _cell(3, (0, 0)),
        _cell(4, (None,)),
        _cell(5, ()),
        _cell(6, (200, 100, 200, 100)),
    )
    optimized = tuple(replace(c, state=HeatmapState.OPTIMIZED) for c in original)
    return result, replace(base, original_cells=original, optimized_cells=optimized)


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_slot_numeric_sort_is_stable_and_incomplete_groups_are_last(detail_view, order):
    _, view = detail_view
    groups = ordered_detail_cells(view, "nonempty", order)
    complete = [c for c in groups if c.conservative_complete_count == c.frame_count]
    totals = [c.conservative_total_time_us for c in complete]
    assert totals == sorted(totals, reverse=order == "desc")
    assert [c.slot_index for c in groups[-4:]] == [2, 4, 2, 4]
    ties = [(c.state, c.slot_index) for c in complete if c.conservative_total_time_us == 600]
    assert ties == [(s, i) for s in HeatmapState for i in (1, 6)]
    assert next(c for c in groups if c.slot_index == 0).conservative_total_time_us == 1300
    assert all(c.slot_index != 0 for c in ordered_detail_cells(view, "all", order))
    assert {c.frame_count for c in ordered_detail_cells(view, "four", order)} == {4}
    assert {c.frame_count for c in ordered_detail_cells(view, "five_plus", order)} == {6}


def test_message_order_restores_original_and_keeps_zero_unknown_and_releases(detail_view):
    _, view = detail_view
    cell = view.original_cells[0]
    assert [r.message.conservative_service_time_us for r in message_rows_for_cell(cell, "asc")] == [
        400,
        420,
        480,
    ]
    assert [
        r.message.conservative_service_time_us for r in message_rows_for_cell(cell, "desc")
    ] == [480, 420, 400]
    assert tuple(r.message for r in message_rows_for_cell(cell)) == cell.messages
    for order in ("asc", "desc"):
        assert [
            r.message.conservative_service_time_us
            for r in message_rows_for_cell(view.original_cells[2], order)
        ] == [180, None]
        assert [
            r.message.conservative_service_time_us
            for r in message_rows_for_cell(view.original_cells[3], order)
        ] == [0, 0]
    ties = view.original_cells[6]
    sorted_rows = message_rows_for_cell(ties, "desc")
    assert [r.message for r in sorted_rows] == [ties.messages[i] for i in (0, 2, 1, 3)]
    assert len(message_rows_for_cell(view.original_cells[1])) == 6


def test_real_estimator_orders_three_long_frames_before_six_short_frames(batch_result):
    result = next(r.result for r in batch_result.network_results if r.result is not None)
    detail = result.steady_heatmap
    source = next(m for slot in detail.original_slots for m in slot.messages)
    slots = list(detail.original_slots)
    for index, count, payload in ((0, 3, 64), (1, 6, 8)):
        message = replace(source, frame_protocol=FrameProtocol.CAN_FD, payload_bytes=payload)
        slots[index] = replace(
            slots[index],
            messages=(message,) * count,
            frame_count=count,
            conservative_total_time_us=None,
            conservative_complete_count=0,
            conservative_total_count=count,
        )
    result = replace(
        result,
        steady_heatmap=replace(detail, original_slots=tuple(slots)),
        steady_counts_before=tuple(s.frame_count for s in slots),
    )
    config = NetworkTimingConfig(
        result.network_id,
        500_000,
        TimingConfigSource.MANUAL,
        confirmed=True,
        default_brs=False,
        brs_source=TimingConfigSource.MANUAL,
    )
    view = build_heatmap_view_model(result, HeatmapWindowKind.STEADY, config)
    assert (
        view.original_cells[0].conservative_total_time_us
        > view.original_cells[1].conservative_total_time_us
    )
    ordered = ordered_detail_cells(view, "nonempty", "desc")
    assert ordered.index(view.original_cells[0]) < ordered.index(view.original_cells[1])
    assert len(message_rows_for_cell(view.original_cells[1])) == 6
    assert view.original_cells[0] not in ordered_detail_cells(view, "all", "desc")


@pytest.mark.parametrize("kind", list(HeatmapWindowKind))
def test_two_sort_controls_selection_return_and_group_identity(
    qtbot, monkeypatch, detail_view, kind
):
    result, view = detail_view
    view = replace(view, window_kind=kind)
    monkeypatch.setattr(heatmap_module, "build_heatmap_view_model", lambda *args: view)
    widget = LoadHeatmap()
    qtbot.addWidget(widget)
    widget.resize(620, 720)
    widget.show()
    widget.set_result(result)
    natural = widget.visible_detail_rows
    widget.slot_sort.setCurrentIndex(2)
    widget.message_sort.setCurrentIndex(1)
    assert [r.message.conservative_service_time_us for r in widget.visible_detail_rows[:3]] == [
        400,
        420,
        480,
    ]
    assert [(r.state, r.slot_index) for r in widget.visible_detail_rows[:3]] == [
        (HeatmapState.ORIGINAL, 0)
    ] * 3
    sorted_groups = [(r.state, r.slot_index) for r in widget.visible_detail_rows]
    widget.message_sort.setCurrentIndex(0)
    assert [(r.state, r.slot_index) for r in widget.visible_detail_rows] == sorted_groups
    assert [r.message.conservative_service_time_us for r in widget.visible_detail_rows[:3]] == [
        480,
        400,
        420,
    ]
    widget.message_sort.setCurrentIndex(1)
    widget.slot_sort.setCurrentIndex(0)
    assert [(r.state, r.slot_index) for r in widget.visible_detail_rows] == [
        (r.state, r.slot_index) for r in natural
    ]
    assert [r.message.conservative_service_time_us for r in widget.visible_detail_rows[:3]] == [
        400,
        420,
        480,
    ]
    widget.slot_sort.setCurrentIndex(2)
    table = widget.details_table
    partial_headers = [
        table.item(i, 0).text() for i in range(table.rowCount()) if table.columnSpan(i, 0) > 1
    ]
    assert any("≥180 μs" in text and "已知 1/2 帧" in text for text in partial_headers)
    assert any("保守 —" in text and "已知 0/1 帧" in text for text in partial_headers)
    # Both a sorted member row and its group header retain the full identity.
    identity = table.item(1, 0).data(Qt.ItemDataRole.UserRole + 3)
    assert identity == view.selection_for(HeatmapState.ORIGINAL, 0)
    assert table.item(0, 0).data(Qt.ItemDataRole.UserRole + 3) == identity
    widget._locate_cell_from_detail(1, 4)
    assert widget.selected_cell == identity
    assert not widget.slot_sort.isEnabled()
    assert not widget.congestion_filter.isEnabled()
    assert widget.message_sort.isEnabled()
    widget.message_sort.setCurrentIndex(2)
    assert [r.message.conservative_service_time_us for r in widget.visible_detail_rows] == [
        480,
        420,
        400,
    ]
    widget.show_all_button.click()
    assert widget.slot_sort.isEnabled()
    assert widget.slot_sort.currentData() == widget.message_sort.currentData() == "desc"
    widget.congestion_filter.setCurrentIndex(1)
    assert all(r.frame_count >= 4 for r in widget.visible_detail_rows)
    widget.canvas.cell_clicked.emit("optimized", 5)
    assert widget.visible_detail_rows == ()
    assert "没有报文释放" in widget.details_empty_label.text()
    assert not widget.slot_sort.isEnabled()
    widget.show_all_button.click()
    assert widget.congestion_filter.currentData() == "all"
    widget.congestion_filter.setCurrentIndex(0)
    widget.slot_sort.setCurrentIndex(0)
    widget.message_sort.setCurrentIndex(0)
    assert widget.visible_detail_rows == natural
    assert widget.canvas.highlighted_cell is None
