"""! @file config.py
@brief project.yaml 的强类型读取、默认值和范围校验。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from .exceptions import ConfigurationError
from .models import WeightMode


@dataclass(frozen=True, slots=True)
class NetworkOverrides:
    """! @brief YAML 对 ARXML 通道字段的显式覆盖。"""

    channel: str | None = None
    nominal_bitrate: int | None = None
    data_bitrate: int | None = None
    brs: bool | None = None

    def __post_init__(self) -> None:
        if self.channel is not None and not self.channel.strip():
            raise ConfigurationError("network.channel must be non-empty when provided")
        for name, value in (
            ("nominal_bitrate", self.nominal_bitrate),
            ("data_bitrate", self.data_bitrate),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ConfigurationError(f"network.{name} must be a positive integer")
        if self.brs is not None and not isinstance(self.brs, bool):
            raise ConfigurationError("network.brs must be boolean or null")

@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    """! @brief GCLS、窗口及候选 Offset 配置。"""

    slot_width_us: int = 5_000
    hyperperiod_us: int | None = None
    hyperperiod_cap_us: int = 5_000_000
    offset_min_us: int = 15_000
    offset_max_us: int = 100_000
    offset_step_us: int = 5_000
    random_restarts: int = 20
    hot_slot_count: int = 3
    conflict_candidate_cap: int = 6
    pair_neighbor_steps: tuple[int, ...] = (1, 2, 3)

    def __post_init__(self) -> None:
        integer_fields = (
            self.slot_width_us,
            self.hyperperiod_cap_us,
            self.offset_min_us,
            self.offset_max_us,
            self.offset_step_us,
            self.random_restarts,
            self.hot_slot_count,
            self.conflict_candidate_cap,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in integer_fields
        ):
            raise ConfigurationError("optimization integer fields must be integers")
        positive = (
            self.slot_width_us,
            self.hyperperiod_cap_us,
            self.offset_step_us,
            self.hot_slot_count,
            self.conflict_candidate_cap,
        )
        if any(value <= 0 for value in positive):
            raise ConfigurationError("slot/cap/step/count values must be positive")
        if self.offset_min_us < 0 or self.offset_max_us < self.offset_min_us:
            raise ConfigurationError("offset range is invalid")
        if self.offset_max_us == 0:
            raise ConfigurationError("offset_max_us must be positive for startup analysis")
        if (self.offset_max_us - self.offset_min_us) % self.offset_step_us:
            raise ConfigurationError("offset range must be divisible by offset step")
        if (
            self.offset_min_us % self.slot_width_us
            or self.offset_max_us % self.slot_width_us
            or self.offset_step_us % self.slot_width_us
        ):
            raise ConfigurationError("offset range and step must align to slot_width_us")
        if self.random_restarts < 0:
            raise ConfigurationError("random_restarts must be non-negative")
        if not self.pair_neighbor_steps or any(
            isinstance(step, bool) or not isinstance(step, int) or step <= 0
            for step in self.pair_neighbor_steps
        ):
            raise ConfigurationError("pair_neighbor_steps must contain positive integers")
        if tuple(sorted(set(self.pair_neighbor_steps))) != self.pair_neighbor_steps:
            raise ConfigurationError("pair_neighbor_steps must be unique and increasing")
        if self.hyperperiod_us is not None and (
            isinstance(self.hyperperiod_us, bool)
            or not isinstance(self.hyperperiod_us, int)
            or self.hyperperiod_us <= 0
        ):
            raise ConfigurationError("explicit hyperperiod must be a positive integer")

    @property
    def allowed_offsets_us(self) -> tuple[int, ...]:
        """! @brief 生成闭区间内严格递增的合法 Offset。"""
        return tuple(
            range(self.offset_min_us, self.offset_max_us + 1, self.offset_step_us)
        )


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """! @brief 权重模式与平均负载诊断阈值。"""

    weight_mode: WeightMode = WeightMode.FRAME_TIME_US
    average_load_limit: float = 0.75

    def __post_init__(self) -> None:
        if not isinstance(self.weight_mode, WeightMode):
            raise ConfigurationError("weight_mode must be a WeightMode")
        if isinstance(self.average_load_limit, bool) or not isinstance(
            self.average_load_limit, (int, float)
        ):
            raise ConfigurationError("average_load_limit must be numeric")
        if not 0 < self.average_load_limit <= 1:
            raise ConfigurationError("average_load_limit must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """! @brief 完整项目配置。"""

    network: NetworkOverrides = field(default_factory=NetworkOverrides)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    model: ModelConfig = field(default_factory=ModelConfig)


def _mapping(value: object, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{context} keys must be strings")
    return cast(dict[str, Any], value)


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ConfigurationError(f"unknown {context} fields: {sorted(unknown)}")


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer or null")
    return value


def _ms(mapping: dict[str, Any], key: str, default_ms: int) -> int:
    value = mapping.get(key, default_ms)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"optimization.{key} must be an integer")
    return value * 1_000


def load_project_config(path: Path) -> ProjectConfig:
    """! @brief 读取并校验 project.yaml。

    @param path YAML 文件路径。
    @return 已完成单位归一化的不可变配置。
    @raises ConfigurationError 文件结构或字段类型、范围无效时抛出。
    """
    try:
        raw_value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot read configuration {path}: {exc}") from exc
    raw = _mapping(raw_value, "configuration root")
    unknown = set(raw) - {"network", "optimization", "model"}
    if unknown:
        raise ConfigurationError(f"unknown top-level fields: {sorted(unknown)}")

    network_raw = _mapping(raw.get("network"), "network")
    optimization_raw = _mapping(raw.get("optimization"), "optimization")
    model_raw = _mapping(raw.get("model"), "model")
    _reject_unknown(
        network_raw,
        {"channel", "nominal_bitrate", "data_bitrate", "brs"},
        "network",
    )
    _reject_unknown(
        optimization_raw,
        {
            "slot_ms",
            "hyperperiod_ms",
            "hyperperiod_cap_ms",
            "offset_min_ms",
            "offset_max_ms",
            "offset_step_ms",
            "random_restarts",
            "hot_slot_count",
            "conflict_candidate_cap",
            "pair_neighbor_steps",
        },
        "optimization",
    )
    _reject_unknown(model_raw, {"weight_mode", "average_load_limit"}, "model")

    brs = network_raw.get("brs")
    if brs is not None and not isinstance(brs, bool):
        raise ConfigurationError("network.brs must be boolean or null")
    channel = network_raw.get("channel")
    if channel is not None and (not isinstance(channel, str) or not channel.strip()):
        raise ConfigurationError("network.channel must be a non-empty string or null")
    network = NetworkOverrides(
        channel=channel.strip() if isinstance(channel, str) else None,
        nominal_bitrate=_optional_int(network_raw, "nominal_bitrate"),
        data_bitrate=_optional_int(network_raw, "data_bitrate"),
        brs=brs,
    )
    hyperperiod_value = optimization_raw.get("hyperperiod_ms", "auto")
    if hyperperiod_value == "auto":
        hyperperiod_us = None
    elif isinstance(hyperperiod_value, int) and not isinstance(hyperperiod_value, bool):
        hyperperiod_us = hyperperiod_value * 1_000
    else:
        raise ConfigurationError("optimization.hyperperiod_ms must be 'auto' or integer")
    steps = optimization_raw.get("pair_neighbor_steps", [1, 2, 3])
    if not isinstance(steps, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in steps
    ):
        raise ConfigurationError("optimization.pair_neighbor_steps must be a list of integers")
    optimization = OptimizationConfig(
        slot_width_us=_ms(optimization_raw, "slot_ms", 5),
        hyperperiod_us=hyperperiod_us,
        hyperperiod_cap_us=_ms(optimization_raw, "hyperperiod_cap_ms", 5_000),
        offset_min_us=_ms(optimization_raw, "offset_min_ms", 15),
        offset_max_us=_ms(optimization_raw, "offset_max_ms", 100),
        offset_step_us=_ms(optimization_raw, "offset_step_ms", 5),
        random_restarts=_required_int(optimization_raw, "random_restarts", 20),
        hot_slot_count=_required_int(optimization_raw, "hot_slot_count", 3),
        conflict_candidate_cap=_required_int(
            optimization_raw, "conflict_candidate_cap", 6
        ),
        pair_neighbor_steps=tuple(steps),
    )
    mode_value = model_raw.get("weight_mode", WeightMode.FRAME_TIME_US.value)
    try:
        mode = WeightMode(mode_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"unsupported model.weight_mode: {mode_value!r}") from exc
    limit = model_raw.get("average_load_limit", 0.75)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        raise ConfigurationError("model.average_load_limit must be numeric")
    return ProjectConfig(network, optimization, ModelConfig(mode, float(limit)))


def _required_int(mapping: dict[str, Any], key: str, default: int) -> int:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"optimization.{key} must be an integer")
    return value
