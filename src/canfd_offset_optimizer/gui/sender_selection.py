"""Formal DBC transmitter selection inventory, preview and reconciliation service."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import hashlib
import importlib
from pathlib import Path
from typing import Any

from ..exceptions import CanfdOptimizerError
from ..models import FrameProtocol as CoreFrameProtocol
from ..parsers.dbc_parser import (
    message_cycle_time_us,
    message_frame_protocol,
    message_is_declared_periodic,
    parse_loaded_dbc,
    transmitter_nodes,
)
from .contracts import (
    DbcSenderSelectionSummary,
    FrameProtocol,
    MessageEligibilityRecord,
    MessageEligibilityStatus,
    SenderNodeSelectionConfig,
    SenderNodeStats,
    SenderSelectionDbcStatus,
)


def dbc_identity(relative_path: Path, sha256: str) -> str:
    material = f"{relative_path.as_posix()}|{sha256}"
    return f"dbc-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def dbc_revision(summaries: tuple[DbcSenderSelectionSummary, ...]) -> str:
    material = "\n".join(
        f"{item.dbc_id}|{item.sha256}"
        for item in sorted(summaries, key=lambda value: value.dbc_id)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()



def _message_key(message: Any) -> tuple[int, bool, str]:
    return (
        int(getattr(message, "frame_id")),
        bool(getattr(message, "is_extended_frame", False)),
        str(getattr(message, "name")),
    )


def build_sender_inventory(
    *,
    dbc_id: str,
    dbc_file: str,
    network_id: str,
    network_name: str,
    source_workspace_path: Path,
    sha256: str,
    dbc_path: Path,
    allowed_offsets_us: tuple[int, ...],
    routing_excluded_can_ids: frozenset[int] = frozenset(),
) -> DbcSenderSelectionSummary:
    """Inspect every DBC message while reusing core parse eligibility as truth."""

    cantools = importlib.import_module("cantools")
    try:
        database = cantools.database.load_file(str(dbc_path), strict=False)
    except Exception as exc:  # cantools exposes format failures through several types.
        return DbcSenderSelectionSummary(
            dbc_id=dbc_id,
            dbc_file=dbc_file,
            network_id=network_id,
            network_name=network_name,
            source_workspace_path=source_workspace_path,
            sha256=sha256,
            node_stats=(),
            messages=(),
            status=SenderSelectionDbcStatus.INPUT_ERROR,
            note=f"{type(exc).__name__}: {exc}",
        )
    concrete_nodes = tuple(
        sorted(
            {
                sender
                for raw in database.messages
                for sender in transmitter_nodes(raw)
            }
        )
    )
    eligible: dict[tuple[int, bool, str], object] = {}
    node_errors: dict[str, str] = {}
    for node_name in concrete_nodes:
        try:
            parsed = parse_loaded_dbc(
                database,
                dbc_path,
                allowed_offsets_us=allowed_offsets_us,
                selected_transmitters=frozenset({node_name}),
            )
        except CanfdOptimizerError as exc:
            node_errors[node_name] = f"{type(exc).__name__}: {exc}"
            continue
        eligible.update(
            {
                (message.can_id, message.is_extended, message.name): message
                for message in parsed.messages
            }
        )
    parse_error = "；".join(
        f"{name}: {error}" for name, error in sorted(node_errors.items())
    )

    records: list[MessageEligibilityRecord] = []
    node_messages: dict[str, list[MessageEligibilityRecord]] = defaultdict(list)
    for raw in database.messages:
        key = _message_key(raw)
        senders = transmitter_nodes(raw)
        cycle_time_us = message_cycle_time_us(raw)
        parsed_message = eligible.get(key)
        raw_protocol = message_frame_protocol(raw)
        protocol = (
            FrameProtocol.CLASSIC_CAN
            if raw_protocol is CoreFrameProtocol.CLASSIC_CAN
            else FrameProtocol.CAN_FD
        )
        base_eligible = parsed_message is not None
        if not senders:
            record_status = MessageEligibilityStatus.NO_VALID_TRANSMITTER
            reason = "DBC 未提供可识别的具体发送节点（Vector__XXX/空节点按未知处理）"
        elif cycle_time_us is None and message_is_declared_periodic(raw):
            record_status = MessageEligibilityStatus.INPUT_ERROR
            reason = (
                "；".join(node_errors[sender] for sender in senders if sender in node_errors)
                or "报文声明为周期发送，但没有有效正周期"
            )
        elif cycle_time_us is None:
            record_status = MessageEligibilityStatus.NON_PERIODIC
            reason = "报文没有有效正周期"
        elif senders and all(sender in node_errors for sender in senders):
            record_status = MessageEligibilityStatus.INPUT_ERROR
            reason = "；".join(node_errors[sender] for sender in senders)
        elif not base_eligible:
            record_status = MessageEligibilityStatus.UNSUPPORTED_SEND_TYPE
            reason = "未满足核心现有基础资格条件"
        else:
            record_status = MessageEligibilityStatus.BASE_ELIGIBLE
            reason = "等待用户选择本机发送节点"
        record = MessageEligibilityRecord(
            dbc_id=dbc_id,
            dbc_file=dbc_file,
            network_id=network_id,
            network_name=network_name,
            can_id=key[0],
            is_extended=key[1],
            message_name=key[2],
            transmitter_nodes=senders,
            selected_transmitter_match=False,
            cycle_time_us=cycle_time_us,
            frame_protocol=protocol,
            base_eligible=base_eligible,
            routing_match=key[0] in routing_excluded_can_ids,
            final_status=record_status,
            exclusion_reason=reason,
        )
        records.append(record)
        for sender in senders:
            node_messages[sender].append(record)

    stats_list = [
        SenderNodeStats(
            node_name=name,
            message_count=len(node_records),
            valid_periodic_count=sum(item.cycle_time_us is not None for item in node_records),
            classic_can_count=sum(
                item.frame_protocol is FrameProtocol.CLASSIC_CAN for item in node_records
            ),
            can_fd_count=sum(
                item.frame_protocol is FrameProtocol.CAN_FD for item in node_records
            ),
            base_candidate_count=sum(item.base_eligible for item in node_records),
            note=node_errors.get(name, ""),
        )
        for name, node_records in sorted(node_messages.items(), key=lambda item: item[0])
    ]
    unknown_records = [record for record in records if not record.transmitter_nodes]
    if unknown_records:
        stats_list.append(
            SenderNodeStats(
                node_name="Vector__XXX / 空节点（不可选择）",
                message_count=len(unknown_records),
                valid_periodic_count=sum(
                    item.cycle_time_us is not None for item in unknown_records
                ),
                classic_can_count=sum(
                    item.frame_protocol is FrameProtocol.CLASSIC_CAN
                    for item in unknown_records
                ),
                can_fd_count=sum(
                    item.frame_protocol is FrameProtocol.CAN_FD
                    for item in unknown_records
                ),
                base_candidate_count=0,
                note="未知/占位发送节点，不能作为本机节点选择",
                selectable=False,
            )
        )
    stats = tuple(stats_list)
    summary_status = (
        SenderSelectionDbcStatus.NO_IDENTIFIABLE_TRANSMITTER
        if not any(item.selectable for item in stats)
        else (
            SenderSelectionDbcStatus.INPUT_ERROR
            if concrete_nodes and len(node_errors) == len(concrete_nodes)
            else SenderSelectionDbcStatus.UNPROCESSED
        )
    )
    return DbcSenderSelectionSummary(
        dbc_id=dbc_id,
        dbc_file=dbc_file,
        network_id=network_id,
        network_name=network_name,
        source_workspace_path=source_workspace_path,
        sha256=sha256,
        node_stats=stats,
        messages=tuple(records),
        status=summary_status,
        note=parse_error,
    )


def apply_selection_to_summary(
    summary: DbcSenderSelectionSummary,
    config: SenderNodeSelectionConfig,
) -> DbcSenderSelectionSummary:
    selected = config.selected_for(summary.dbc_id)
    excluded = summary.dbc_id in config.excluded_dbc_ids
    selected_protocols = {
        record.frame_protocol
        for record in summary.messages
        if record.base_eligible
        and selected.intersection(record.transmitter_nodes)
        and record.frame_protocol is not None
    }
    mixed_protocols = len(selected_protocols) > 1
    messages: list[MessageEligibilityRecord] = []
    for record in summary.messages:
        matched = bool(selected.intersection(record.transmitter_nodes))
        if excluded:
            record_status = MessageEligibilityStatus.EXCLUDED_BY_USER
            reason = "用户明确排除该 DBC"
        elif not record.transmitter_nodes:
            record_status = MessageEligibilityStatus.NO_VALID_TRANSMITTER
            reason = "DBC 未提供可识别的具体发送节点"
        elif not matched:
            record_status = MessageEligibilityStatus.EXCLUDED_UNSELECTED_TRANSMITTER
            reason = "报文发送节点未命中用户选择的本机节点"
        elif mixed_protocols and record.base_eligible:
            record_status = MessageEligibilityStatus.INPUT_ERROR
            reason = (
                "所选本机节点的基础合资格报文混合 Classic CAN 与 CAN FD，"
                "同一物理网段不能混合权重单位"
            )
        elif not record.base_eligible:
            record_status = record.final_status
            reason = record.exclusion_reason
        elif record.routing_match:
            record_status = MessageEligibilityStatus.ROUTING_EXCLUDED
            reason = "命中路由表目标网段 + CAN ID"
        else:
            record_status = MessageEligibilityStatus.FINAL_ELIGIBLE
            reason = "参与优化"
        messages.append(
            replace(
                record,
                selected_transmitter_match=matched,
                final_status=record_status,
                exclusion_reason=reason,
            )
        )
    selected_input_error = any(
        record.selected_transmitter_match
        and record.final_status is MessageEligibilityStatus.INPUT_ERROR
        for record in messages
    )
    summary_status = (
        SenderSelectionDbcStatus.EXCLUDED_BY_USER
        if excluded
        else (
            SenderSelectionDbcStatus.INPUT_ERROR
            if selected_input_error
            else (
                SenderSelectionDbcStatus.SELECTED
                if selected
                else summary.status
            )
        )
    )
    return replace(
        summary,
        messages=tuple(messages),
        status=summary_status,
        selected_transmitters=tuple(sorted(selected)),
        excluded_by_user=excluded,
    )


def validate_complete_selection(
    summaries: tuple[DbcSenderSelectionSummary, ...],
    config: SenderNodeSelectionConfig,
) -> None:
    dbc_ids = frozenset(item.dbc_id for item in summaries)
    unknown = frozenset(config.selected_transmitters_by_dbc).union(
        config.excluded_dbc_ids
    ).difference(dbc_ids)
    if unknown:
        raise ValueError("发送节点选择包含不属于当前工程的 DBC")
    unprocessed = dbc_ids.difference(config.selected_transmitters_by_dbc).difference(
        config.excluded_dbc_ids
    )
    if unprocessed:
        raise ValueError(
            f"仍有 {len(unprocessed)} 个 DBC 未选择本机发送节点或明确排除。"
        )
    inventories = {item.dbc_id: item for item in summaries}
    for dbc_id, selected in config.selected_transmitters_by_dbc.items():
        available = {
            item.node_name
            for item in inventories[dbc_id].node_stats
            if item.selectable
        }
        if not selected.issubset(available):
            raise ValueError("发送节点选择包含当前 DBC 中不存在的节点")


def reconcile_selection(
    previous: SenderNodeSelectionConfig | None,
    summaries: tuple[DbcSenderSelectionSummary, ...],
) -> SenderNodeSelectionConfig:
    revision = dbc_revision(summaries)
    if previous is None:
        return SenderNodeSelectionConfig(dbc_revision=revision)
    ids = frozenset(item.dbc_id for item in summaries)
    selected = {
        dbc_id: names
        for dbc_id, names in previous.selected_transmitters_by_dbc.items()
        if dbc_id in ids
    }
    excluded = previous.excluded_dbc_ids.intersection(ids)
    complete = frozenset(selected).union(excluded) == ids
    return SenderNodeSelectionConfig(
        selected_transmitters_by_dbc=selected,
        excluded_dbc_ids=excluded,
        confirmed=previous.confirmed and complete,
        dbc_revision=revision,
    )
