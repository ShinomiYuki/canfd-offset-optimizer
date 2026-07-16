"""! @file project_loader.py
@brief 聚合 DBC、ARXML、YAML 并构造统一 NetworkModel 与时隙预计算。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ProjectConfig, load_project_config
from ..exceptions import ConfigurationError, InputFileError, MissingFieldError
from ..models import CanMessage, ChannelConfig, NetworkModel, WeightMode
from ..timeline.slot_map import SlotMap, build_windows, precompute_slot_map
from ..timing.frame_time import estimate_frame_weight
from .arxml_parser import ArxmlChannelData, parse_arxml_directory
from .dbc_parser import parse_dbc


@dataclass(frozen=True, slots=True)
class LoadedProject:
    """! @brief CLI 与优化器所需的完整加载结果。"""

    config: ProjectConfig
    network: NetworkModel
    slot_map: SlotMap


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


def load_project(dbc_path: Path, arxml_dir: Path, config_path: Path) -> LoadedProject:
    """! @brief 完成外部输入解析、优先级合并、权重和窗口构造。

    @raises MissingFieldError 精确权重模式缺少 bitrate/BRS 且无 YAML 覆盖时抛出。
    """
    config = load_project_config(config_path)
    dbc = parse_dbc(dbc_path)
    warnings = list(dbc.warnings)
    sources: dict[str, str] = {}
    channel_name = config.network.channel
    if not channel_name:
        raise ConfigurationError("network.channel must be specified to select an ARXML channel")
    sources["channel"] = "project.yaml network.channel selection"
    sources["weight_mode"] = "project.yaml model.weight_mode"
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
    for raw in dbc.messages:
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
        if (
            raw.original_offset_us is not None
            and raw.original_offset_us not in config.optimization.allowed_offsets_us
        ):
            warnings.append(
                f"message {raw.name} original Offset {raw.original_offset_us} us is not "
                f"legal; baseline uses {min(config.optimization.allowed_offsets_us)} us"
            )
        for key, value in raw.field_sources:
            sources[f"message.{raw.name}.{key}"] = value
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
    input_files = (dbc_path, config_path, *arxml_files)
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
        )
    return LoadedProject(config, network, precompute_slot_map(network.messages, startup, steady))
