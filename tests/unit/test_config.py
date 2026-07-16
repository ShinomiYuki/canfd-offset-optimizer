"""! @file test_config.py
@brief YAML 配置解析、默认候选集合和范围校验测试。

@author 篠見由紀
"""

from pathlib import Path

import pytest

from canfd_offset_optimizer.config import (
    ModelConfig,
    NetworkOverrides,
    OptimizationConfig,
    load_project_config,
)
from canfd_offset_optimizer.exceptions import ConfigurationError


def test_default_offsets_are_15_to_100_ms() -> None:
    offsets = OptimizationConfig().allowed_offsets_us
    assert offsets == tuple(range(15_000, 100_001, 5_000))


def test_load_project_config_normalizes_milliseconds(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(
        "optimization:\n  slot_ms: 5\n  offset_min_ms: 15\n  offset_max_ms: 25\n"
        "  offset_step_ms: 5\nmodel:\n  weight_mode: unit\n",
        encoding="utf-8",
    )
    config = load_project_config(path)
    assert config.optimization.allowed_offsets_us == (15_000, 20_000, 25_000)
    assert config.model.weight_mode.value == "unit"


def test_config_rejects_invalid_range_and_unknown_fields(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="range"):
        OptimizationConfig(offset_min_us=20_000, offset_max_us=15_000)
    path = tmp_path / "bad.yaml"
    path.write_text("surprise: true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown"):
        load_project_config(path)
    path.write_text("network:\n  channel: CAN1\n  mystery: 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown network"):
        load_project_config(path)


def test_direct_config_objects_reject_bool_and_invalid_runtime_types() -> None:
    with pytest.raises(ConfigurationError, match="integer"):
        OptimizationConfig(slot_width_us=True)
    with pytest.raises(ConfigurationError, match="positive integer"):
        NetworkOverrides(nominal_bitrate=-1)
    with pytest.raises(ConfigurationError, match="WeightMode"):
        ModelConfig(weight_mode="unit")  # type intentionally invalid at runtime


@pytest.mark.parametrize("bitrate", [0, -500_000])
def test_yaml_bitrate_must_be_positive(tmp_path: Path, bitrate: int) -> None:
    path = tmp_path / "invalid_bitrate.yaml"
    path.write_text(
        f"network:\n  channel: CAN1\n  nominal_bitrate: {bitrate}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="nominal_bitrate.*positive"):
        load_project_config(path)
