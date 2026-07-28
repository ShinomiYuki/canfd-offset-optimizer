"""! @file project_loader.py
@brief 聚合 DBC、ARXML、YAML 并构造统一 NetworkModel 与时隙预计算。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..config import ProjectConfig, load_project_config
from ..exceptions import ConfigurationError, InputFileError, MissingFieldError
from ..models import CanMessage, ChannelConfig, NetworkModel, ObjectiveMode, WeightMode
from ..timeline.slot_map import SlotMap, build_windows, precompute_slot_map
from ..timing.frame_time import estimate_frame_weight
from .arxml_parser import ArxmlChannelData, parse_arxml_directory
from .dbc_parser import DbcParseResult, ParsedDbcMessage, parse_dbc
from .routing_parser import (
    RouteMessageEntry,
    RouteMessageKey,
    RoutingTable,
    normalize_target_network,
    parse_routing_excel,
)


@dataclass(frozen=True, slots=True)
class RoutingExclusion:
    """一条被正式排除在研究对象之外的目标侧路由报文。"""

    message_name: str
    can_id: int
    is_extended: bool
    route_row_number: int
    routing_message_name: str


@dataclass(frozen=True, slots=True)
class LoadedProject:
    """! @brief CLI 与优化器所需的完整加载结果。"""

    config: ProjectConfig
    network: NetworkModel
    slot_map: SlotMap
    dbc_parse_result: DbcParseResult | None = None
    routing_table: RoutingTable | None = None
    routing_target_network: str | None = None
    routing_exclusions: tuple[RoutingExclusion, ...] = ()
    eligible_start_delay_explicit_count: int = 0
    eligible_start_delay_default_count: int = 0
    eligible_start_delay_unknown_count: int = 0


def _merge_field(
    name: str,
    arxml_value: int | bool | None,
    override: int | bool | None,
    warnings: list[str],
    sources: dict[str, str],
    arxml_sources: dict[str, str],
) -> int | bool | None:
    """! @brief 应用显式 YAML 覆盖并同步记录来源与冲突诊断。"""
    if override is not None:
        if arxml_value is not None and arxml_value != override:
            warnings.append(
                f"YAML overrides ARXML {name}: {arxml_value!r} -> {override!r}"
            )
        else:
            warnings.append(f"YAML explicitly supplies {name}={override!r}")
        sources[name] = "project.yaml override"
        return override
    if arxml_value is not None:
        sources[name] = arxml_sources.get(name, "ARXML")
    return arxml_value


def load_project(
    dbc_path: Path,
    arxml_dir: Path,
    config_path: Path,
    *,
    weight_mode_override: WeightMode | None = None,
    channel_override: str | None = None,
    objective_mode_override: ObjectiveMode | None = None,
    selected_sender: str | None = None,
    routing_excel_path: Path | None = None,
    routing_target_network: str | None = None,
    require_original_offsets: bool = False,
) -> LoadedProject:
    """! @brief 完成外部输入解析、优先级合并、权重和窗口构造。

    @raises MissingFieldError 精确权重模式缺少 bitrate/BRS 且无 YAML 覆盖时抛出。
    """
    if (routing_excel_path is None) != (routing_target_network is None):
        raise ConfigurationError(
            "routing_excel_path and routing_target_network must be provided together"
        )
    config = load_project_config(config_path)
    dbc = parse_dbc(dbc_path, selected_sender=selected_sender)
    warnings = list(dbc.warnings)
    sources: dict[str, str] = {}
    routing_table: RoutingTable | None = None
    canonical_routing_target: str | None = None
    route_exclusions: list[RoutingExclusion] = []
    selected_dbc_messages: tuple[ParsedDbcMessage, ...] = dbc.messages
    if routing_excel_path is not None and routing_target_network is not None:
        routing_table = parse_routing_excel(routing_excel_path)
        canonical_routing_target = normalize_target_network(routing_target_network)
        entries_by_key: dict[RouteMessageKey, RouteMessageEntry] = {}
        for entry in routing_table.entries_for_target(canonical_routing_target):
            entries_by_key.setdefault(entry.key, entry)
        retained: list[ParsedDbcMessage] = []
        for raw in dbc.messages:
            key = RouteMessageKey(
                canonical_routing_target,
                raw.can_id,
                raw.is_extended,
            )
            matched = entries_by_key.get(key)
            if matched is None:
                retained.append(raw)
                continue
            route_exclusions.append(
                RoutingExclusion(
                    raw.name,
                    raw.can_id,
                    raw.is_extended,
                    matched.row_number,
                    matched.message_name,
                )
            )
        selected_dbc_messages = tuple(retained)
        sources["routing_excel"] = str(routing_table.path)
        sources["routing_sheet"] = routing_table.sheet_name
        sources["routing_target_network"] = canonical_routing_target
        warnings.append(
            f"routing exclusion removed {len(route_exclusions)} selected periodic TX "
            f"messages for target {canonical_routing_target}"
        )
    if not selected_dbc_messages:
        raise InputFileError(
            f"{dbc_path}: routing exclusion removed every selected periodic TX message"
        )
    unknown_originals = tuple(
        raw.name for raw in selected_dbc_messages if raw.original_offset_us is None
    )
    if require_original_offsets and unknown_originals:
        names = ", ".join(unknown_originals[:10])
        suffix = " ..." if len(unknown_originals) > 10 else ""
        raise MissingFieldError(
            f"{dbc_path}: {len(unknown_originals)} eligible messages have unknown "
            f"GenMsgStartDelayTime: {names}{suffix}"
        )
    if selected_sender is not None:
        sources["selected_sender"] = selected_sender.strip()
    cli_overrides: dict[str, str] = {}
    restart_policy = config.optimization.restart_policy
    if restart_policy.legacy_additional_restarts is not None:
        warnings.append(
            "optimization.random_restarts is deprecated; normalized "
            f"{restart_policy.legacy_additional_restarts} additional restarts to "
            f"fixed total_attempts={restart_policy.attempt_limit}"
        )
        sources["restart_policy"] = "legacy project.yaml random_restarts adapter"
    else:
        sources["restart_policy"] = (
            "project.yaml optimization.restart_policy"
            if restart_policy.source_kind == "structured"
            else "default adaptive restart policy"
        )
    configured_weight_mode = config.model.weight_mode
    if weight_mode_override is not None:
        cli_overrides["weight_mode"] = weight_mode_override.value
        if weight_mode_override is configured_weight_mode:
            warnings.append(
                f"CLI explicitly selects model.weight_mode={weight_mode_override.value}"
            )
        else:
            warnings.append(
                "CLI overrides project.yaml model.weight_mode: "
                f"{configured_weight_mode.value} -> {weight_mode_override.value}"
            )
            config = replace(
                config,
                model=replace(config.model, weight_mode=weight_mode_override),
            )
    if channel_override is not None:
        selected_channel = channel_override.strip()
        if not selected_channel:
            raise ConfigurationError("CLI --channel must not be empty")
        cli_overrides["channel"] = selected_channel
        if selected_channel == config.network.channel:
            warnings.append(
                f"CLI --channel explicitly selects network.channel={selected_channel!r}"
            )
        else:
            warnings.append(
                "CLI overrides project.yaml network.channel: "
                f"{config.network.channel!r} -> {selected_channel!r}"
            )
        config = replace(
            config,
            network=replace(config.network, channel=selected_channel),
        )
    if objective_mode_override is not None:
        cli_overrides["objective_mode"] = objective_mode_override.value
        configured_objective_mode = config.objective.mode
        if objective_mode_override is configured_objective_mode:
            warnings.append(
                f"CLI explicitly selects objective.mode={objective_mode_override.value}"
            )
        else:
            warnings.append(
                "CLI overrides project.yaml objective.mode: "
                f"{configured_objective_mode.value} -> {objective_mode_override.value}"
            )
        config = replace(
            config,
            objective=replace(config.objective, mode=objective_mode_override),
        )
    if (
        config.model.weight_mode is not WeightMode.FRAME_TIME_US
        and config.objective.mode is not ObjectiveMode.PEAK
    ):
        warnings.append(
            f"objective.mode={config.objective.mode.value} requires frame_time_us; "
            "approximate weight mode was forced to peak"
        )
        config = replace(
            config,
            objective=replace(config.objective, mode=ObjectiveMode.PEAK),
        )
    channel_name = config.network.channel
    if not channel_name:
        raise ConfigurationError("network.channel must be specified to select an ARXML channel")
    sources["channel"] = (
        "CLI --channel override"
        if channel_override is not None
        else "project.yaml network.channel selection"
    )
    sources["weight_mode"] = (
        "CLI --weight-mode override"
        if weight_mode_override is not None
        else "project.yaml model.weight_mode"
    )
    sources["objective_mode"] = (
        "forced peak for approximate weight mode"
        if config.model.weight_mode is not WeightMode.FRAME_TIME_US
        else (
            "CLI --objective-mode override"
            if objective_mode_override is not None
            else "project.yaml objective.mode"
        )
    )
    arxml: ArxmlChannelData | None = None
    if not arxml_dir.is_dir():
        raise InputFileError(f"ARXML directory does not exist: {arxml_dir}")
    arxml_files = tuple(
        sorted(path for path in arxml_dir.rglob("*") if path.suffix.lower() == ".arxml")
    )
    if arxml_files:
        try:
            arxml = parse_arxml_directory(arxml_dir, channel_name)
        except MissingFieldError as exc:
            override_brs = config.network.brs
            overrides_sufficient = (
                config.model.weight_mode is not WeightMode.FRAME_TIME_US
                or (
                    config.network.nominal_bitrate is not None
                    and override_brs is not None
                    and (not override_brs or config.network.data_bitrate is not None)
                )
            )
            if not overrides_sufficient:
                raise
            warnings.append(
                f"ARXML channel {channel_name!r} was unusable ({exc}); "
                "explicit YAML/model settings were used"
            )
    arxml_sources = dict(arxml.field_sources) if arxml else {}
    nominal_value = _merge_field(
        "nominal_bitrate",
        arxml.nominal_bitrate if arxml else None,
        config.network.nominal_bitrate,
        warnings,
        sources,
        arxml_sources,
    )
    data_value = _merge_field(
        "data_bitrate",
        arxml.data_bitrate if arxml else None,
        config.network.data_bitrate,
        warnings,
        sources,
        arxml_sources,
    )
    brs_value = _merge_field(
        "brs",
        arxml.brs if arxml else None,
        config.network.brs,
        warnings,
        sources,
        arxml_sources,
    )
    exact_fields_missing = config.model.weight_mode is WeightMode.FRAME_TIME_US and (
        nominal_value is None
        or brs_value is None
        or (brs_value is True and data_value is None)
    )
    if exact_fields_missing:
        missing = []
        if nominal_value is None:
            missing.append("nominal_bitrate")
        if brs_value is not False and data_value is None:
            missing.append("data_bitrate")
        if brs_value is None:
            missing.append("brs")
        raise MissingFieldError(
            f"channel {channel_name!r} lacks {', '.join(missing)}; provide ARXML or YAML overrides"
        )
    channel = ChannelConfig(
        channel_name,
        int(nominal_value) if nominal_value is not None else None,
        int(data_value) if data_value is not None else None,
        bool(brs_value) if brs_value is not None else None,
    )
    messages: list[CanMessage] = []
    approximation_warning: str | None = None
    for raw in selected_dbc_messages:
        try:
            estimate = estimate_frame_weight(
                raw.payload_bytes, raw.is_extended, channel, config.model.weight_mode
            )
        except ValueError as exc:
            raise MissingFieldError(
                f"{dbc_path}: message {raw.name} cannot be weighted: {exc}"
            ) from exc
        approximation_warning = estimate.warning or approximation_warning
        messages.append(
            CanMessage(
                name=raw.name,
                can_id=raw.can_id,
                is_extended=raw.is_extended,
                cycle_time_us=raw.cycle_time_us,
                frame_time_us=estimate.frame_time_us,
                allowed_offsets_us=config.optimization.allowed_offsets_us,
                original_offset_us=raw.original_offset_us,
                sender_ecu=raw.sender_ecu,
                definition_index=raw.definition_index,
                payload_bytes=raw.payload_bytes,
            )
        )
        if raw.original_offset_us is None:
            warnings.append(
                f"message {raw.name} has no original Offset; baseline uses "
                f"{min(config.optimization.allowed_offsets_us)} us"
            )
        elif raw.original_offset_us not in config.optimization.allowed_offsets_us:
            warnings.append(
                f"message {raw.name} original Offset {raw.original_offset_us} us is not "
                f"legal; baseline uses {min(config.optimization.allowed_offsets_us)} us"
            )
        for field_key, value in raw.field_sources:
            sources[f"message.{raw.name}.{field_key}"] = value
    if approximation_warning:
        warnings.append(approximation_warning)
    try:
        startup, steady, hyperperiod = build_windows(
            tuple(messages),
            config.optimization.slot_width_us,
            config.optimization.hyperperiod_us,
            config.optimization.hyperperiod_cap_us,
        )
    except ValueError as exc:
        raise ConfigurationError(f"invalid optimization timeline: {exc}") from exc
    input_files = (
        dbc_path,
        config_path,
        *arxml_files,
        *((routing_excel_path,) if routing_excel_path is not None else ()),
    )
    network = NetworkModel(
        messages=tuple(messages),
        channel=channel,
        hyperperiod_us=hyperperiod,
        startup_window=startup,
        steady_window=steady,
        weight_mode=config.model.weight_mode,
        warnings=tuple(warnings),
        field_sources=tuple(sorted(sources.items())),
        input_files=tuple(input_files),
        cli_overrides=tuple(sorted(cli_overrides.items())),
    )
    if (
        network.weight_mode is WeightMode.FRAME_TIME_US
        and network.average_load > config.model.average_load_limit
    ):
        network = NetworkModel(
            messages=network.messages,
            channel=network.channel,
            hyperperiod_us=network.hyperperiod_us,
            startup_window=network.startup_window,
            steady_window=network.steady_window,
            weight_mode=network.weight_mode,
            warnings=network.warnings
            + (
                "average load exceeds configured limit and cannot be repaired by Offset optimization",
            ),
            field_sources=network.field_sources,
            input_files=network.input_files,
            cli_overrides=network.cli_overrides,
        )
    return LoadedProject(
        config=config,
        network=network,
        slot_map=precompute_slot_map(network.messages, startup, steady),
        dbc_parse_result=dbc,
        routing_table=routing_table,
        routing_target_network=canonical_routing_target,
        routing_exclusions=tuple(route_exclusions),
        eligible_start_delay_explicit_count=sum(
            raw.start_delay_source == "explicit" for raw in selected_dbc_messages
        ),
        eligible_start_delay_default_count=sum(
            raw.start_delay_source == "default" for raw in selected_dbc_messages
        ),
        eligible_start_delay_unknown_count=sum(
            raw.start_delay_source == "unknown" for raw in selected_dbc_messages
        ),
    )
