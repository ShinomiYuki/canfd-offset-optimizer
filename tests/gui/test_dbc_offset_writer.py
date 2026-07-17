from __future__ import annotations

from pathlib import Path

import pytest

from canfd_offset_optimizer.gui.dbc_offset_writer import (
    DbcOffsetReplacement,
    write_dbc_with_offsets,
)


def test_writer_changes_only_existing_offset_numeric_tokens_in_a_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        b'VERSION "keep exactly"\r\n'
        b'BO_ 100 MsgA: 8 VCU\r\n'
        b'BO_ 2147483939 MsgExt: 8 VCU\r\n'
        b'BA_ "GenMsgCycleTime" BO_ 100 20; // untouched\r\n'
        b'BA_ "GenMsgStartDelayTime" BO_ 100 15; // offset A\r\n'
        b'BA_ "GenMsgDelayTime" BO_ 100 5; // not the start Offset\r\n'
        b'BA_ "GenMsgStartDelayTime" BO_ 2147483939 20;\r\n'
    )
    source.write_bytes(original)
    output = tmp_path / "run" / "dbc" / "copy.dbc"

    written = write_dbc_with_offsets(
        source,
        output,
        (
            DbcOffsetReplacement("MsgA", 100, False, 35_000),
            DbcOffsetReplacement("MsgExt", 0x123, True, 100_000),
        ),
    )

    expected = original.replace(
        b'"GenMsgStartDelayTime" BO_ 100 15;',
        b'"GenMsgStartDelayTime" BO_ 100 35;',
    ).replace(
        b'"GenMsgStartDelayTime" BO_ 2147483939 20;',
        b'"GenMsgStartDelayTime" BO_ 2147483939 100;',
    )
    assert written == output.resolve()
    assert source.read_bytes() == original
    assert output.read_bytes() == expected


def test_writer_fails_closed_when_original_offset_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BO_ 100 MsgA: 8 VCU\n')
    output = tmp_path / "dbc" / "copy.dbc"

    with pytest.raises(ValueError, match="各有且仅有一个原 Offset"):
        write_dbc_with_offsets(
            source,
            output,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )

    assert not output.exists()
    assert source.read_bytes() == b'BO_ 100 MsgA: 8 VCU\n'


def test_writer_refuses_to_overwrite_the_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n')
    with pytest.raises(ValueError, match="must be a copy"):
        write_dbc_with_offsets(
            source,
            source,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )
