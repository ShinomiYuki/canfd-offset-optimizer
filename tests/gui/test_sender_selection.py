from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
import pytest

import canfd_offset_optimizer.gui.main_window as main_window_module
from canfd_offset_optimizer.gui.artifact_outputs import (
    write_message_eligibility_csv,
    write_run_config_json,
)
from canfd_offset_optimizer.gui.contracts import (
    CancellationToken,
    GuiBatchOptimizationRequest,
    MessageEligibilityStatus,
    OptimizationMode,
    RestartMode,
    RestartSettings,
    SenderNodeSelectionConfig,
    SenderSelectionDbcStatus,
    WeightMode,
)
from canfd_offset_optimizer.exceptions import InputFileError
from canfd_offset_optimizer.gui.main_window import MainWindow
from canfd_offset_optimizer.gui.real_backend import RealBackend
from canfd_offset_optimizer.gui.sender_selection import (
    build_sender_inventory,
    dbc_identity,
    reconcile_selection,
)
from canfd_offset_optimizer.gui.state import WorkflowState
from canfd_offset_optimizer.gui.view_models import (
    MessageEligibilityFilterProxy,
    MessageEligibilityTableModel,
    NetworkDetailsTableModel,
)
from canfd_offset_optimizer.gui.widgets.sender_selection_dialog import (
    SenderSelectionDialog,
)
from canfd_offset_optimizer.parsers.dbc_parser import parse_dbc


def _matrix_dbc(path: Path) -> Path:
    source = Path("tests/fixtures/dbc/minimal.dbc").read_text(encoding="utf-8")
    source = source.replace("BU_: VCU", "BU_: LocalAlpha RemoteBeta AliasGamma")
    source = source.replace("BO_ 913 Msg391: 8 VCU", "BO_ 913 Msg391: 8 LocalAlpha")
    source = source.replace(
        "BO_ 2147484768 Msg460Ext: 16 VCU",
        "BO_ 2147484768 Msg460Ext: 16 RemoteBeta",
    )
    source = source.replace("BO_ 350 EventOnly: 8 VCU", "BO_ 350 EventOnly: 8 LocalAlpha")
    definition_anchor = "BO_ 400 RxCyclic: 8 Vector__XXX\n"
    source = source.replace(
        definition_anchor,
        "BO_ 700 SharedPeriodic: 8 LocalAlpha\n"
        ' SG_ SharedValue : 0|8@1+ (1,0) [0|255] "" Vector__XXX\n\n'
        "BO_TX_BU_ 700 : LocalAlpha,AliasGamma;\n\n"
        + definition_anchor,
    )
    source += (
        '\nBA_ "GenMsgCycleTime" BO_ 700 50;\n'
        'BA_ "GenMsgStartDelayTime" BO_ 700 20;\n'
        'BA_ "GenMsgSendType" BO_ 700 "Cyclic";\n'
        'BA_ "VFrameFormat" BO_ 700 "StandardCAN_FD";\n'
    )
    path.write_text(source, encoding="utf-8")
    return path


def _inspect(tmp_path: Path, *dbc_paths: Path) -> tuple[RealBackend, object]:
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    session = backend.import_inputs(dbc_paths, lambda _update: None, CancellationToken())
    inspection = backend.inspect_workspace(
        session, lambda _update: None, CancellationToken()
    )
    return backend, inspection


def _selection(
    inspection: object,
    *,
    node: str = "LocalAlpha",
    exclude: frozenset[str] = frozenset(),
) -> SenderNodeSelectionConfig:
    summaries = inspection.sender_selection_summaries
    return SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={
            summary.dbc_id: frozenset({node})
            for summary in summaries
            if summary.dbc_id not in exclude
        },
        excluded_dbc_ids=exclude,
        confirmed=True,
        dbc_revision=inspection.dbc_revision,
    )


def _request(inspection: object, output_root: Path) -> GuiBatchOptimizationRequest:
    return GuiBatchOptimizationRequest(
        inspection=inspection,
        can_fd_weight=WeightMode.PAYLOAD_BYTES,
        mode=OptimizationMode.PEAK,
        balanced_tolerance=0.05,
        restart=RestartSettings(mode=RestartMode.FIXED, fixed_attempts=1),
        candidate_pool_size=1,
        enable_triple_search=False,
        output_root=output_root,
        sender_selection=inspection.sender_selection,
    )


def test_parser_exact_sender_filter_and_multi_transmitter_intersection(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")

    local = parse_dbc(dbc, selected_transmitters=frozenset({"LocalAlpha"}))
    remote = parse_dbc(dbc, selected_transmitters=frozenset({"RemoteBeta"}))
    alias = parse_dbc(dbc, selected_transmitters=frozenset({"AliasGamma"}))
    with pytest.raises(InputFileError, match="no eligible periodic TX"):
        parse_dbc(dbc, selected_transmitters=frozenset({"Local"}))

    assert [item.name for item in local.messages] == ["Msg391", "SharedPeriodic"]
    assert [item.name for item in remote.messages] == ["Msg460Ext"]
    assert [item.name for item in alias.messages] == ["SharedPeriodic"]
    assert alias.messages[0].transmitter_nodes == ("LocalAlpha", "AliasGamma")


def test_inspection_requires_explicit_per_dbc_selection_and_defaults_unchecked(
    qtbot, tmp_path: Path
) -> None:
    first = _matrix_dbc(tmp_path / "first.dbc")
    second = _matrix_dbc(tmp_path / "second.dbc")
    backend, inspection = _inspect(tmp_path, first, second)

    assert not inspection.sender_selection.confirmed
    assert not inspection.can_optimize
    assert all(
        summary.status is SenderSelectionDbcStatus.UNPROCESSED
        for summary in inspection.sender_selection_summaries
    )
    assert len({summary.dbc_id for summary in inspection.sender_selection_summaries}) == 2

    dialog = SenderSelectionDialog(inspection)
    qtbot.addWidget(dialog)
    assert dialog.dbc_table.rowCount() == 2
    assert dialog.node_table.rowCount() >= 3
    assert all(
        dialog.node_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(dialog.node_table.rowCount())
    )
    assert dialog.selection_config is None
    del backend


def test_selection_is_per_dbc_supports_multiple_nodes_and_explicit_exclusion(
    tmp_path: Path,
) -> None:
    first = _matrix_dbc(tmp_path / "first.dbc")
    second = _matrix_dbc(tmp_path / "second.dbc")
    backend, inspection = _inspect(tmp_path, first, second)
    one, two = inspection.sender_selection_summaries
    config = SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={
            one.dbc_id: frozenset({"LocalAlpha", "AliasGamma"})
        },
        excluded_dbc_ids=frozenset({two.dbc_id}),
        confirmed=True,
        dbc_revision=inspection.dbc_revision,
    )

    updated = backend.apply_sender_selection(inspection, config)

    assert updated.sender_selection.selected_for(one.dbc_id) == frozenset(
        {"LocalAlpha", "AliasGamma"}
    )
    assert updated.sender_selection.selected_for(two.dbc_id) == frozenset()
    assert updated.sender_selection_summaries[1].excluded_by_user
    assert updated.sender_selection_summaries[1].status is SenderSelectionDbcStatus.EXCLUDED_BY_USER
    assert len(updated.optimizable_networks) == 1


def test_preview_and_real_request_exclude_other_ecu_and_route_after_sender(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    digest = "a" * 64
    inventory = build_sender_inventory(
        dbc_id=dbc_identity(Path("dbc/matrix.dbc"), digest),
        dbc_file=dbc.name,
        network_id="net-test",
        network_name="matrix",
        source_workspace_path=Path("dbc/matrix.dbc"),
        sha256=digest,
        dbc_path=dbc,
        allowed_offsets_us=tuple(range(15_000, 100_001, 5_000)),
        routing_excluded_can_ids=frozenset({0x2BC}),
    )
    inspection_stub = type("Inspection", (), {})()
    inspection_stub.sender_selection_summaries = (inventory,)
    inspection_stub.dbc_revision = "revision"
    config = SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={inventory.dbc_id: frozenset({"LocalAlpha"})},
        confirmed=True,
        dbc_revision="revision",
    )
    from canfd_offset_optimizer.gui.sender_selection import apply_selection_to_summary

    preview = apply_selection_to_summary(inventory, config)
    by_name = {item.message_name: item for item in preview.messages}
    assert by_name["Msg460Ext"].final_status is MessageEligibilityStatus.EXCLUDED_UNSELECTED_TRANSMITTER
    assert by_name["SharedPeriodic"].final_status is MessageEligibilityStatus.ROUTING_EXCLUDED
    assert by_name["Msg391"].final_status is MessageEligibilityStatus.FINAL_ELIGIBLE
    assert preview.final_eligible_count == 1


def test_real_backend_never_sends_other_ecu_messages_to_gcls_or_assignment(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    updated = backend.apply_sender_selection(inspection, _selection(inspection))
    result = backend.optimize_all_networks(
        _request(updated, tmp_path / "out"),
        lambda _update: None,
        CancellationToken(),
    )

    item = result.network_results[0]
    assert item.result is not None
    assignment_names = {row.message_name for row in item.result.assignments}
    assert assignment_names == {"Msg391", "SharedPeriodic"}
    assert "Msg460Ext" not in assignment_names
    audit_path = result.output_directory / "results" / "message_eligibility.csv"
    config_path = result.output_directory / "results" / "run_config.json"
    assert audit_path.is_file()
    assert config_path.is_file()
    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "sender_node_selection"
    ]["confirmed"] is True


def test_revision_reconciliation_uses_path_and_hash_not_filename(tmp_path: Path) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, first = _inspect(tmp_path / "first", dbc)
    confirmed = backend.apply_sender_selection(first, _selection(first)).sender_selection

    same_backend, same = _inspect(tmp_path / "same", dbc)
    preserved = reconcile_selection(confirmed, same.sender_selection_summaries)
    assert preserved.confirmed
    assert preserved.selected_transmitters_by_dbc

    dbc.write_text(dbc.read_text(encoding="utf-8") + "\nCM_ \"changed\";\n", encoding="utf-8")
    changed_backend, changed = _inspect(tmp_path / "changed", dbc)
    invalidated = reconcile_selection(confirmed, changed.sender_selection_summaries)
    assert not invalidated.confirmed
    assert not invalidated.selected_transmitters_by_dbc
    del same_backend, changed_backend


def test_output_records_confirmed_selection_and_each_message_reason(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    updated = backend.apply_sender_selection(inspection, _selection(inspection))
    request = _request(updated, tmp_path / "out")
    config_path = write_run_config_json(request, tmp_path / "run_config.json")
    audit_path = write_message_eligibility_csv(
        request, tmp_path / "message_eligibility.csv"
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    selection = payload["sender_node_selection"]
    assert selection["confirmed"] is True
    assert selection["dbc_selections"][0]["selected_transmitters"] == ["LocalAlpha"]
    with audit_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["message_name"] for row in rows} >= {"Msg391", "Msg460Ext"}
    remote = next(row for row in rows if row["message_name"] == "Msg460Ext")
    assert remote["final_status"] == "excluded_unselected_transmitter"
    assert remote["selected_transmitter_match"] == "false"


def test_details_models_expose_counts_and_reason_filters(tmp_path: Path) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    updated = backend.apply_sender_selection(inspection, _selection(inspection))

    network_model = NetworkDetailsTableModel()
    network_model.set_inspection(updated)
    headers = [
        network_model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(network_model.columnCount())
    ]
    assert "DBC 报文总数" in headers
    assert "本机节点发送报文" in headers
    assert "其他 ECU 排除" in headers
    assert "最终参与优化" in headers

    messages = MessageEligibilityTableModel()
    messages.set_inspection(updated)
    proxy = MessageEligibilityFilterProxy(messages)
    proxy.set_filter_name("unselected")
    assert proxy.rowCount() == 1
    record = messages.record_at(proxy.mapToSource(proxy.index(0, 0)).row())
    assert record.message_name == "Msg460Ext"
    assert record.exclusion_reason


def test_main_window_gate_tooltip_and_explicit_apply(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend = RealBackend(workspace_root=tmp_path / "workspace")
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    window.import_sources((dbc,))
    qtbot.waitUntil(
        lambda: not window.task_active
        and window.workflow_state is WorkflowState.AWAITING_SENDER_SELECTION,
        timeout=5_000,
    )
    assert not window.progress_panel.run_button.isEnabled()
    assert window.progress_panel.run_button.toolTip() == "请先完成 DBC 本机发送节点选择。"
    assert "待发送节点筛选" in window.settings_panel.networks_label.text()

    class AutoSelectionDialog:
        def __init__(self, inspection: object, parent: object) -> None:
            del parent
            self.selection_config = _selection(inspection)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "SenderSelectionDialog", AutoSelectionDialog)
    window.edit_sender_selection()
    assert window.workflow_state is WorkflowState.READY
    assert window.progress_panel.run_button.isEnabled()
    assert "已完成" in window.settings_panel.sender_selection_label.text()
    window.settings_panel.offset_min_spin.setValue(105)
    assert not window.progress_panel.run_button.isEnabled()
    assert window.progress_panel.run_button.toolTip() == "请检查批量优化参数。"
    window.settings_panel.offset_min_spin.setValue(15)
    assert window.progress_panel.run_button.isEnabled()


def test_selection_change_invalidates_existing_result(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    selected = backend.apply_sender_selection(inspection, _selection(inspection))
    batch = backend.optimize_all_networks(
        _request(selected, tmp_path / "out"), lambda _update: None, CancellationToken()
    )
    window = MainWindow(backend, dialog_handler=lambda *_args: None)
    qtbot.addWidget(window)
    window._inspection = selected
    window._result = batch
    window._state._state = WorkflowState.SUCCEEDED
    dbc_id = selected.sender_selection_summaries[0].dbc_id

    class ExcludeDialog:
        def __init__(self, current: object, parent: object) -> None:
            del parent
            self.selection_config = SenderNodeSelectionConfig(
                excluded_dbc_ids=frozenset({dbc_id}),
                confirmed=True,
                dbc_revision=current.dbc_revision,
            )

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "SenderSelectionDialog", ExcludeDialog)
    window.edit_sender_selection()
    assert window.result is None
    assert window.workflow_state is WorkflowState.INCOMPLETE
    assert not window.progress_panel.run_button.isEnabled()



def test_dialog_blocks_unprocessed_dbc_and_propagates_only_after_user_action(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _matrix_dbc(tmp_path / "first.dbc")
    second = _matrix_dbc(tmp_path / "second.dbc")
    _backend, inspection = _inspect(tmp_path, first, second)
    dialog = SenderSelectionDialog(inspection)
    qtbot.addWidget(dialog)

    local_row = next(
        row
        for row in range(dialog.node_table.rowCount())
        if dialog.node_table.item(row, 1).text() == "LocalAlpha"
    )
    dialog.node_table.item(local_row, 0).setCheckState(Qt.CheckState.Checked)
    assert len(dialog._draft_config().selected_transmitters_by_dbc) == 1
    dialog._select_same_names()
    assert len(dialog._draft_config().selected_transmitters_by_dbc) == 2
    dialog._clear_current()
    warnings: list[str] = []
    monkeypatch.setattr(
        "canfd_offset_optimizer.gui.widgets.sender_selection_dialog.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    dialog._apply()
    assert dialog.selection_config is None
    assert warnings and "仍有" in warnings[0]


def test_unknown_placeholder_is_visible_but_cannot_be_selected(
    qtbot, tmp_path: Path
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    _backend, inspection = _inspect(tmp_path, dbc)
    dialog = SenderSelectionDialog(inspection)
    qtbot.addWidget(dialog)
    unknown_row = next(
        row
        for row in range(dialog.node_table.rowCount())
        if "不可选择" in dialog.node_table.item(row, 1).text()
    )
    checkbox = dialog.node_table.item(unknown_row, 0)
    assert not bool(checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert not bool(checkbox.flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_all_dbcs_excluded_is_confirmed_but_cannot_create_optimization_request(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    dbc_id = inspection.sender_selection_summaries[0].dbc_id
    config = SenderNodeSelectionConfig(
        excluded_dbc_ids=frozenset({dbc_id}),
        confirmed=True,
        dbc_revision=inspection.dbc_revision,
    )
    updated = backend.apply_sender_selection(inspection, config)

    assert updated.sender_selection_ready
    assert not updated.can_optimize
    assert updated.optimizable_networks == ()
    assert updated.networks[0].unoptimizable_reason == "用户明确排除该 DBC"
    with pytest.raises(ValueError, match="not ready"):
        _request(updated, tmp_path / "out")


def test_selected_node_without_periodic_candidate_has_explicit_reason(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    text = dbc.read_text(encoding="utf-8")
    text = text.replace(
        "BU_: LocalAlpha RemoteBeta AliasGamma",
        "BU_: LocalAlpha RemoteBeta AliasGamma IdleDelta",
    ).replace(
        "BO_ 350 EventOnly: 8 LocalAlpha",
        "BO_ 350 EventOnly: 8 IdleDelta",
    )
    dbc.write_text(text, encoding="utf-8")
    backend, inspection = _inspect(tmp_path, dbc)
    updated = backend.apply_sender_selection(
        inspection, _selection(inspection, node="IdleDelta")
    )

    network = updated.networks[0]
    assert not network.is_optimizable
    assert network.unoptimizable_reason == (
        "所选本机节点没有基础合资格周期 TX 报文"
    )
    event = next(
        record
        for record in updated.sender_selection_summaries[0].messages
        if record.message_name == "EventOnly"
    )
    assert event.final_status is MessageEligibilityStatus.NON_PERIODIC


def test_new_dbc_makes_reconciled_selection_incomplete(tmp_path: Path) -> None:
    first = _matrix_dbc(tmp_path / "first.dbc")
    backend, initial = _inspect(tmp_path / "initial", first)
    confirmed = backend.apply_sender_selection(initial, _selection(initial)).sender_selection
    second = _matrix_dbc(tmp_path / "second.dbc")
    _next_backend, changed = _inspect(tmp_path / "changed", first, second)

    reconciled = reconcile_selection(confirmed, changed.sender_selection_summaries)

    assert not reconciled.confirmed
    assert len(reconciled.selected_transmitters_by_dbc) == 1
    assert not reconciled.is_complete_for(
        frozenset(item.dbc_id for item in changed.sender_selection_summaries)
    )



def test_unselected_ecu_input_error_does_not_poison_selected_local_network(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    dbc.write_text(
        dbc.read_text(encoding="utf-8").replace(
            "BO_ 2147484768 Msg460Ext: 16 RemoteBeta",
            "BO_ 2147484768 Msg460Ext: 10 RemoteBeta",
        ),
        encoding="utf-8",
    )
    backend, inspection = _inspect(tmp_path, dbc)
    remote_stats = next(
        item
        for item in inspection.sender_selection_summaries[0].node_stats
        if item.node_name == "RemoteBeta"
    )
    assert "payload length" in remote_stats.note

    updated = backend.apply_sender_selection(inspection, _selection(inspection))

    assert updated.can_optimize
    assert updated.networks[0].available_weight_modes == (WeightMode.PAYLOAD_BYTES,)
    batch = backend.optimize_all_networks(
        _request(updated, tmp_path / "out"), lambda _update: None, CancellationToken()
    )
    assert batch.network_results[0].result is not None
    assert {row.message_name for row in batch.network_results[0].result.assignments} == {
        "Msg391",
        "SharedPeriodic",
    }


def test_multi_node_selection_rejects_mixed_classic_and_fd_before_request(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    text = dbc.read_text(encoding="utf-8")
    text = text.replace(
        "BO_ 700 SharedPeriodic: 8 LocalAlpha",
        "BO_ 700 SharedPeriodic: 8 RemoteBeta",
    ).replace(
        "BO_TX_BU_ 700 : LocalAlpha,AliasGamma;",
        "BO_TX_BU_ 700 : RemoteBeta,AliasGamma;",
    ).replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    )
    dbc.write_text(text, encoding="utf-8")
    backend, inspection = _inspect(tmp_path, dbc)
    config = SenderNodeSelectionConfig(
        selected_transmitters_by_dbc={
            inspection.sender_selection_summaries[0].dbc_id: frozenset(
                {"LocalAlpha", "RemoteBeta"}
            )
        },
        confirmed=True,
        dbc_revision=inspection.dbc_revision,
    )

    updated = backend.apply_sender_selection(inspection, config)

    assert not updated.can_optimize
    assert "混合 Classic CAN 与 CAN FD" in (
        updated.networks[0].unoptimizable_reason or ""
    )
    assert updated.sender_selection_summaries[0].final_eligible_count == 0



def test_dialog_cancel_does_not_change_last_confirmed_selection(
    qtbot, tmp_path: Path
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    backend, inspection = _inspect(tmp_path, dbc)
    confirmed = backend.apply_sender_selection(inspection, _selection(inspection))
    dialog = SenderSelectionDialog(confirmed)
    qtbot.addWidget(dialog)
    remote_row = next(
        row
        for row in range(dialog.node_table.rowCount())
        if dialog.node_table.item(row, 1).text() == "RemoteBeta"
    )
    dialog.node_table.item(remote_row, 0).setCheckState(Qt.CheckState.Checked)
    dialog.reject()

    assert dialog.selection_config is None
    assert confirmed.sender_selection.selected_for(
        confirmed.sender_selection_summaries[0].dbc_id
    ) == frozenset({"LocalAlpha"})



def test_confirmed_flag_without_applied_summaries_does_not_bypass_gate(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    _backend, inspection = _inspect(tmp_path, dbc)
    forged = replace(inspection, sender_selection=_selection(inspection))

    assert not forged.sender_selection_ready
    assert not forged.can_optimize

def test_declared_periodic_message_without_cycle_is_audited_as_input_error(
    tmp_path: Path,
) -> None:
    dbc = _matrix_dbc(tmp_path / "matrix.dbc")
    dbc.write_text(
        dbc.read_text(encoding="utf-8").replace(
            'BA_ "GenMsgCycleTime" BO_ 913 20;\n', ""
        ),
        encoding="utf-8",
    )
    backend, inspection = _inspect(tmp_path, dbc)
    updated = backend.apply_sender_selection(inspection, _selection(inspection))
    record = next(
        item
        for item in updated.sender_selection_summaries[0].messages
        if item.message_name == "Msg391"
    )

    assert record.final_status is MessageEligibilityStatus.INPUT_ERROR
    assert "cycle time" in record.exclusion_reason
    assert not updated.can_optimize