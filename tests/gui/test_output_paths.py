from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from canfd_offset_optimizer.gui.output_paths import (
    BATCH_TIMESTAMP_FORMAT,
    create_timestamped_batch_directory,
    dbc_output_destination,
    short_output_stem,
    windows_utf16_path_length,
)


def test_batch_directory_contains_only_timestamp_and_resolves_collision(
    tmp_path: Path,
) -> None:
    fixed = datetime(2026, 7, 21, 9, 16, 32, 301590)
    first_name = fixed.strftime(BATCH_TIMESTAMP_FORMAT)
    (tmp_path / first_name).mkdir()

    created = create_timestamped_batch_directory(tmp_path, clock=lambda: fixed)

    assert created.name == "20260721_091632_301591"
    assert re.fullmatch(r"\d{8}_\d{6}_\d{6}", created.name)
    assert "real" not in created.name.casefold()


def test_short_output_stem_keeps_short_names_and_hashes_long_names() -> None:
    assert short_output_stem("SU") == "SU"
    first = short_output_stem("A" * 100)
    second = short_output_stem("A" * 100)
    assert first == second
    assert len(first) == 48
    assert re.fullmatch(r"A{39}_[0-9a-f]{8}", first)


def test_windows_path_length_counts_utf16_code_units(tmp_path: Path) -> None:
    path = tmp_path / "横置" / "result.dbc"
    expected = len(str(path.resolve(strict=False)).encode("utf-16-le")) // 2
    assert windows_utf16_path_length(path) == expected


def test_dbc_name_is_unchanged_when_collision_uses_short_subdirectory(
    tmp_path: Path,
) -> None:
    dbc_directory = tmp_path / "dbc"
    dbc_directory.mkdir()
    source_name = "long original source name.dbc"
    (dbc_directory / source_name).write_text("first", encoding="utf-8")

    destination = dbc_output_destination(
        dbc_directory,
        source_name,
        "SU",
        "net-ff981da4de58bceb",
    )

    assert destination.name == source_name
    assert destination.parent.name == "SU_de58bceb"


def test_company_installation_example_has_safe_margin_with_timestamp_batch() -> None:
    source_name = (
        "E0X_OT_Car FLZCU_PDCS_SU Message list V4.50 "
        "Draft_202510301403_REEV(横置)&PHEV&ICE.dbc"
    )
    destination = (
        Path(r"D:\yuan.zhou\CANFDOffsetOptimizer-0.1.0-win-x64")
        / "user_output"
        / "20260721_091632_301590"
        / "dbc"
        / source_name
    )

    assert destination.name == source_name
    assert windows_utf16_path_length(destination) < 240
