from __future__ import annotations

from pathlib import Path

import pytest

import canfd_offset_optimizer.gui.dbc_offset_writer as writer_module

from canfd_offset_optimizer.gui.dbc_offset_writer import (
    DbcOffsetReplacement,
    inspect_dbc_offset_write,
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
    assert not tuple(output.parent.glob(".dbc-*.tmp"))


def test_writer_fails_closed_when_offset_schema_is_undeclared(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BO_ 100 MsgA: 8 VCU\n')
    output = tmp_path / "dbc" / "copy.dbc"

    with pytest.raises(ValueError, match="缺少显式原 Offset"):
        write_dbc_with_offsets(
            source,
            output,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )

    assert not output.exists()
    assert source.read_bytes() == b'BO_ 100 MsgA: 8 VCU\n'


def test_writer_materializes_inherited_default_in_output_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    original = (
        b'VERSION "keep"\r\n'
        b'BO_ 100 MsgA: 8 VCU\r\n'
        b'BO_ 101 MsgB: 8 VCU\r\n'
        b'BA_DEF_ BO_ "GenMsgDelayTime" INT 0 10000;\r\n'
        b'BA_DEF_DEF_ "GenMsgDelayTime" 0;\r\n'
        b'BA_ "GenMsgDelayTime" BO_ 100 15; // replace only number\r\n'
    )
    source.write_bytes(original)
    output = tmp_path / "dbc" / "copy.dbc"
    replacements = (
        DbcOffsetReplacement("MsgA", 100, False, 35_000),
        DbcOffsetReplacement("MsgB", 101, False, 40_000),
    )

    plan = inspect_dbc_offset_write(source, replacements)
    written = write_dbc_with_offsets(source, output, replacements)

    assert plan.attribute_name == "GenMsgDelayTime"
    assert plan.replaced_count == 1
    assert plan.inserted_count == 1
    assert source.read_bytes() == original
    assert written.read_bytes() == original.replace(
        b'"GenMsgDelayTime" BO_ 100 15;',
        b'"GenMsgDelayTime" BO_ 100 35;',
    ) + b'BA_ "GenMsgDelayTime" BO_ 101 40;\r\n'


def test_writer_refuses_to_overwrite_the_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n')
    with pytest.raises(ValueError, match="must be a copy"):
        write_dbc_with_offsets(
            source,
            source,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )


def test_writer_rejects_final_path_over_safety_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n')
    output = tmp_path / "dbc" / "unchanged-name.dbc"
    monkeypatch.setattr(writer_module, "windows_utf16_path_length", lambda _path: 241)

    with pytest.raises(ValueError, match=r"241 > 240"):
        write_dbc_with_offsets(
            source,
            output,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )

    assert not output.exists()


def test_writer_removes_short_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n')
    output = tmp_path / "dbc" / "unchanged-name.dbc"
    original_replace = Path.replace

    def fail_temporary_replace(path: Path, target: Path) -> Path:
        if path.name.startswith(".dbc-"):
            raise OSError("injected replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_temporary_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        write_dbc_with_offsets(
            source,
            output,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )

    assert not output.exists()
    assert not tuple(output.parent.glob(".dbc-*.tmp"))
