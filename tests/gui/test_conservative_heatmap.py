from __future__ import annotations

from dataclasses import replace

from canfd_offset_optimizer.gui.contracts import (
    BatchOptimizationResult,
    FrameProtocol,
    HeatmapWindowDetail,
    NetworkTimingConfig,
    TimingConfigSource,
    WeightMode,
)
from canfd_offset_optimizer.gui.heatmap_view_model import (
    HeatmapWindowKind,
    build_heatmap_view_model,
    conservative_estimate_cache_info,
    message_rows_for_cell,
)
from canfd_offset_optimizer.gui.widgets.load_heatmap import LoadHeatmap, ROW_HEIGHT


def _result(batch: BatchOptimizationResult):
    return next(item.result for item in batch.network_results if item.result is not None)


def _config(
    network_id: str,
    bitrate: int,
    *,
    data_bitrate: int = 2_000_000,
    brs: bool = True,
) -> NetworkTimingConfig:
    return NetworkTimingConfig(
        network_id,
        bitrate,
        TimingConfigSource.MANUAL,
        confirmed=True,
        data_bitrate_bps=data_bitrate,
        default_brs=brs,
        data_source=TimingConfigSource.MANUAL,
        brs_source=TimingConfigSource.MANUAL,
    )


def test_same_optimization_result_gets_different_diagnostics_without_assignment_change(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    before_assignments = result.assignments
    before_metrics = (result.original_metrics, result.optimized_metrics)
    before_hash = result.assignment_hash
    view_500 = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, _config(result.network_id, 500_000)
    )
    view_250 = build_heatmap_view_model(
        result,
        HeatmapWindowKind.STEADY,
        _config(result.network_id, 250_000, data_bitrate=1_000_000),
    )
    cell_500 = next(cell for cell in view_500.original_cells if cell.frame_count)
    cell_250 = view_250.original_cells[cell_500.slot_index]
    assert cell_500.conservative_total_time_us is not None
    assert cell_250.conservative_total_time_us == 2 * cell_500.conservative_total_time_us
    assert result.assignments == before_assignments
    assert (result.original_metrics, result.optimized_metrics) == before_metrics
    assert result.assignment_hash == before_hash


def test_slot_total_is_strict_sum_of_formal_members_for_both_states(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    view = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, _config(result.network_id, 500_000)
    )
    for cells in (view.original_cells, view.optimized_cells):
        for cell in tuple(item for item in cells if item.frame_count)[:5]:
            assert cell.conservative_complete_count == cell.frame_count
            assert cell.conservative_total_time_us == sum(
                message.conservative_service_time_us or 0
                for message in cell.messages
            )


def test_zero_partial_and_unavailable_cells_are_not_confused_with_zero(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    detail = result.steady_heatmap
    assert detail is not None
    target = next(slot for slot in detail.original_slots if slot.frame_count >= 2)
    partial_messages = (
        replace(
            target.messages[0],
            payload_bytes=None,
            conservative_service_time_us=None,
            conservative_total_bits_upper_bound=None,
            conservative_nominal_bits_upper_bound=None,
            conservative_data_bits_upper_bound=None,
            conservative_unavailable_reason="invalid_payload_length",
        ),
        *target.messages[1:],
    )
    partial_slot = replace(target, messages=partial_messages)
    partial_detail = HeatmapWindowDetail(
        detail.slot_width_us,
        tuple(
            partial_slot if slot.slot_index == target.slot_index else slot
            for slot in detail.original_slots
        ),
        detail.optimized_slots,
    )
    partial_result = replace(result, steady_heatmap=partial_detail)
    view = build_heatmap_view_model(
        partial_result,
        HeatmapWindowKind.STEADY,
        _config(result.network_id, 500_000),
    )
    partial = view.original_cells[target.slot_index]
    assert partial.conservative_complete_count == partial.frame_count - 1
    assert partial.conservative_total_time_us is not None
    assert partial.conservative_text.startswith("保守 ≥")
    assert partial.conservative_text.endswith(" μs*")

    missing = build_heatmap_view_model(result, HeatmapWindowKind.STEADY)
    unavailable = next(cell for cell in missing.original_cells if cell.frame_count)
    assert unavailable.conservative_total_time_us is None
    assert unavailable.conservative_text == "保守 —"
    empty = next(cell for cell in missing.original_cells if cell.frame_count == 0)
    assert empty.conservative_total_time_us == 0
    assert empty.conservative_text == "保守 0 μs"


def test_payload_and_frame_time_weights_share_same_conservative_third_line(
    batch_result: BatchOptimizationResult,
) -> None:
    base = _result(batch_result)
    payload = replace(
        base,
        weight_mode=WeightMode.PAYLOAD_BYTES,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    physical = replace(payload, weight_mode=WeightMode.FRAME_TIME_US)
    config = _config(base.network_id, 500_000)
    payload_view = build_heatmap_view_model(payload, HeatmapWindowKind.STEADY, config)
    physical_view = build_heatmap_view_model(physical, HeatmapWindowKind.STEADY, config)
    index = next(
        cell.slot_index for cell in payload_view.original_cells if cell.frame_count
    )
    payload_cell = payload_view.original_cells[index]
    physical_cell = physical_view.original_cells[index]
    assert payload_cell.text.splitlines()[1].endswith(" B")
    assert physical_cell.text.splitlines()[1].endswith(" μs")
    assert payload_cell.text.splitlines()[2] == physical_cell.text.splitlines()[2]


def test_detail_rows_expose_payload_bytes_and_independent_message_time(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    view = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, _config(result.network_id, 500_000)
    )
    cell = next(cell for cell in view.optimized_cells if cell.frame_count)
    rows = message_rows_for_cell(cell)
    assert len(rows) == cell.frame_count
    assert all(row.payload_text not in {"", "—"} for row in rows)
    assert all(row.conservative_time_text not in {"", "—"} for row in rows)
    assert sum(int(row.conservative_time_text) for row in rows) == cell.conservative_total_time_us


def test_widget_refreshes_bitrate_without_rebinding_or_rerun(
    qtbot,
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    widget = LoadHeatmap()
    qtbot.addWidget(widget)
    widget.set_result(result)
    widget.set_timing_config(_config(result.network_id, 500_000))
    assert widget.view_model is not None
    cell_500 = next(cell for cell in widget.view_model.original_cells if cell.frame_count)
    assignment_identity = result.assignments
    widget.set_timing_config(
        _config(result.network_id, 250_000, data_bitrate=1_000_000)
    )
    assert widget.view_model is not None
    cell_250 = widget.view_model.original_cells[cell_500.slot_index]
    assert cell_250.conservative_total_time_us == 2 * cell_500.conservative_total_time_us
    assert result.assignments is assignment_identity
    assert widget.details_table.columnCount() == 10
    assert widget.details_table.horizontalHeaderItem(6).text() == "长度(Byte)"
    assert widget.details_table.horizontalHeaderItem(9).text() == "保守占用时间(μs)"
    assert ROW_HEIGHT >= 88


def test_selected_slot_table_displays_real_8_16_and_64_byte_payloads(
    qtbot,
    batch_result: BatchOptimizationResult,
) -> None:
    base = _result(batch_result)
    detail = base.steady_heatmap
    assert detail is not None
    target = next(slot for slot in detail.original_slots if slot.frame_count >= 3)
    payloads = (8, 16, 64)
    messages = tuple(
        replace(
            message,
            payload_bytes=payloads[index],
            frame_protocol=FrameProtocol.CAN_FD,
        )
        if index < len(payloads)
        else message
        for index, message in enumerate(target.messages)
    )
    changed_slot = replace(target, messages=messages)
    changed_detail = HeatmapWindowDetail(
        detail.slot_width_us,
        tuple(
            changed_slot if slot.slot_index == target.slot_index else slot
            for slot in detail.original_slots
        ),
        detail.optimized_slots,
    )
    result = replace(
        base,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
        steady_heatmap=changed_detail,
    )
    widget = LoadHeatmap()
    qtbot.addWidget(widget)
    widget.set_result(result)
    widget.set_timing_config(_config(result.network_id, 500_000))

    widget.canvas.cell_clicked.emit("original", target.slot_index)

    displayed_payloads = {
        widget.details_table.item(row, 6).text()
        for row in range(widget.details_table.rowCount())
    }
    displayed_times = {
        widget.details_table.item(row, 9).text()
        for row in range(widget.details_table.rowCount())
    }
    assert {"8", "16", "64"}.issubset(displayed_payloads)
    assert "—" not in displayed_times
    assert widget.details_table.horizontalHeaderItem(6).text() == "长度(Byte)"
    assert widget.details_table.horizontalHeaderItem(9).text() == "保守占用时间(μs)"


def test_unknown_brs_and_missing_data_have_distinct_unavailable_reasons(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    unknown_brs = NetworkTimingConfig(
        result.network_id,
        500_000,
        TimingConfigSource.MANUAL,
        confirmed=True,
        data_bitrate_bps=2_000_000,
        data_source=TimingConfigSource.MANUAL,
    )
    missing_data = NetworkTimingConfig(
        result.network_id,
        500_000,
        TimingConfigSource.MANUAL,
        confirmed=True,
        default_brs=True,
        brs_source=TimingConfigSource.MANUAL,
    )

    unknown_view = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, unknown_brs
    )
    missing_view = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, missing_data
    )
    unknown = next(
        message
        for cell in unknown_view.original_cells
        for message in cell.messages
    )
    missing = next(
        message
        for cell in missing_view.original_cells
        for message in cell.messages
    )
    assert unknown.conservative_unavailable_reason == "unknown_brs"
    assert missing.conservative_unavailable_reason == "missing_can_fd_data_bitrate"


def test_per_message_dbc_brs_precedes_network_default(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    detail = result.steady_heatmap
    assert detail is not None
    target = next(slot for slot in detail.original_slots if slot.frame_count)
    changed_message = replace(
        target.messages[0],
        dbc_brs=False,
        dbc_brs_source="DBC:CANFD_BRS",
    )
    changed_slot = replace(
        target,
        messages=(changed_message, *target.messages[1:]),
    )
    changed_detail = HeatmapWindowDetail(
        detail.slot_width_us,
        tuple(
            changed_slot if slot.slot_index == target.slot_index else slot
            for slot in detail.original_slots
        ),
        detail.optimized_slots,
    )
    changed_result = replace(result, steady_heatmap=changed_detail)
    view = build_heatmap_view_model(
        changed_result,
        HeatmapWindowKind.STEADY,
        _config(result.network_id, 500_000, brs=True),
    )
    message = view.original_cells[target.slot_index].messages[0]
    assert message.effective_brs is False
    assert message.effective_brs_source == "DBC:CANFD_BRS"
    assert message.conservative_data_bits_upper_bound == 0


def test_data_rate_change_invalidates_diagnostic_cache_only(
    batch_result: BatchOptimizationResult,
) -> None:
    result = _result(batch_result)
    before = conservative_estimate_cache_info()
    at_2m = build_heatmap_view_model(
        result, HeatmapWindowKind.STEADY, _config(result.network_id, 500_000)
    )
    middle = conservative_estimate_cache_info()
    at_5m = build_heatmap_view_model(
        result,
        HeatmapWindowKind.STEADY,
        _config(result.network_id, 500_000, data_bitrate=5_000_000),
    )
    after = conservative_estimate_cache_info()
    index = next(cell.slot_index for cell in at_2m.original_cells if cell.frame_count)
    assert (
        at_5m.original_cells[index].conservative_total_time_us
        < at_2m.original_cells[index].conservative_total_time_us
    )
    assert middle.misses >= before.misses
    assert after.misses > middle.misses
    assert result.assignment_hash


def test_payload_can_fd_top_unit_is_bytes_per_slot(
    qtbot,
    batch_result: BatchOptimizationResult,
) -> None:
    base = _result(batch_result)
    result = replace(
        base,
        weight_mode=WeightMode.PAYLOAD_BYTES,
        frame_protocol=FrameProtocol.CAN_FD,
        classic_weight_model=None,
    )
    widget = LoadHeatmap()
    qtbot.addWidget(widget)
    widget.set_result(result)
    widget.set_timing_config(_config(result.network_id, 500_000))
    assert "数值单位：B/slot" in widget.weight_basis_label.text()
