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


@dataclass(frozen=True, slots=True)
class DbcOffsetReplacement:
    message_name: str
    can_id: int
    is_extended: bool
    offset_us: int

    @property
    def raw_dbc_id(self) -> int:
        return self.can_id | (0x80000000 if self.is_extended else 0)


def write_dbc_with_offsets(
    source_path: Path,
    output_path: Path,
    replacements: tuple[DbcOffsetReplacement, ...],
) -> Path:
    """Create a DBC copy changing only existing Offset numeric tokens.

    The function operates on bytes so encoding, line endings, spacing, comments,
    ordering and every unrelated field remain byte-for-byte identical. Missing or
    duplicate Offset attributes fail closed instead of inserting or guessing.
    """

    source = source_path.resolve(strict=True)
    destination = output_path.resolve(strict=False)
    if source == destination:
        raise ValueError("DBC output must be a copy, not the imported source file")
    if not replacements:
        raise ValueError("DBC Offset replacement set must not be empty")
    by_raw_id = {item.raw_dbc_id: item for item in replacements}
    if len(by_raw_id) != len(replacements):
        raise ValueError("DBC Offset replacements contain duplicate frame IDs")
    if any(item.offset_us < 0 or item.offset_us % 1_000 for item in replacements):
        raise ValueError("DBC Offset values must be non-negative whole milliseconds")

    original = source.read_bytes()
    matches_by_id: dict[int, list[re.Match[bytes]]] = {}
    for match in _OFFSET_LINE.finditer(original):
        frame_id = int(match.group("frame_id"))
        if frame_id in by_raw_id:
            matches_by_id.setdefault(frame_id, []).append(match)
    selected_by_id: dict[int, re.Match[bytes]] = {}
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
        if len(preferred) != 1:
            invalid.append(item.message_name)
        else:
            selected_by_id[frame_id] = preferred[0]
    if invalid:
        raise ValueError(
            "DBC 中参与优化的报文必须各有且仅有一个原 Offset 属性："
            + ", ".join(invalid)
        )

    selected = sorted(
        (
            (selected_by_id[frame_id], item)
            for frame_id, item in by_raw_id.items()
        ),
        key=lambda pair: pair[0].start("value"),
    )
    chunks: list[bytes] = []
    cursor = 0
    for match, item in selected:
        chunks.append(original[cursor : match.start("value")])
        chunks.append(str(item.offset_us // 1_000).encode("ascii"))
        cursor = match.end("value")
    chunks.append(original[cursor:])
    updated = b"".join(chunks)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(updated)
    temporary.replace(destination)
    return destination
