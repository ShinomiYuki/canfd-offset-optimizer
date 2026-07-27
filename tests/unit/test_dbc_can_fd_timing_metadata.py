from __future__ import annotations

from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import InputFileError
from canfd_offset_optimizer.parsers.dbc_parser import (
    parse_dbc,
    read_dbc_data_bitrate,
)


FIXTURE = Path("tests/fixtures/dbc/minimal.dbc")


def _timed_dbc() -> str:
    return (
        FIXTURE.read_text(encoding="utf-8")
        + '\nBA_DEF_ BO_ "CANFD_BRS" ENUM "0","1";'
        + '\nBA_DEF_DEF_ "CANFD_BRS" "1";'
        + '\nBA_ "CANFD_BRS" BO_ 913 0;'
        + '\nBA_DEF_ "DataBitrate" INT 1 10000000;'
        + '\nBA_ "DataBitrate" 2000000;\n'
    )


def test_per_message_brs_prefers_explicit_then_dbc_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "timed.dbc"
    path.write_text(_timed_dbc(), encoding="utf-8")

    parsed = parse_dbc(path)
    by_name = {message.name: message for message in parsed.messages}

    assert by_name["Msg391"].dbc_brs is False
    assert by_name["Msg391"].dbc_brs_source == "DBC:CANFD_BRS"
    assert by_name["Msg460Ext"].dbc_brs is True
    assert (
        by_name["Msg460Ext"].dbc_brs_source
        == "DBC:CANFD_BRS:BA_DEF_DEF_"
    )


def test_explicit_global_data_bitrate_is_auditable(tmp_path: Path) -> None:
    path = tmp_path / "timed.dbc"
    path.write_text(_timed_dbc(), encoding="utf-8")

    value, source = read_dbc_data_bitrate(path)
    parsed = parse_dbc(path)

    assert (value, source) == (2_000_000, "DBC:DataBitrate")
    assert parsed.data_bitrate_bps == 2_000_000
    assert parsed.data_bitrate_source == "DBC:DataBitrate"


def test_missing_data_rate_and_brs_are_not_guessed(tmp_path: Path) -> None:
    path = tmp_path / "plain.dbc"
    path.write_bytes(FIXTURE.read_bytes())

    parsed = parse_dbc(path)

    assert parsed.data_bitrate_bps is None
    assert parsed.data_bitrate_source is None
    assert all(message.dbc_brs is None for message in parsed.messages)


def test_conflicting_data_rate_aliases_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "conflict.dbc"
    path.write_text(
        _timed_dbc() + '\nBA_ "CANFD_DataBitrate" 5000000;\n',
        encoding="utf-8",
    )

    with pytest.raises(InputFileError, match="conflicting"):
        read_dbc_data_bitrate(path)
