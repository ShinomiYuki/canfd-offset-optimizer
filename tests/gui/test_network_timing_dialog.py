from __future__ import annotations

from pathlib import Path

from canfd_offset_optimizer.gui.contracts import (
    CLASSIC_WEIGHT_MODEL,
    FrameProtocol,
    NetworkSummary,
    NetworkTimingConfig,
    TimingConfigSource,
    WeightMode,
    WorkspaceInspection,
)
from canfd_offset_optimizer.gui.widgets.network_timing_dialog import (
    NetworkTimingDialog,
)
from canfd_offset_optimizer.gui.widgets.settings_panel import SettingsPanel


def _network(
    network_id: str, protocol: FrameProtocol, *, source_file: str | None = None
) -> NetworkSummary:
    classic = protocol is FrameProtocol.CLASSIC_CAN
    return NetworkSummary(
        network_id=network_id,
        network_name=network_id.upper(),
        display_name=network_id.upper(),
        source_file=source_file or f"{network_id}.dbc",
        source_workspace_path=Path("dbc") / (source_file or f"{network_id}.dbc"),
        is_optimizable=True,
        message_count=2,
        available_weight_modes=(
            (WeightMode.PAYLOAD_BYTES,)
            if classic
            else (WeightMode.PAYLOAD_BYTES, WeightMode.FRAME_TIME_US)
        ),
        frame_protocol=protocol,
        automatic_weight_mode=(
            WeightMode.PAYLOAD_BYTES if classic else WeightMode.FRAME_TIME_US
        ),
        classic_weight_model=CLASSIC_WEIGHT_MODEL if classic else None,
    )


def test_dialog_shows_dbc_source_and_missing_status(qtbot) -> None:
    networks = (
        _network("bd", FrameProtocol.CLASSIC_CAN),
        _network("dk", FrameProtocol.CAN_FD),
    )
    configs = (
        NetworkTimingConfig(
            "bd", 500_000, TimingConfigSource.DBC, confirmed=True
        ),
        NetworkTimingConfig("dk"),
    )
    dialog = NetworkTimingDialog(networks, configs)
    qtbot.addWidget(dialog)
    assert dialog.table.item(0, 3).text() == "DBC"
    assert dialog.table.item(0, 4).text() == "已配置"
    assert dialog.table.item(1, 3).text() == "—"
    assert dialog.table.item(1, 4).text() == "待配置"
    assert dialog.editors["bd"].text() == "500"
    assert dialog.editors["dk"].text() == ""


def test_batch_fill_only_unconfigured_can_fd_and_never_overwrites(qtbot) -> None:
    networks = (
        _network("bd", FrameProtocol.CLASSIC_CAN),
        _network("dk", FrameProtocol.CAN_FD),
        _network("gl", FrameProtocol.CAN_FD),
    )
    configs = (
        NetworkTimingConfig("bd"),
        NetworkTimingConfig(
            "dk", 250_000, TimingConfigSource.MANUAL, confirmed=True
        ),
        NetworkTimingConfig("gl"),
    )
    dialog = NetworkTimingDialog(networks, configs)
    qtbot.addWidget(dialog)
    dialog.batch_bitrate_spin.setValue(500)
    dialog.apply_to_unconfigured_fd()
    assert dialog.editors["bd"].text() == ""
    assert dialog.editors["dk"].text() == "250"
    assert dialog.editors["gl"].text() == "500"
    dialog.accept()
    assert dialog.timing_configs is not None
    by_id = {config.network_id: config for config in dialog.timing_configs}
    assert by_id["dk"].nominal_bitrate_bps == 250_000
    assert by_id["gl"].nominal_bitrate_bps == 500_000
    assert by_id["gl"].source is TimingConfigSource.MANUAL


def test_non_positive_manual_value_is_rejected(qtbot, monkeypatch) -> None:
    network = _network("dk", FrameProtocol.CAN_FD)
    dialog = NetworkTimingDialog((network,), (NetworkTimingConfig("dk"),))
    qtbot.addWidget(dialog)
    warnings: list[str] = []
    monkeypatch.setattr(
        "canfd_offset_optimizer.gui.widgets.network_timing_dialog.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    dialog.editors["dk"].setText("0")
    dialog.accept()
    assert dialog.timing_configs is None
    assert warnings and "正数" in warnings[0]


def test_missing_bitrate_does_not_block_settings_request(
    qtbot, inspection: WorkspaceInspection
) -> None:
    inspected = WorkspaceInspection(
        session=inspection.session,
        networks=inspection.networks,
        missing_required=inspection.missing_required,
        warnings=inspection.warnings,
        errors=inspection.errors,
        routing_exclusion=inspection.routing_exclusion,
        sender_selection=inspection.sender_selection,
        sender_selection_summaries=inspection.sender_selection_summaries,
        dbc_revision=inspection.dbc_revision,
        network_timing_configs=tuple(
            NetworkTimingConfig(network.network_id) for network in inspection.networks
        ),
    )
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_inspection(inspected)
    assert panel.timing_summary_label.text().endswith(
        f"0/{len(inspected.networks)}"
    )
    assert panel.can_build_request()
    request = panel.build_request()
    assert all(
        config.nominal_bitrate_bps is None
        for config in request.network_timing_configs
    )
