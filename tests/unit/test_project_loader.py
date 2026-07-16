"""! @file test_project_loader.py
@brief 多输入合并、窗口与 YAML 覆盖诊断测试。

@author 篠見由紀
"""

from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import InputFileError, MissingFieldError
from canfd_offset_optimizer.parsers.project_loader import load_project


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_loader_constructs_four_message_network() -> None:
    loaded = load_project(
        FIXTURES / "dbc" / "four_messages.dbc",
        FIXTURES / "arxml",
        FIXTURES / "config" / "project.yaml",
    )
    assert len(loaded.network.messages) == 4
    assert loaded.network.hyperperiod_us == 500_000
    assert loaded.network.steady_window.slot_count == 100
    assert loaded.network.channel.nominal_bitrate == 500_000
    assert all(message.frame_time_us > 0 for message in loaded.network.messages)


def test_channel_override_is_applied_and_audited(tmp_path: Path) -> None:
    config = tmp_path / "wrong-channel.yaml"
    config.write_text(
        (FIXTURES / "config" / "project.yaml")
        .read_text(encoding="utf-8")
        .replace("channel: CAN1", "channel: WRONG"),
        encoding="utf-8",
    )
    loaded = load_project(
        FIXTURES / "dbc" / "four_messages.dbc",
        FIXTURES / "arxml",
        config,
        channel_override="CAN1",
    )
    assert loaded.config.network.channel == "CAN1"
    assert dict(loaded.network.field_sources)["channel"] == "CLI --channel override"
    assert any("CLI overrides" in warning for warning in loaded.network.warnings)


def test_yaml_override_is_used_and_reported(tmp_path: Path) -> None:
    config = tmp_path / "override.yaml"
    config.write_text(
        "network:\n  channel: CAN1\n  nominal_bitrate: 1000000\n"
        "  data_bitrate: null\n  brs: null\noptimization:\n  hyperperiod_ms: 500\n",
        encoding="utf-8",
    )
    loaded = load_project(
        FIXTURES / "dbc" / "four_messages.dbc", FIXTURES / "arxml", config
    )
    assert loaded.network.channel.nominal_bitrate == 1_000_000
    assert any("overrides ARXML nominal_bitrate" in item for item in loaded.network.warnings)


def test_exact_weight_mode_never_guesses_missing_network_fields(tmp_path: Path) -> None:
    empty_arxml = tmp_path / "arxml"
    empty_arxml.mkdir()
    with pytest.raises(MissingFieldError, match="nominal_bitrate.*data_bitrate.*brs"):
        load_project(
            FIXTURES / "dbc" / "four_messages.dbc",
            empty_arxml,
            FIXTURES / "config" / "project.yaml",
        )


def test_brs_false_override_does_not_require_data_bitrate(tmp_path: Path) -> None:
    empty_arxml = tmp_path / "arxml"
    empty_arxml.mkdir()
    config = tmp_path / "no_brs.yaml"
    config.write_text(
        "network:\n  channel: CAN1\n  nominal_bitrate: 500000\n"
        "  data_bitrate: null\n  brs: false\n"
        "optimization:\n  hyperperiod_ms: 500\n"
        "model:\n  weight_mode: frame_time_us\n",
        encoding="utf-8",
    )
    loaded = load_project(
        FIXTURES / "dbc" / "four_messages.dbc", empty_arxml, config
    )
    assert loaded.network.channel.data_bitrate is None
    assert all(message.frame_time_us > 0 for message in loaded.network.messages)


def test_missing_arxml_path_is_never_treated_as_an_empty_directory(
    tmp_path: Path,
) -> None:
    config = tmp_path / "complete_overrides.yaml"
    config.write_text(
        "network:\n  channel: CAN1\n  nominal_bitrate: 500000\n"
        "  data_bitrate: 2000000\n  brs: true\n"
        "optimization:\n  hyperperiod_ms: 500\n",
        encoding="utf-8",
    )
    with pytest.raises(InputFileError, match="ARXML directory does not exist"):
        load_project(
            FIXTURES / "dbc" / "four_messages.dbc",
            tmp_path / "misspelled-arxml",
            config,
        )
