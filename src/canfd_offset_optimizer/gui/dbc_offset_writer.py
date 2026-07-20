"""Byte-preserving writer for optimized Offset attributes in DBC copies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


# Mirrors dbc_parser.DBC_ATTRIBUTES["start_delay"] precedence without importing
# the core-private parser into this GUI-only byte writer.
_OFFSET_ATTRIBUTES = (
    b"GenMsgStartDelayTime",
    b"GenMsgDelayTime",
    b"MsgStartDelayTime",
)
_OFFSET_ATTRIBUTE = rb"(?:" + rb"|".join(_OFFSET_ATTRIBUTES) + rb")"
_OFFSET_LINE = re.compile(
    rb"(?m)^(?P<prefix>[ \t]*BA_[ \t]+\"(?P<attribute>" + _OFFSET_ATTRIBUTE
    + rb")\"[ \t]+BO_[ \t]+(?P<frame_id>[0-9]+)[ \t]+)"
    rb"(?P<value>[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))"
    rb"(?P<suffix>[ \t]*;[^\r\n]*)(?P<carriage_return>\r?)$"
)
_OFFSET_DEFINITION = re.compile(
    rb'(?m)^[ \t]*BA_DEF_[ \t]+BO_[ \t]+"(?P<attribute>'
    + _OFFSET_ATTRIBUTE
    + rb')"[ \t]+'
)
_OFFSET_DEFAULT = re.compile(
    rb'(?m)^[ \t]*BA_DEF_DEF_[ \t]+"(?P<attribute>'
    + _OFFSET_ATTRIBUTE
    + rb')"[ \t]+'
)


@dataclass(frozen=True, slots=True)
class DbcOffsetReplacement:
    message_name: str
    can_id: int
    is_extended: bool
    offset_us: int

    @property
    def raw_dbc_id(self) -> int:
        return self.can_id | (0x80000000 if self.is_extended else 0)


@dataclass(frozen=True, slots=True)
class DbcOffsetWritePlan:
    """Auditable description of byte-level Offset materialization."""

    attribute_name: str
    replaced_count: int
    inserted_count: int


@dataclass(frozen=True, slots=True)
class _PreparedWrite:
    original: bytes
    selected: tuple[tuple[re.Match[bytes], DbcOffsetReplacement], ...]
    missing: tuple[DbcOffsetReplacement, ...]
    insertion_attribute: bytes
    plan: DbcOffsetWritePlan


def _prepare_write(
    source: Path, replacements: tuple[DbcOffsetReplacement, ...]
) -> _PreparedWrite:
    if not replacements:
        raise ValueError("DBC Offset replacement set must not be empty")
    by_raw_id = {item.raw_dbc_id: item for item in replacements}
    if len(by_raw_id) != len(replacements):
        raise ValueError("DBC Offset replacements contain duplicate frame IDs")
    if any(item.offset_us < 0 or item.offset_us % 1_000 for item in replacements):
        raise ValueError("DBC Offset values must be non-negative whole milliseconds")

    original = source.read_bytes()
    all_matches = tuple(_OFFSET_LINE.finditer(original))
    matches_by_id: dict[int, list[re.Match[bytes]]] = {}
    for match in all_matches:
        frame_id = int(match.group("frame_id"))
        if frame_id in by_raw_id:
            matches_by_id.setdefault(frame_id, []).append(match)

    selected_by_id: dict[int, re.Match[bytes]] = {}
    missing: list[DbcOffsetReplacement] = []
    invalid: list[str] = []
    for frame_id, item in by_raw_id.items():
        candidates = matches_by_id.get(frame_id, ())
        preferred: list[re.Match[bytes]] = []
        for attribute in _OFFSET_ATTRIBUTES:
            preferred = [
                match for match in candidates if match.group("attribute") == attribute
            ]
            if preferred:
                break
        if len(preferred) > 1:
            invalid.append(item.message_name)
        elif preferred:
            selected_by_id[frame_id] = preferred[0]
        else:
            missing.append(item)
    if invalid:
        raise ValueError(
            "DBC 中参与优化的报文存在重复的原 Offset 属性：" + ", ".join(invalid)
        )

    declared = {
        match.group("attribute") for match in _OFFSET_DEFINITION.finditer(original)
    }
    defaulted = {
        match.group("attribute") for match in _OFFSET_DEFAULT.finditer(original)
    }
    insertion_attribute = b""
    if missing:
        if not defaulted:
            raise ValueError(
                "DBC 中参与优化的报文缺少显式原 Offset，且 DBC 未提供 Offset 默认值："
                + ", ".join(item.message_name for item in missing)
            )
        insertion_candidates = [
            attribute for attribute in _OFFSET_ATTRIBUTES if attribute in declared
        ]
        if not insertion_candidates:
            raise ValueError(
                "DBC 中参与优化的报文缺少显式原 Offset，且 DBC 未声明可写入的 BO_ Offset 属性："
                + ", ".join(item.message_name for item in missing)
            )
        counts = {
            attribute: sum(
                match.group("attribute") == attribute for match in all_matches
            )
            for attribute in insertion_candidates
        }
        insertion_attribute = min(
            insertion_candidates,
            key=lambda attribute: (-counts[attribute], _OFFSET_ATTRIBUTES.index(attribute)),
        )
    elif selected_by_id:
        insertion_attribute = next(iter(selected_by_id.values())).group("attribute")

    selected = tuple(
        sorted(
            (
                (selected_by_id[frame_id], item)
                for frame_id, item in by_raw_id.items()
                if frame_id in selected_by_id
            ),
            key=lambda pair: pair[0].start("value"),
        )
    )
    attribute_name = insertion_attribute.decode("ascii") if insertion_attribute else ""
    return _PreparedWrite(
        original,
        selected,
        tuple(missing),
        insertion_attribute,
        DbcOffsetWritePlan(attribute_name, len(selected), len(missing)),
    )


def inspect_dbc_offset_write(
    source_path: Path, replacements: tuple[DbcOffsetReplacement, ...]
) -> DbcOffsetWritePlan:
    """Validate write capability without creating or changing any file."""
    source = source_path.resolve(strict=True)
    return _prepare_write(source, replacements).plan


def _verify_updated_bytes(
    updated: bytes, replacements: tuple[DbcOffsetReplacement, ...]
) -> None:
    matches_by_id: dict[int, list[re.Match[bytes]]] = {}
    for match in _OFFSET_LINE.finditer(updated):
        matches_by_id.setdefault(int(match.group("frame_id")), []).append(match)
    invalid: list[str] = []
    for item in replacements:
        candidates = matches_by_id.get(item.raw_dbc_id, ())
        selected: list[re.Match[bytes]] = []
        for attribute in _OFFSET_ATTRIBUTES:
            selected = [
                match for match in candidates if match.group("attribute") == attribute
            ]
            if selected:
                break
        expected = str(item.offset_us // 1_000).encode("ascii")
        if len(selected) != 1 or selected[0].group("value") != expected:
            invalid.append(item.message_name)
    if invalid:
        raise ValueError("DBC Offset 写回验证失败：" + ", ".join(invalid))


def write_dbc_with_offsets(
    source_path: Path,
    output_path: Path,
    replacements: tuple[DbcOffsetReplacement, ...],
) -> Path:
    """Create a DBC copy with explicit optimized Offset assignments.

    The function operates on bytes so encoding, line endings, spacing, comments,
    ordering and every unrelated field remain byte-for-byte identical. Existing
    values are replaced; messages inheriting a declared BO_ default receive one
    explicit BA_ assignment in the output copy.
    """

    source = source_path.resolve(strict=True)
    destination = output_path.resolve(strict=False)
    if source == destination:
        raise ValueError("DBC output must be a copy, not the imported source file")
    prepared = _prepare_write(source, replacements)
    chunks: list[bytes] = []
    cursor = 0
    for match, item in prepared.selected:
        chunks.append(prepared.original[cursor : match.start("value")])
        chunks.append(str(item.offset_us // 1_000).encode("ascii"))
        cursor = match.end("value")
    chunks.append(prepared.original[cursor:])
    updated = b"".join(chunks)
    if prepared.missing:
        newline = b"\r\n" if b"\r\n" in prepared.original else b"\n"
        if updated and not updated.endswith((b"\n", b"\r")):
            updated += newline
        for item in prepared.missing:
            updated += (
                b'BA_ "'
                + prepared.insertion_attribute
                + b'" BO_ '
                + str(item.raw_dbc_id).encode("ascii")
                + b" "
                + str(item.offset_us // 1_000).encode("ascii")
                + b";"
                + newline
            )
    _verify_updated_bytes(updated, replacements)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(updated)
    temporary.replace(destination)
    return destination
