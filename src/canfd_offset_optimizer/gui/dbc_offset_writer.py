"""Byte-preserving writer for optimized GenMsgStartDelayTime DBC attributes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from .output_paths import WINDOWS_SAFE_DBC_PATH_LENGTH, windows_utf16_path_length


_OFFSET_ATTRIBUTE = b"GenMsgStartDelayTime"
_OFFSET_LINE = re.compile(
    rb'(?m)^(?P<prefix>[ \t]*BA_[ \t]+"GenMsgStartDelayTime"[ \t]+BO_[ \t]+'
    rb"(?P<frame_id>[0-9]+)[ \t]+)"
    rb"(?P<value>[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))"
    rb"(?P<suffix>[ \t]*;[^\r\n]*)(?P<carriage_return>\r?)$"
)
_OFFSET_DEFINITION = re.compile(
    rb'(?m)^[ \t]*BA_DEF_[ \t]+BO_[ \t]+"GenMsgStartDelayTime"[ \t]+'
)
_DELAY_LINE = re.compile(
    rb'(?m)^[ \t]*BA_[ \t]+"GenMsgDelayTime"[ \t]+BO_[ \t]+'
    rb"[0-9]+[ \t]+[^;\r\n]*;[^\r\n]*(?:\r?$)"
)
_MESSAGE_ATTRIBUTE_LINE = re.compile(
    rb'(?m)^[ \t]*BA_[ \t]+"[^"\r\n]+"[ \t]+BO_[ \t]+'
    rb"[0-9]+[ \t]+[^;\r\n]*;[^\r\n]*(?:\r?\n|$)"
)
_ANY_ATTRIBUTE_LINE = re.compile(
    rb'(?m)^[ \t]*BA_[ \t]+"[^"\r\n]+"[ \t]+'
    rb"[^;\r\n]*;[^\r\n]*(?:\r?\n|$)"
)
_ATTRIBUTE_SCHEMA_LINE = re.compile(
    rb'(?m)^[ \t]*BA_DEF_(?:DEF_)?[ \t]+[^;\r\n]*;[^\r\n]*(?:\r?\n|$)'
)
_VAL_LINE = re.compile(rb"(?m)^[ \t]*VAL_[ \t]+")


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
    """Auditable description of StartDelay materialization."""

    attribute_name: str
    replaced_count: int
    inserted_count: int
    unchanged_count: int = 0
    warnings: tuple[str, ...] = ()
    untouched_delay_count: int = 0

    @property
    def message_count(self) -> int:
        return self.replaced_count + self.inserted_count

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


def validate_dbc_output_path(output_path: Path) -> None:
    """Reject unsafe legacy-Windows paths without changing the DBC basename."""

    length = windows_utf16_path_length(output_path)
    if length > WINDOWS_SAFE_DBC_PATH_LENGTH:
        raise ValueError(
            "DBC 最终输出路径超过 Windows 安全预算："
            f"{length} > {WINDOWS_SAFE_DBC_PATH_LENGTH}；{output_path.resolve(strict=False)}"
        )


@dataclass(frozen=True, slots=True)
class _PreparedWrite:
    original: bytes
    selected: tuple[tuple[re.Match[bytes], DbcOffsetReplacement], ...]
    missing: tuple[DbcOffsetReplacement, ...]
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
    if _OFFSET_DEFINITION.search(original) is None:
        raise ValueError(
            "优化成功，但 DBC 缺少 GenMsgStartDelayTime 的 BO_ 属性定义，"
            "无法安全回写 Offset"
        )

    matches_by_id: dict[int, list[re.Match[bytes]]] = {}
    for match in _OFFSET_LINE.finditer(original):
        frame_id = int(match.group("frame_id"))
        if frame_id in by_raw_id:
            matches_by_id.setdefault(frame_id, []).append(match)

    selected_by_id: dict[int, tuple[re.Match[bytes], ...]] = {}
    missing: list[DbcOffsetReplacement] = []
    conflicting: list[str] = []
    warnings: list[str] = []
    unchanged_count = 0
    for frame_id, item in by_raw_id.items():
        candidates = tuple(matches_by_id.get(frame_id, ()))
        if not candidates:
            missing.append(item)
            continue
        values = {
            Decimal(match.group("value").decode("ascii")) for match in candidates
        }
        if len(values) > 1:
            conflicting.append(item.message_name)
            continue
        selected_by_id[frame_id] = candidates
        if len(candidates) > 1:
            warnings.append(
                f"{item.message_name} 存在 {len(candidates)} 条同值 "
                "GenMsgStartDelayTime；将同步更新全部声明"
            )
        expected = Decimal(item.offset_us // 1_000)
        if values == {expected}:
            unchanged_count += 1
    if conflicting:
        raise ValueError(
            "DBC 中参与优化的报文存在冲突的 GenMsgStartDelayTime 原值："
            + ", ".join(conflicting)
        )

    selected = tuple(
        sorted(
            (
                (match, item)
                for frame_id, item in by_raw_id.items()
                for match in selected_by_id.get(frame_id, ())
            ),
            key=lambda pair: pair[0].start("value"),
        )
    )
    plan = DbcOffsetWritePlan(
        attribute_name=_OFFSET_ATTRIBUTE.decode("ascii"),
        replaced_count=len(selected_by_id),
        inserted_count=len(missing),
        unchanged_count=unchanged_count,
        warnings=tuple(warnings),
        untouched_delay_count=sum(1 for _ in _DELAY_LINE.finditer(original)),
    )
    return _PreparedWrite(original, selected, tuple(missing), plan)


def inspect_dbc_offset_write(
    source_path: Path, replacements: tuple[DbcOffsetReplacement, ...]
) -> DbcOffsetWritePlan:
    """Validate write capability without creating or changing any file."""

    source = source_path.resolve(strict=True)
    return _prepare_write(source, replacements).plan


def _insertion_anchor(content: bytes) -> int:
    """Return a stable BA_ assignment insertion point without reordering sections."""

    first_val = _VAL_LINE.search(content)
    boundary = first_val.start() if first_val is not None else len(content)
    message_attributes = tuple(
        match
        for match in _MESSAGE_ATTRIBUTE_LINE.finditer(content)
        if match.start() < boundary
    )
    if message_attributes:
        return message_attributes[-1].end()
    if first_val is not None:
        return first_val.start()

    attributes = tuple(_ANY_ATTRIBUTE_LINE.finditer(content))
    if attributes:
        return attributes[-1].end()
    schema = tuple(_ATTRIBUTE_SCHEMA_LINE.finditer(content))
    if schema:
        return schema[-1].end()
    # A StartDelay BA_DEF_ was already required above, so this is unreachable
    # unless the schema regex and definition regex drift apart.
    raise ValueError("无法确定 GenMsgStartDelayTime 的安全 BA_ 插入位置")


def _insert_explicit_offsets(
    content: bytes, missing: tuple[DbcOffsetReplacement, ...], newline: bytes
) -> bytes:
    if not missing:
        return content
    anchor = _insertion_anchor(content)
    lines = b"".join(
        b'BA_ "GenMsgStartDelayTime" BO_ '
        + str(item.raw_dbc_id).encode("ascii")
        + b" "
        + str(item.offset_us // 1_000).encode("ascii")
        + b";"
        + newline
        for item in missing
    )
    prefix = b""
    if anchor > 0 and content[anchor - 1 : anchor] not in (b"\n", b"\r"):
        prefix = newline
    return content[:anchor] + prefix + lines + content[anchor:]


def _verify_updated_bytes(
    original: bytes,
    updated: bytes,
    replacements: tuple[DbcOffsetReplacement, ...],
    missing: tuple[DbcOffsetReplacement, ...],
) -> None:
    if tuple(_DELAY_LINE.findall(original)) != tuple(_DELAY_LINE.findall(updated)):
        raise ValueError("GenMsgDelayTime 保护校验失败：Offset Writer 不得修改该属性")

    matches_by_id: dict[int, list[re.Match[bytes]]] = {}
    for match in _OFFSET_LINE.finditer(updated):
        matches_by_id.setdefault(int(match.group("frame_id")), []).append(match)
    invalid: list[str] = []
    for item in replacements:
        selected = matches_by_id.get(item.raw_dbc_id, ())
        expected = str(item.offset_us // 1_000).encode("ascii")
        if not selected or any(match.group("value") != expected for match in selected):
            invalid.append(item.message_name)
    if invalid:
        raise ValueError("DBC Offset 写回验证失败：" + ", ".join(invalid))

    first_val = _VAL_LINE.search(updated)
    if first_val is not None:
        for item in missing:
            inserted = matches_by_id.get(item.raw_dbc_id, ())
            if not inserted or max(match.start() for match in inserted) >= first_val.start():
                raise ValueError(
                    "DBC section 验证失败：新增 GenMsgStartDelayTime 必须位于首个 VAL_ 前"
                )


def write_dbc_with_offsets(
    source_path: Path,
    output_path: Path,
    replacements: tuple[DbcOffsetReplacement, ...],
) -> Path:
    """Create a minimally patched DBC copy with explicit optimized StartDelay."""

    source = source_path.resolve(strict=True)
    destination = output_path.resolve(strict=False)
    if source == destination:
        raise ValueError("DBC output must be a copy, not the imported source file")
    validate_dbc_output_path(destination)
    prepared = _prepare_write(source, replacements)

    chunks: list[bytes] = []
    cursor = 0
    for match, item in prepared.selected:
        chunks.append(prepared.original[cursor : match.start("value")])
        chunks.append(str(item.offset_us // 1_000).encode("ascii"))
        cursor = match.end("value")
    chunks.append(prepared.original[cursor:])
    updated = b"".join(chunks)
    newline = b"\r\n" if b"\r\n" in prepared.original else b"\n"
    updated = _insert_explicit_offsets(updated, prepared.missing, newline)
    _verify_updated_bytes(
        prepared.original, updated, replacements, prepared.missing
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix=".dbc-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
