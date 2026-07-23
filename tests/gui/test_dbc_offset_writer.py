from __future__ import annotations

from pathlib import Path

import pytest

import canfd_offset_optimizer.gui.dbc_offset_writer as writer_module
from canfd_offset_optimizer.gui.dbc_offset_writer import (
    DbcOffsetReplacement,
    inspect_dbc_offset_write,
    write_dbc_with_offsets,
)
from canfd_offset_optimizer.parsers.dbc_parser import parse_dbc


START_DEFINITION = b'BA_DEF_ BO_ "GenMsgStartDelayTime" INT 0 65535;\n'
DBC_FIXTURE = Path(__file__).parents[1] / "fixtures" / "dbc" / "minimal.dbc"


def test_writer_patches_only_start_delay_and_preserves_delay_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        b'VERSION "keep exactly"\r\n'
        b'BA_DEF_ BO_ "GenMsgStartDelayTime" INT 0 65535;\r\n'
        b'BO_ 100 MsgA: 8 VCU\r\n'
        b'BO_ 2147483939 MsgExt: 8 VCU\r\n'
        b'BA_ "GenMsgCycleTime" BO_ 100 20; // untouched\r\n'
        b'BA_ "GenMsgStartDelayTime" BO_ 100 15; // offset A\r\n'
        b'BA_ "GenMsgDelayTime" BO_ 100 5; // independent timing\r\n'
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
    assert b'"GenMsgDelayTime" BO_ 100 5; // independent timing' in expected
    assert not tuple(output.parent.glob(".dbc-*.tmp"))


def test_writer_updates_all_equal_duplicates_and_audits_warning(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        START_DEFINITION
        + b'BA_ "GenMsgStartDelayTime" BO_ 100 15; // first\n'
        + b'BA_ "GenMsgDelayTime" BO_ 100 5;\n'
        + b'BA_ "GenMsgStartDelayTime" BO_ 100 15.0; // second\n'
        + b'BA_ "GenMsgStartDelayTime" BO_ 100 +15; // third\n'
    )
    source.write_bytes(original)
    replacements = (DbcOffsetReplacement("MsgA", 100, False, 35_000),)

    plan = inspect_dbc_offset_write(source, replacements)
    output = write_dbc_with_offsets(
        source, tmp_path / "dbc" / "copy.dbc", replacements
    )

    assert plan.attribute_name == "GenMsgStartDelayTime"
    assert plan.replaced_count == plan.message_count == 1
    assert plan.inserted_count == 0
    assert plan.warning_count == 1
    assert plan.untouched_delay_count == 1
    assert output.read_bytes().count(b'"GenMsgStartDelayTime" BO_ 100 35;') == 3
    assert b'"GenMsgDelayTime" BO_ 100 5;' in output.read_bytes()


def test_writer_rejects_conflicting_duplicate_start_delay_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        START_DEFINITION
        + b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n'
        + b'BA_ "GenMsgStartDelayTime" BO_ 100 20;\n'
    )
    source.write_bytes(original)
    output = tmp_path / "dbc" / "copy.dbc"
    replacements = (DbcOffsetReplacement("MsgA", 100, False, 35_000),)

    with pytest.raises(ValueError, match="冲突的 GenMsgStartDelayTime"):
        inspect_dbc_offset_write(source, replacements)
    with pytest.raises(ValueError, match="冲突的 GenMsgStartDelayTime"):
        write_dbc_with_offsets(source, output, replacements)

    assert source.read_bytes() == original
    assert not output.exists()


def test_writer_fails_closed_without_start_delay_bo_definition(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        b'BA_DEF_ BO_ "GenMsgDelayTime" INT 0 65535;\n'
        b'BA_ "GenMsgDelayTime" BO_ 100 5;\n'
        b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n'
    )
    source.write_bytes(original)
    output = tmp_path / "dbc" / "copy.dbc"

    with pytest.raises(ValueError, match="缺少 GenMsgStartDelayTime.*BO_ 属性定义"):
        write_dbc_with_offsets(
            source,
            output,
            (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
        )

    assert source.read_bytes() == original
    assert not output.exists()


def test_writer_inserts_missing_start_delays_before_first_val(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        b'VERSION "keep"\r\n'
        b'BA_DEF_ BO_ "GenMsgStartDelayTime" INT 0 65535;\r\n'
        b'BA_DEF_DEF_ "GenMsgStartDelayTime" 0;\r\n'
        b'BA_ "GenMsgCycleTime" BO_ 100 20; // existing BA order\r\n'
        b'VAL_ 100 State 0 "off" 1 "on";\r\n'
        b'VAL_ 101 State 0 "off";\r\n'
    )
    source.write_bytes(original)
    replacements = (
        DbcOffsetReplacement("MsgA", 100, False, 35_000),
        DbcOffsetReplacement("MsgB", 101, False, 40_000),
    )

    plan = inspect_dbc_offset_write(source, replacements)
    output = write_dbc_with_offsets(
        source, tmp_path / "dbc" / "copy.dbc", replacements
    )
    updated = output.read_bytes()

    assert plan.attribute_name == "GenMsgStartDelayTime"
    assert plan.replaced_count == 0
    assert plan.inserted_count == plan.message_count == 2
    first_val = updated.index(b"VAL_ 100")
    assert updated.index(b'"GenMsgStartDelayTime" BO_ 100 35;') < first_val
    assert updated.index(b'"GenMsgStartDelayTime" BO_ 101 40;') < first_val
    assert updated[updated.index(b"VAL_ 100") :] == original[original.index(b"VAL_ 100") :]
    assert not updated.rstrip().endswith(b'"GenMsgStartDelayTime" BO_ 101 40;')
    assert b'BA_ "GenMsgDelayTime"' not in updated


def test_writer_uses_exact_ids_and_keeps_existing_line_position(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        START_DEFINITION
        + b'BA_ "GenMsgStartDelayTime" BO_ 560 10;\n'
        + b'BA_ "GenMsgStartDelayTime" BO_ 56 15; // target\n'
        + b'BA_ "GenMsgStartDelayTime" BO_ 156 20;\n'
        + b'VAL_ 56 X 0 "x";\n'
    )
    source.write_bytes(original)
    output = write_dbc_with_offsets(
        source,
        tmp_path / "copy.dbc",
        (DbcOffsetReplacement("Exact", 56, False, 45_000),),
    )
    updated = output.read_bytes()

    assert b"BO_ 560 10;" in updated
    assert b"BO_ 156 20;" in updated
    assert updated.index(b"BO_ 56 45;") == original.index(b"BO_ 56 15;")


def test_writer_without_val_inserts_after_existing_attribute_block(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = (
        START_DEFINITION
        + b'BA_DEF_DEF_ "GenMsgStartDelayTime" 0;\n'
        + b'BA_ "GenMsgCycleTime" BO_ 100 20;\n'
        + b'CM_ "tail stays after BA block";\n'
    )
    source.write_bytes(original)
    output = write_dbc_with_offsets(
        source,
        tmp_path / "copy.dbc",
        (DbcOffsetReplacement("MsgA", 100, False, 35_000),),
    )
    updated = output.read_bytes()

    assert updated.index(b'"GenMsgCycleTime"') < updated.index(
        b'"GenMsgStartDelayTime" BO_ 100 35;'
    )
    assert updated.index(b'"GenMsgStartDelayTime" BO_ 100 35;') < updated.index(
        b'CM_ "tail'
    )


def test_written_copy_round_trips_optimized_start_delay_before_val(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dbc"
    original = DBC_FIXTURE.read_bytes()
    marker = b'VAL_ 913 State 0 "off" 1 "on";\n'
    source.write_bytes(original + marker)
    output = write_dbc_with_offsets(
        source,
        tmp_path / "copy.dbc",
        (
            DbcOffsetReplacement("Msg391", 0x391, False, 35_000),
            DbcOffsetReplacement("Msg460Ext", 0x460, True, 40_000),
        ),
    )

    parsed = {message.name: message for message in parse_dbc(output).messages}
    assert parsed["Msg391"].original_offset_us == 35_000
    assert parsed["Msg391"].original_offset_source == "explicit"
    assert parsed["Msg460Ext"].original_offset_us == 40_000
    inserted = output.read_bytes().index(
        b'BA_ "GenMsgStartDelayTime" BO_ 2147484768 40;'
    )
    assert inserted < output.read_bytes().index(b"VAL_ 913")


def test_writer_refuses_to_overwrite_the_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source.dbc"
    source.write_bytes(
        START_DEFINITION + b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n'
    )
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
    source.write_bytes(
        START_DEFINITION + b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n'
    )
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
    source.write_bytes(
        START_DEFINITION + b'BA_ "GenMsgStartDelayTime" BO_ 100 15;\n'
    )
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
