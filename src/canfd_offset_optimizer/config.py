"""! @file config.py
@brief project.yaml 的强类型读取、默认值和范围校验。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, cast

import yaml

from .exceptions import ConfigurationError
from .models import ObjectiveMode, PeakToleranceType, RestartMode, WeightMode


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    """! @brief 以总尝试次数表达的 fixed/adaptive 重启策略。"""

    mode: RestartMode = RestartMode.ADAPTIVE
    total_attempts: int | None = None
    min_attempts: int = 20
    check_interval: int = 10
    patience_attempts: int = 20
    max_attempts: int = 80
    source_kind: str = "default"
    legacy_additional_restarts: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RestartMode):
            raise ConfigurationError("restart_policy.mode must be a RestartMode")
        if self.source_kind not in {"default", "structured", "legacy", "cli"}:
            raise ConfigurationError("restart_policy.source_kind is invalid")
        if self.legacy_additional_restarts is not None and (
            self.source_kind != "legacy"
            or self.mode is not RestartMode.FIXED
            or self.total_attempts != self.legacy_additional_restarts + 1
        ):
            raise ConfigurationError("legacy restart metadata is inconsistent")
        values = (
            self.min_attempts,
            self.check_interval,
            self.patience_attempts,
            self.max_attempts,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ConfigurationError("adaptive restart fields must be integers")
        if any(value <= 0 for value in values):
            raise ConfigurationError("adaptive restart fields must be positive")
        if self.mode is RestartMode.FIXED:
            if (
                isinstance(self.total_attempts, bool)
                or not isinstance(self.total_attempts, int)
                or self.total_attempts <= 0
            ):
                raise ConfigurationError(
                    "fixed restart_policy.total_attempts must be a positive integer"
                )
        elif self.total_attempts is not None:
            raise ConfigurationError(
                "adaptive restart_policy must not define total_attempts"
            )
        if self.min_attempts > self.max_attempts:
            raise ConfigurationError(
                "restart_policy.min_attempts must not exceed max_attempts"
            )
        if self.patience_attempts > self.max_attempts:
            raise ConfigurationError(
                "restart_policy.patience_attempts must not exceed max_attempts"
            )

    @classmethod
    def fixed(
        cls,
        total_attempts: int,
        *,
        source_kind: str = "default",
        legacy_additional_restarts: int | None = None,
    ) -> RestartPolicy:
        """Construct a fixed policy using total-attempt semantics."""
        return cls(
            mode=RestartMode.FIXED,
            total_attempts=total_attempts,
            source_kind=source_kind,
            legacy_additional_restarts=legacy_additional_restarts,
        )

    @property
    def attempt_limit(self) -> int:
        """Return the fixed total or adaptive hard upper bound."""
        if self.mode is RestartMode.FIXED:
            assert self.total_attempts is not None
            return self.total_attempts
        return self.max_attempts


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
    restart_policy: RestartPolicy = field(default_factory=RestartPolicy)
    hot_slot_count: int = 3
    conflict_candidate_cap: int = 6
    pair_neighbor_steps: tuple[int, ...] = (1, 2, 3)
    variance_offset_cap: int = 3
    peak_candidate_pool_size: int = 1
    conflict_triple_enabled: bool = False
    triple_candidate_cap: int = 6
    triple_hot_slot_count: int = 3
    triple_max_rounds: int = 3
    random_restarts: InitVar[int | None] = None

    def __post_init__(self, random_restarts: int | None) -> None:
        if not isinstance(self.conflict_triple_enabled, bool):
            raise ConfigurationError(
                "optimization.conflict_triple_enabled must be boolean"
            )
        if (
            isinstance(self.triple_candidate_cap, bool)
            or not isinstance(self.triple_candidate_cap, int)
            or not 6 <= self.triple_candidate_cap <= 8
        ):
            raise ConfigurationError(
                "optimization.triple_candidate_cap must be an integer in [6, 8]"
            )
        if random_restarts is not None:
            if isinstance(random_restarts, bool) or not isinstance(
                random_restarts, int
            ):
                raise ConfigurationError("random_restarts must be an integer")
            if random_restarts < 0:
                raise ConfigurationError("random_restarts must be non-negative")
            if self.restart_policy != RestartPolicy():
                raise ConfigurationError(
                    "random_restarts conflicts with restart_policy"
                )
            object.__setattr__(
                self,
                "restart_policy",
                RestartPolicy.fixed(
                    random_restarts + 1,
                    source_kind="legacy",
                    legacy_additional_restarts=random_restarts,
                ),
            )
        if (
            isinstance(self.peak_candidate_pool_size, bool)
            or not isinstance(self.peak_candidate_pool_size, int)
            or self.peak_candidate_pool_size not in {1, 4, 8, 16, 32}
        ):
            raise ConfigurationError(
                "optimization.peak_candidate_pool_size must be one of 1, 4, 8, 16, 32"
            )
        integer_fields = (
            self.slot_width_us,
            self.hyperperiod_cap_us,
            self.offset_min_us,
            self.offset_max_us,
            self.offset_step_us,
            self.hot_slot_count,
            self.conflict_candidate_cap,
            self.variance_offset_cap,
            self.triple_candidate_cap,
            self.triple_hot_slot_count,
            self.triple_max_rounds,
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
            self.variance_offset_cap,
            self.triple_hot_slot_count,
            self.triple_max_rounds,
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
class PeakToleranceConfig:
    """! @brief balanced 峰值预算相对或绝对宽容量。"""

    type: PeakToleranceType = PeakToleranceType.RELATIVE
    value: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.type, PeakToleranceType):
            raise ConfigurationError("peak_tolerance.type is invalid")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ConfigurationError("peak_tolerance.value must be numeric")
        if not isfinite(self.value):
            raise ConfigurationError("peak_tolerance.value must be finite")
        if self.value < 0:
            raise ConfigurationError("peak_tolerance.value must be non-negative")
        if self.type is PeakToleranceType.RELATIVE and self.value > 1:
            raise ConfigurationError("relative peak_tolerance.value must be at most 1")
        if self.type is PeakToleranceType.ABSOLUTE and not float(self.value).is_integer():
            raise ConfigurationError("absolute peak_tolerance.value must be integer microseconds")


@dataclass(frozen=True, slots=True)
class ObjectiveConfig:
    """! @brief 固定目标模式、峰值预算宽容和方差指标。"""

    mode: ObjectiveMode = ObjectiveMode.BALANCED
    peak_tolerance: PeakToleranceConfig = field(default_factory=PeakToleranceConfig)
    variance_metric: str = "sum_of_squares"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ObjectiveMode):
            raise ConfigurationError("objective.mode must be an ObjectiveMode")
        if self.variance_metric != "sum_of_squares":
            raise ConfigurationError("objective.variance_metric must be 'sum_of_squares'")


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """! @brief 完整项目配置。"""

    network: NetworkOverrides = field(default_factory=NetworkOverrides)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    objective: ObjectiveConfig = field(default_factory=ObjectiveConfig)


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
    unknown = set(raw) - {"network", "optimization", "model", "objective"}
    if unknown:
        raise ConfigurationError(f"unknown top-level fields: {sorted(unknown)}")

    network_raw = _mapping(raw.get("network"), "network")
    optimization_raw = _mapping(raw.get("optimization"), "optimization")
    model_raw = _mapping(raw.get("model"), "model")
    objective_raw = _mapping(raw.get("objective"), "objective")
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
            "restart_policy",
            "hot_slot_count",
            "conflict_candidate_cap",
            "pair_neighbor_steps",
            "variance_offset_cap",
            "peak_candidate_pool_size",
            "conflict_triple_enabled",
            "triple_candidate_cap",
            "triple_hot_slot_count",
            "triple_max_rounds",
        },
        "optimization",
    )
    _reject_unknown(model_raw, {"weight_mode", "average_load_limit"}, "model")
    _reject_unknown(
        objective_raw, {"mode", "peak_tolerance", "variance_metric"}, "objective"
    )

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
    legacy_restarts = optimization_raw.get("random_restarts")
    restart_raw_value = optimization_raw.get("restart_policy")
    if legacy_restarts is not None and restart_raw_value is not None:
        raise ConfigurationError(
            "optimization.random_restarts conflicts with restart_policy"
        )
    if legacy_restarts is not None:
        if isinstance(legacy_restarts, bool) or not isinstance(legacy_restarts, int):
            raise ConfigurationError("optimization.random_restarts must be an integer")
        if legacy_restarts < 0:
            raise ConfigurationError(
                "optimization.random_restarts must be non-negative"
            )
        restart_policy = RestartPolicy.fixed(
            legacy_restarts + 1,
            source_kind="legacy",
            legacy_additional_restarts=legacy_restarts,
        )
    else:
        restart_raw = _mapping(restart_raw_value, "optimization.restart_policy")
        restart_mode_value = restart_raw.get("mode", RestartMode.ADAPTIVE.value)
        try:
            restart_mode = RestartMode(restart_mode_value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"unsupported restart_policy.mode: {restart_mode_value!r}"
            ) from exc
        if restart_mode is RestartMode.FIXED:
            _reject_unknown(
                restart_raw,
                {"mode", "total_attempts"},
                "optimization.restart_policy",
            )
            if "total_attempts" not in restart_raw:
                raise ConfigurationError(
                    "fixed restart_policy requires total_attempts"
                )
            restart_policy = RestartPolicy.fixed(
                _required_int(restart_raw, "total_attempts", 21),
                source_kind="structured",
            )
        else:
            _reject_unknown(
                restart_raw,
                {
                    "mode",
                    "min_attempts",
                    "check_interval",
                    "patience_attempts",
                    "max_attempts",
                },
                "optimization.restart_policy",
            )
            restart_policy = RestartPolicy(
                mode=RestartMode.ADAPTIVE,
                min_attempts=_required_int(restart_raw, "min_attempts", 20),
                check_interval=_required_int(restart_raw, "check_interval", 10),
                patience_attempts=_required_int(
                    restart_raw, "patience_attempts", 20
                ),
                max_attempts=_required_int(restart_raw, "max_attempts", 80),
                source_kind=(
                    "structured" if restart_raw_value is not None else "default"
                ),
            )
    optimization = OptimizationConfig(
        slot_width_us=_ms(optimization_raw, "slot_ms", 5),
        hyperperiod_us=hyperperiod_us,
        hyperperiod_cap_us=_ms(optimization_raw, "hyperperiod_cap_ms", 5_000),
        offset_min_us=_ms(optimization_raw, "offset_min_ms", 15),
        offset_max_us=_ms(optimization_raw, "offset_max_ms", 100),
        offset_step_us=_ms(optimization_raw, "offset_step_ms", 5),
        restart_policy=restart_policy,
        hot_slot_count=_required_int(optimization_raw, "hot_slot_count", 3),
        conflict_candidate_cap=_required_int(
            optimization_raw, "conflict_candidate_cap", 6
        ),
        pair_neighbor_steps=tuple(steps),
        variance_offset_cap=_required_int(optimization_raw, "variance_offset_cap", 3),
        peak_candidate_pool_size=_required_int(
            optimization_raw, "peak_candidate_pool_size", 1
        ),
        conflict_triple_enabled=optimization_raw.get(
            "conflict_triple_enabled", False
        ),
        triple_candidate_cap=_required_int(
            optimization_raw, "triple_candidate_cap", 6
        ),
        triple_hot_slot_count=_required_int(
            optimization_raw, "triple_hot_slot_count", 3
        ),
        triple_max_rounds=_required_int(
            optimization_raw, "triple_max_rounds", 3
        ),
    )
    mode_value = model_raw.get("weight_mode", WeightMode.FRAME_TIME_US.value)
    try:
        mode = WeightMode(mode_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"unsupported model.weight_mode: {mode_value!r}") from exc
    limit = model_raw.get("average_load_limit", 0.75)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        raise ConfigurationError("model.average_load_limit must be numeric")
    objective_mode_value = objective_raw.get("mode", ObjectiveMode.BALANCED.value)
    try:
        objective_mode = ObjectiveMode(objective_mode_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"unsupported objective.mode: {objective_mode_value!r}"
        ) from exc
    tolerance_raw = _mapping(
        objective_raw.get("peak_tolerance"), "objective.peak_tolerance"
    )
    _reject_unknown(tolerance_raw, {"type", "value"}, "objective.peak_tolerance")
    tolerance_type_value = tolerance_raw.get(
        "type", PeakToleranceType.RELATIVE.value
    )
    try:
        tolerance_type = PeakToleranceType(tolerance_type_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"unsupported peak_tolerance.type: {tolerance_type_value!r}"
        ) from exc
    tolerance_value = tolerance_raw.get("value", 0.05)
    if isinstance(tolerance_value, bool) or not isinstance(
        tolerance_value, (int, float)
    ):
        raise ConfigurationError("objective.peak_tolerance.value must be numeric")
    objective = ObjectiveConfig(
        mode=objective_mode,
        peak_tolerance=PeakToleranceConfig(tolerance_type, float(tolerance_value)),
        variance_metric=objective_raw.get("variance_metric", "sum_of_squares"),
    )
    return ProjectConfig(network, optimization, ModelConfig(mode, float(limit)), objective)


def _required_int(mapping: dict[str, Any], key: str, default: int) -> int:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"optimization.{key} must be an integer")
    return value
