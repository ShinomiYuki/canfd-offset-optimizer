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


def _fd_config(network_id: str) -> NetworkTimingConfig:
    return NetworkTimingConfig(
        network_id,
        500_000,
        TimingConfigSource.MANUAL,
        confirmed=True,
        data_bitrate_bps=2_000_000,
        default_brs=True,
        data_source=TimingConfigSource.MANUAL,
        brs_source=TimingConfigSource.MANUAL,
    )


def test_dialog_has_nominal_data_brs_source_and_status_columns(qtbot) -> None:
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

    assert dialog.table.columnCount() == 7
    assert dialog.table.horizontalHeaderItem(2).text().startswith("Nominal")
    assert dialog.table.horizontalHeaderItem(3).text().startswith("Data")
    assert dialog.table.horizontalHeaderItem(4).text() == "BRS"
    assert dialog.table.item(0, 5).text() == "N:DBC"
    assert dialog.table.item(0, 6).text() == "已配置"
    assert dialog.table.item(1, 5).text() == "N:—；D:—；BRS:—"
    assert dialog.table.item(1, 6).text() == "待配置：缺少 Nominal"
    assert dialog.editors["bd"].text() == "500"
    assert not dialog.data_editors["bd"].isEnabled()
    assert not dialog.brs_combos["bd"].isEnabled()


def test_batch_fill_only_empty_can_fd_fields_and_never_classic(qtbot) -> None:
    networks = (
        _network("bd", FrameProtocol.CLASSIC_CAN),
        _network("dk", FrameProtocol.CAN_FD),
        _network("gl", FrameProtocol.CAN_FD),
    )
    configs = (
        NetworkTimingConfig("bd"),
        _fd_config("dk"),
        NetworkTimingConfig("gl"),
    )
    dialog = NetworkTimingDialog(networks, configs)
    qtbot.addWidget(dialog)
    dialog.batch_bitrate_spin.setValue(250)
    dialog.batch_data_bitrate_spin.setValue(5_000)
    dialog.batch_brs_combo.setCurrentIndex(dialog.batch_brs_combo.findData(False))

    dialog.apply_to_unconfigured_fd()

    assert dialog.editors["bd"].text() == ""
    assert dialog.data_editors["bd"].text() == ""
    assert dialog.editors["dk"].text() == "500"
    assert dialog.data_editors["dk"].text() == "2000"
    assert dialog.brs_combos["dk"].currentData() is True
    assert dialog.editors["gl"].text() == "250"
    assert dialog.data_editors["gl"].text() == "5000"
    assert dialog.brs_combos["gl"].currentData() is False

    dialog.accept()
    assert dialog.timing_configs is not None
    by_id = {config.network_id: config for config in dialog.timing_configs}
    assert by_id["dk"] == configs[1]
    assert by_id["gl"].nominal_bitrate_bps == 250_000
    assert by_id["gl"].data_bitrate_bps == 5_000_000
    assert by_id["gl"].default_brs is False
    assert by_id["gl"].nominal_source is TimingConfigSource.MANUAL


def test_dbc_per_message_brs_is_read_only_and_can_be_mixed(qtbot) -> None:
    network = _network("dk", FrameProtocol.CAN_FD)
    config = NetworkTimingConfig(
        "dk",
        500_000,
        TimingConfigSource.MANUAL,
        confirmed=True,
        data_bitrate_bps=2_000_000,
        data_source=TimingConfigSource.MANUAL,
        dbc_brs_complete=True,
        dbc_brs_mixed=True,
        dbc_brs_has_on=True,
    )
    dialog = NetworkTimingDialog((network,), (config,))
    qtbot.addWidget(dialog)

    combo = dialog.brs_combos["dk"]
    assert not combo.isEnabled()
    assert combo.currentText() == "来自 DBC / 按报文（混合）"
    assert "BRS:DBC/按报文" in dialog.table.item(0, 5).text()
    assert dialog.table.item(0, 6).text() == "已配置"


def test_brs_on_requires_data_bitrate_but_brs_off_does_not(qtbot) -> None:
    network = _network("dk", FrameProtocol.CAN_FD)
    dialog = NetworkTimingDialog(
        (network,),
        (
            NetworkTimingConfig(
                "dk",
                500_000,
                TimingConfigSource.MANUAL,
                confirmed=True,
                default_brs=True,
                brs_source=TimingConfigSource.MANUAL,
            ),
        ),
    )
    qtbot.addWidget(dialog)
    assert dialog.table.item(0, 6).text() == "待配置：缺少 Data"

    combo = dialog.brs_combos["dk"]
    combo.setCurrentIndex(combo.findData(False))
    assert dialog.table.item(0, 6).text() == "已配置"


def test_data_below_nominal_is_preserved_with_warning(qtbot) -> None:
    network = _network("dk", FrameProtocol.CAN_FD)
    dialog = NetworkTimingDialog((network,), (NetworkTimingConfig("dk"),))
    qtbot.addWidget(dialog)
    dialog.editors["dk"].setText("500")
    dialog.data_editors["dk"].setText("250")
    combo = dialog.brs_combos["dk"]
    combo.setCurrentIndex(combo.findData(True))

    assert dialog.table.item(0, 6).text() == "已配置（Data < Nominal）"
    dialog.accept()
    assert dialog.timing_configs is not None
    assert dialog.timing_configs[0].data_bitrate_bps == 250_000


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


def test_missing_timing_does_not_block_settings_request(
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