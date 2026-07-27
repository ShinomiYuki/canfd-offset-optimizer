from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import InputFileError
from canfd_offset_optimizer.parsers.dbc_parser import (
    parse_dbc,
    read_dbc_nominal_bitrate,
)


FIXTURE = Path("tests/fixtures/dbc/minimal.dbc")


def _with_baudrate(value: int) -> str:
    return (
        FIXTURE.read_text(encoding="utf-8")
        + '\nBA_DEF_ "Baudrate" INT 1 10000000;'
        + f'\nBA_ "Baudrate" {value};\n'
    )


def test_explicit_global_dbc_baudrate_is_read_as_bits_per_second(tmp_path: Path) -> None:
    path = tmp_path / "timed.dbc"
    path.write_text(_with_baudrate(500_000), encoding="utf-8")
    assert read_dbc_nominal_bitrate(path) == 500_000


def test_blank_dbc_bs_does_not_guess_500k(tmp_path: Path) -> None:
    path = tmp_path / "blank.dbc"
    path.write_bytes(FIXTURE.read_bytes())
    assert read_dbc_nominal_bitrate(path) is None


def test_conflicting_explicit_baudrate_values_are_not_silently_selected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conflict.dbc"
    path.write_text(
        _with_baudrate(500_000) + '\nBA_ "Baudrate" 250000;\n',
        encoding="utf-8",
    )
    with pytest.raises(InputFileError, match="conflicting"):
        read_dbc_nominal_bitrate(path)


def test_parse_result_exposes_reliable_dbc_bitrate_and_source(tmp_path: Path) -> None:
    path = tmp_path / "timed-matrix.dbc"
    path.write_text(_with_baudrate(500_000), encoding="utf-8")

    parsed = parse_dbc(path)

    assert parsed.nominal_bitrate_bps == 500_000
    assert parsed.nominal_bitrate_source == "DBC:Baudrate"
