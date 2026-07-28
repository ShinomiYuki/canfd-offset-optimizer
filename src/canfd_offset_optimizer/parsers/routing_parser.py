"""! @file routing_parser.py
@brief 解析最终论文实验使用的直接报文路由 Excel。

@details
路由排除的唯一匹配键为 ``(canonical target network, CAN ID, extended flag)``。
解析器只接受权威 ``直接报文路由`` Sheet，不做 substring/fuzzy 匹配，也不依赖
报文名。为避免给核心包引入只为读取一个工作簿的重量级依赖，XLSX 使用标准库
按 OOXML 只读解析。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from ..exceptions import InputFileError, MissingFieldError


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _MAIN_NS, "r": _REL_NS, "pr": _PACKAGE_REL_NS}
_CELL_REFERENCE = re.compile(r"^([A-Z]+)[0-9]+$")


@dataclass(frozen=True, slots=True)
class RouteMessageKey:
    """路由排除的规范化精确键。"""

    target_network: str
    can_id: int
    is_extended: bool


@dataclass(frozen=True, slots=True)
class RouteMessageEntry:
    """路由表中的一条目标侧直接报文。"""

    key: RouteMessageKey
    message_name: str
    row_number: int
    raw_target_network: str
    raw_can_id: str


@dataclass(frozen=True, slots=True)
class RoutingTable:
    """一个已解析的直接报文路由表。"""

    path: Path
    sheet_name: str
    entries: tuple[RouteMessageEntry, ...]

    def entries_for_target(self, target_network: str) -> tuple[RouteMessageEntry, ...]:
        canonical = normalize_target_network(target_network)
        return tuple(
            entry for entry in self.entries if entry.key.target_network == canonical
        )

    def keys_for_target(self, target_network: str) -> frozenset[RouteMessageKey]:
        return frozenset(entry.key for entry in self.entries_for_target(target_network))


def normalize_target_network(value: object) -> str:
    """将 ``CHCAN``/``CH`` 等显式网络标识规范为同一精确键。

    只执行空白、连字符/下划线和末尾 ``CAN`` 的确定性规范化；不做 substring
    或相似度匹配。
    """

    if not isinstance(value, str):
        raise MissingFieldError(f"routing target network must be text, got {value!r}")
    normalized = re.sub(r"[\s_-]+", "", value).upper()
    if normalized.endswith("CAN"):
        normalized = normalized[:-3]
    if not normalized or not normalized.isalnum():
        raise MissingFieldError(f"invalid routing target network: {value!r}")
    return normalized


def normalize_can_id(value: object) -> int:
    """规范化 Excel 数值、十进制或十六进制 CAN ID。"""

    if isinstance(value, bool):
        raise MissingFieldError(f"routing CAN ID must not be boolean: {value!r}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise MissingFieldError(f"routing CAN ID must be integral: {value!r}")
        result = int(value)
    elif isinstance(value, str):
        text = value.strip().replace("_", "")
        if not text:
            raise MissingFieldError("routing CAN ID must not be empty")
        lowered = text.lower()
        try:
            if lowered.startswith("0x"):
                result = int(lowered, 16)
            elif lowered.endswith("h"):
                result = int(lowered[:-1], 16)
            else:
                result = int(lowered, 10)
        except ValueError as exc:
            raise MissingFieldError(f"invalid routing CAN ID: {value!r}") from exc
    else:
        raise MissingFieldError(f"invalid routing CAN ID: {value!r}")
    if not 0 <= result <= 0x1FFFFFFF:
        raise MissingFieldError(f"routing CAN ID is outside CAN range: {value!r}")
    return result


def _is_extended_frame(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        raise MissingFieldError(f"routing target frame type is missing: {value!r}")
    normalized = value.upper().replace("-", "_").replace(" ", "_")
    if "EXTENDED" in normalized:
        return True
    if "STANDARD" in normalized:
        return False
    raise MissingFieldError(f"unsupported routing target frame type: {value!r}")


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(reference.upper())
    if match is None:
        raise InputFileError(f"invalid XLSX cell reference: {reference!r}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall("m:si", _NS)
    )


def _cell_value(cell: ElementTree.Element, shared: tuple[str, ...]) -> object:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (IndexError, ValueError) as exc:
            raise InputFileError(f"invalid XLSX shared string index: {raw!r}") from exc
    if cell_type in {"str", "e"}:
        return raw
    try:
        numeric = float(raw)
    except ValueError:
        return raw
    return int(numeric) if numeric.is_integer() else numeric


def _sheet_rows(
    archive: ZipFile,
    sheet_path: str,
    shared: tuple[str, ...],
) -> tuple[tuple[int, dict[int, object]], ...]:
    root = ElementTree.fromstring(archive.read(sheet_path))
    rows: list[tuple[int, dict[int, object]]] = []
    for row in root.findall(".//m:sheetData/m:row", _NS):
        row_number = int(row.attrib.get("r", len(rows) + 1))
        values: dict[int, object] = {}
        for cell in row.findall("m:c", _NS):
            reference = cell.attrib.get("r")
            if reference is None:
                raise InputFileError("XLSX cell has no reference")
            values[_column_index(reference)] = _cell_value(cell, shared)
        rows.append((row_number, values))
    return tuple(rows)


def _resolve_sheet_path(target: str) -> str:
    path = PurePosixPath(target)
    if path.is_absolute():
        path = PurePosixPath(*path.parts[1:])
    if not path.parts or path.parts[0] != "xl":
        path = PurePosixPath("xl") / path
    return str(path)


def parse_routing_excel(path: Path) -> RoutingTable:
    """解析 ``直接报文路由`` Sheet 的目标网段、目标 CAN ID 与帧类型。"""

    resolved = path.resolve()
    if not resolved.is_file():
        raise InputFileError(f"routing Excel does not exist: {resolved}")
    try:
        with ZipFile(resolved) as archive:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            targets = {
                item.attrib["Id"]: item.attrib["Target"] for item in relationships
            }
            matches: list[tuple[str, str]] = []
            sheets = workbook.find("m:sheets", _NS)
            if sheets is None:
                raise InputFileError(f"{resolved}: XLSX workbook contains no sheets")
            for sheet in sheets:
                name = sheet.attrib.get("name", "")
                if name.strip() != "直接报文路由":
                    continue
                relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
                if relation_id is None or relation_id not in targets:
                    raise InputFileError(f"{resolved}: routing sheet relation is missing")
                matches.append((name, _resolve_sheet_path(targets[relation_id])))
            if len(matches) != 1:
                raise InputFileError(
                    f"{resolved}: expected exactly one '直接报文路由' sheet, "
                    f"found {len(matches)}"
                )
            sheet_name, sheet_path = matches[0]
            shared = _shared_strings(archive)
            rows = _sheet_rows(archive, sheet_path, shared)
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise InputFileError(f"cannot parse routing Excel {resolved}: {exc}") from exc

    if not rows:
        raise InputFileError(f"{resolved}: routing sheet is empty")
    header_row, header_values = rows[0]
    headers = {
        str(value).strip(): index
        for index, value in header_values.items()
        if str(value).strip()
    }
    required = {
        "目标网段报文名称",
        "目标网段报文CANID",
        "目标网段报文类型",
        "目标网段CAN通道",
    }
    missing = sorted(required - headers.keys())
    if missing:
        raise MissingFieldError(
            f"{resolved}:{sheet_name}: missing routing columns: {', '.join(missing)}"
        )

    entries: list[RouteMessageEntry] = []
    for row_number, values in rows[1:]:
        raw_network = values.get(headers["目标网段CAN通道"], "")
        raw_can_id = values.get(headers["目标网段报文CANID"], "")
        raw_frame_type = values.get(headers["目标网段报文类型"], "")
        raw_name = values.get(headers["目标网段报文名称"], "")
        if all(
            value == "" or value is None
            for value in (raw_network, raw_can_id, raw_frame_type, raw_name)
        ):
            continue
        try:
            canonical_network = normalize_target_network(raw_network)
            can_id = normalize_can_id(raw_can_id)
            is_extended = _is_extended_frame(raw_frame_type)
        except MissingFieldError as exc:
            raise MissingFieldError(
                f"{resolved}:{sheet_name}: row {row_number}: {exc}"
            ) from exc
        entries.append(
            RouteMessageEntry(
                RouteMessageKey(canonical_network, can_id, is_extended),
                str(raw_name).strip(),
                row_number,
                str(raw_network).strip(),
                str(raw_can_id).strip(),
            )
        )
    if not entries:
        raise InputFileError(f"{resolved}:{sheet_name}: no direct routing rows found")
    return RoutingTable(resolved, sheet_name, tuple(entries))
