"""Parse and match optional XLSX routing-message exclusion tables."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .contracts import (
    RouteExclusionStatus,
    RouteMatchRecord,
    RouteMatchStatus,
    RouteMessageRecord,
    RouteRecordIssue,
    RoutingExclusionReport,
)


class RouteTableParseError(ValueError):
    """A supplied routing workbook cannot be used safely."""


@dataclass(frozen=True, slots=True)
class _Sheet:
    name: str
    rows: tuple[tuple[int, dict[int, str]], ...]


@dataclass(frozen=True, slots=True)
class _DirectRoutingLayout:
    header_row: int
    message_name_column: int
    can_id_column: int
    target_channel_column: int


@dataclass(frozen=True, slots=True)
class _FlzcuRoutingLayout:
    header_row: int
    message_name_column: int
    can_id_column: int
    target_columns: tuple[tuple[int, str], ...]


class RouteMessageTableParser:
    """Dependency-free reader for the subset of OOXML needed by routing tables."""

    SUPPORTED_SUFFIXES = frozenset({".xlsx"})
    DIRECT_ROUTING_SHEET = "直接报文路由"
    FLZCU_ROUTING_SHEET = "routing(flzcu)"
    COLUMN_ALIASES: Mapping[str, frozenset[str]] = {
        "target_network": frozenset(
            {
                "目标网段",
                "目标网络",
                "目标总线",
                "targetnetwork",
                "destinationnetwork",
                "targetbus",
            }
        ),
        "can_id": frozenset(
            {
                "canid",
                "报文id",
                "消息id",
                "帧id",
                "messageid",
                "identifier",
            }
        ),
        "message_name": frozenset(
            {
                "报文名",
                "报文名称",
                "消息名",
                "消息名称",
                "messagename",
            }
        ),
    }

    def parse(self, path: Path) -> tuple[RouteMessageRecord, ...]:
        source = path.resolve()
        if source.suffix.casefold() not in self.SUPPORTED_SUFFIXES:
            raise RouteTableParseError(f"不支持的路由报文表格式：{source.suffix}")
        if not source.is_file():
            raise RouteTableParseError(f"路由报文表不存在：{source}")
        try:
            sheets = self._read_xlsx(source)
        except (BadZipFile, ElementTree.ParseError, KeyError, OSError, ValueError) as exc:
            raise RouteTableParseError(f"无法打开或解析 XLSX：{exc}") from exc

        direct_sheets = tuple(
            sheet
            for sheet in sheets
            if normalize_sheet_name(sheet.name) == self.DIRECT_ROUTING_SHEET
        )
        if direct_sheets:
            return tuple(
                record
                for sheet in direct_sheets
                for record in self._parse_direct_routing_sheet(sheet, source)
            )

        flzcu_sheets = tuple(
            sheet
            for sheet in sheets
            if normalize_sheet_name(sheet.name) == self.FLZCU_ROUTING_SHEET
        )
        if flzcu_sheets:
            return tuple(
                record
                for sheet in flzcu_sheets
                for record in self._parse_flzcu_routing_sheet(sheet, source)
            )

        return self._parse_flat_sheets(sheets, source)

    def _parse_flat_sheets(
        self, sheets: Sequence[_Sheet], source: Path
    ) -> tuple[RouteMessageRecord, ...]:
        records: list[RouteMessageRecord] = []
        schema_errors: list[str] = []
        parsed_sheet_count = 0
        for sheet in sheets:
            if not sheet.rows:
                continue
            header = self._find_header(sheet)
            if header is None:
                if self._contains_known_header(sheet):
                    schema_errors.append(
                        f"Sheet {sheet.name!r} 缺少目标网段或 CAN ID 列"
                    )
                continue
            parsed_sheet_count += 1
            header_row, columns = header
            for row_number, values in sheet.rows:
                if row_number <= header_row or not any(value.strip() for value in values.values()):
                    continue
                target_raw = values.get(columns["target_network"], "").strip()
                can_raw = values.get(columns["can_id"], "").strip()
                message_name = (
                    values.get(columns["message_name"], "").strip()
                    if "message_name" in columns
                    else ""
                )
                records.append(
                    RouteMessageRecord(
                        target_network_raw=target_raw,
                        can_id_raw=can_raw,
                        can_id=parse_can_id(can_raw),
                        message_name=message_name or None,
                        source_file=source.name,
                        sheet_name=sheet.name,
                        row_number=row_number,
                    )
                )
        if schema_errors:
            raise RouteTableParseError("；".join(schema_errors))
        if parsed_sheet_count == 0:
            raise RouteTableParseError("路由报文表缺少目标网段或 CAN ID 列")
        return tuple(records)

    def _parse_direct_routing_sheet(
        self, sheet: _Sheet, source: Path
    ) -> tuple[RouteMessageRecord, ...]:
        layout = self._find_direct_routing_layout(sheet)
        if layout is None:
            raise RouteTableParseError(
                f"Sheet {sheet.name!r} 缺少目标网段报文名称、目标网段报文CANID或"
                "目标网段CAN通道表头"
            )

        records: list[RouteMessageRecord] = []
        for row_number, values in sheet.rows:
            if row_number <= layout.header_row:
                continue
            target_channel = values.get(layout.target_channel_column, "").strip()
            can_raw = values.get(layout.can_id_column, "").strip()
            message_name = values.get(layout.message_name_column, "").strip()
            if not any((target_channel, can_raw, message_name)):
                continue
            target_network = direct_can_network_name(target_channel)
            records.append(
                RouteMessageRecord(
                    target_network_raw=target_network or target_channel,
                    can_id_raw=can_raw,
                    can_id=parse_can_id(can_raw),
                    message_name=message_name or None,
                    source_file=source.name,
                    sheet_name=sheet.name,
                    row_number=row_number,
                )
            )
        return tuple(records)

    def _find_direct_routing_layout(
        self, sheet: _Sheet
    ) -> _DirectRoutingLayout | None:
        for header_row, values in sheet.rows[:20]:
            message_name_column = _unique_column(values, "目标网段报文名称")
            can_id_column = _unique_column(values, "目标网段报文canid")
            target_channel_column = _unique_column(values, "目标网段can通道")
            if (
                message_name_column is None
                or can_id_column is None
                or target_channel_column is None
            ):
                continue
            return _DirectRoutingLayout(
                header_row=header_row,
                message_name_column=message_name_column,
                can_id_column=can_id_column,
                target_channel_column=target_channel_column,
            )
        return None

    def _parse_flzcu_routing_sheet(
        self, sheet: _Sheet, source: Path
    ) -> tuple[RouteMessageRecord, ...]:
        layout = self._find_flzcu_layout(sheet)
        if layout is None:
            raise RouteTableParseError(
                f"Sheet {sheet.name!r} 缺少 Service Subscriber Data、"
                "Service Subscriber Subnet、目标 Msg Name 或目标 Msg ID 表头"
            )

        records: list[RouteMessageRecord] = []
        for row_number, values in sheet.rows:
            if row_number <= layout.header_row:
                continue
            selected_targets = tuple(
                target_network
                for column, target_network in layout.target_columns
                if values.get(column, "").strip()
            )
            if not selected_targets:
                continue
            can_raw = values.get(layout.can_id_column, "").strip()
            message_name = values.get(layout.message_name_column, "").strip()
            for target_network in selected_targets:
                records.append(
                    RouteMessageRecord(
                        target_network_raw=target_network,
                        can_id_raw=can_raw,
                        can_id=parse_can_id(can_raw),
                        message_name=message_name or None,
                        source_file=source.name,
                        sheet_name=sheet.name,
                        row_number=row_number,
                    )
                )
        return tuple(records)

    def _find_flzcu_layout(self, sheet: _Sheet) -> _FlzcuRoutingLayout | None:
        for group_row, group_values in sheet.rows[:20]:
            subscriber_data_column = _unique_column(
                group_values, "servicesubscriberdata"
            )
            subscriber_subnet_column = _unique_column(
                group_values, "servicesubscribersubnet"
            )
            if subscriber_data_column is None or subscriber_subnet_column is None:
                continue
            if subscriber_data_column >= subscriber_subnet_column:
                continue
            target_end_column = min(
                (
                    column
                    for column, value in group_values.items()
                    if column > subscriber_subnet_column and value.strip()
                ),
                default=None,
            )
            if target_end_column is None:
                continue
            for header_row, values in sheet.rows:
                if not group_row < header_row <= group_row + 10:
                    continue
                destination_values = {
                    column: value
                    for column, value in values.items()
                    if subscriber_data_column <= column < subscriber_subnet_column
                }
                message_name_column = _unique_column(destination_values, "msgname")
                can_id_column = _unique_column(destination_values, "msgid")
                if message_name_column is None or can_id_column is None:
                    continue
                target_columns = tuple(
                    (column, target_network)
                    for column, value in values.items()
                    if subscriber_subnet_column <= column < target_end_column
                    if (target_network := flzcu_can_network_name(value)) is not None
                )
                if target_columns:
                    return _FlzcuRoutingLayout(
                        header_row=header_row,
                        message_name_column=message_name_column,
                        can_id_column=can_id_column,
                        target_columns=target_columns,
                    )
        return None

    def _find_header(self, sheet: _Sheet) -> tuple[int, dict[str, int]] | None:
        for row_number, values in sheet.rows[:50]:
            matches: dict[str, list[int]] = defaultdict(list)
            for column, value in values.items():
                normalized = normalize_header(value)
                for semantic, aliases in self.COLUMN_ALIASES.items():
                    if normalized in aliases:
                        matches[semantic].append(column)
            if not matches:
                continue
            if any(len(columns) > 1 for columns in matches.values()):
                raise RouteTableParseError(
                    f"Sheet {sheet.name!r} 第 {row_number} 行存在重复语义列"
                )
            if len(matches.get("target_network", ())) == 1 and len(
                matches.get("can_id", ())
            ) == 1:
                return row_number, {
                    semantic: columns[0] for semantic, columns in matches.items()
                }
        return None

    def _contains_known_header(self, sheet: _Sheet) -> bool:
        aliases = frozenset().union(*self.COLUMN_ALIASES.values())
        return any(
            normalize_header(value) in aliases
            for _, values in sheet.rows[:50]
            for value in values.values()
        )

    @staticmethod
    def _read_xlsx(path: Path) -> tuple[_Sheet, ...]:
        with ZipFile(path) as archive:
            shared = _shared_strings(archive)
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            targets = {
                relation.attrib["Id"]: relation.attrib["Target"]
                for relation in relationships
            }
            sheets: list[_Sheet] = []
            for sheet_element in workbook.findall(".//{*}sheet"):
                name = sheet_element.attrib.get("name", "Sheet")
                relationship_id = next(
                    (
                        value
                        for key, value in sheet_element.attrib.items()
                        if key.endswith("}id") or key == "r:id"
                    ),
                    None,
                )
                if relationship_id is None or relationship_id not in targets:
                    raise ValueError(f"Sheet {name!r} 缺少有效关系")
                target = targets[relationship_id].replace("\\", "/")
                member = (
                    target.lstrip("/")
                    if target.startswith("/xl/")
                    else str(PurePosixPath("xl") / target)
                )
                xml = ElementTree.fromstring(archive.read(member))
                rows: list[tuple[int, dict[int, str]]] = []
                for fallback_row, row in enumerate(xml.findall(".//{*}row"), start=1):
                    row_number = int(row.attrib.get("r", fallback_row))
                    values: dict[int, str] = {}
                    fallback_column = 0
                    for cell in row.findall("{*}c"):
                        reference = cell.attrib.get("r", "")
                        column = _column_index(reference) if reference else fallback_column
                        values[column] = _cell_text(cell, shared)
                        fallback_column = column + 1
                    rows.append((row_number, values))
                sheets.append(_Sheet(name, tuple(rows)))
            return tuple(sheets)


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-:/（）()]+", "", value).casefold()


def normalize_sheet_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def flzcu_can_network_name(value: str) -> str | None:
    """Map a left-domain routing matrix header to the imported DBC network name."""

    match = re.fullmatch(r"FL_(?:CANFD|CAN)_([A-Z0-9_]+)", value.strip(), re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).upper()


def direct_can_network_name(value: str) -> str | None:
    """Map a standard gateway target channel such as ``DACAN`` to ``DA``."""

    match = re.fullmatch(r"([A-Z0-9_]+)CAN", value.strip(), re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).upper()


def _unique_column(values: Mapping[int, str], expected: str) -> int | None:
    matches = [
        column
        for column, value in values.items()
        if normalize_header(value) == expected
    ]
    return matches[0] if len(matches) == 1 else None


def normalize_network_name(value: str) -> str:
    """Normalize an explicit network identity without substring/fuzzy matching."""

    return re.sub(r"\s+", " ", value.strip()).casefold()


def parse_can_id(value: str) -> int | None:
    """Normalize decimal, ``0x`` and hexadecimal ``h`` CAN IDs to integers."""

    raw = value.strip()
    if not raw:
        return None
    try:
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+", raw):
            parsed = int(raw[2:], 16)
        elif re.fullmatch(r"[0-9A-Fa-f]+[hH]", raw):
            parsed = int(raw[:-1], 16)
        elif re.fullmatch(r"[0-9]+(?:\.0+)?", raw):
            parsed = int(float(raw))
        else:
            return None
    except ValueError:
        return None
    return parsed if 0 <= parsed <= 0x1FFFFFFF else None


def match_route_messages(
    records: Sequence[RouteMessageRecord],
    network_names: Mapping[str, str],
    network_messages: Mapping[str, Sequence[tuple[int, str, bool]]],
    *,
    table_count: int,
) -> RoutingExclusionReport:
    """Match by ``network_id + integer CAN ID`` and retain every source row."""

    aliases: dict[str, set[str]] = defaultdict(set)
    for network_id, network_name in network_names.items():
        aliases[normalize_network_name(network_id)].add(network_id)
        aliases[normalize_network_name(network_name)].add(network_id)

    resolved: list[tuple[RouteMessageRecord, tuple[str, ...]]] = []
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        candidates = tuple(
            sorted(aliases.get(normalize_network_name(record.target_network_raw), ()))
        )
        resolved.append((record, candidates))
        if record.can_id is not None:
            identity = candidates[0] if len(candidates) == 1 else normalize_network_name(
                record.target_network_raw
            )
            groups[(identity, record.can_id)].append(index)

    issues_by_index: dict[int, list[RouteRecordIssue]] = defaultdict(list)
    for indexes in groups.values():
        if len(indexes) <= 1:
            continue
        for duplicate_index in indexes[1:]:
            issues_by_index[duplicate_index].append(RouteRecordIssue.DUPLICATE)
        names: set[str] = set()
        for index in indexes:
            message_name = records[index].message_name
            if message_name is not None and message_name.strip():
                names.add(message_name.strip())
        if len(names) > 1:
            for index in indexes:
                issues_by_index[index].append(
                    RouteRecordIssue.DUPLICATE_CONFLICT_WARNING
                )

    excluded: set[tuple[str, int]] = set()
    matched: list[RouteMatchRecord] = []
    for index, (record, candidates) in enumerate(resolved):
        record = replace(
            record,
            target_network_id=candidates[0] if len(candidates) == 1 else None,
        )
        issues = issues_by_index[index]
        if record.can_id is None:
            matched.append(
                RouteMatchRecord(
                    record,
                    candidates[0] if len(candidates) == 1 else None,
                    None,
                    RouteMatchStatus.INVALID_CAN_ID,
                    RouteExclusionStatus.NOT_EXCLUDED,
                    tuple(issues),
                    "INVALID_CAN_ID：CAN ID 为空、无法解析或超出支持范围",
                )
            )
            continue
        if not candidates:
            matched.append(
                RouteMatchRecord(
                    record,
                    None,
                    None,
                    RouteMatchStatus.NOT_FOUND,
                    RouteExclusionStatus.NOT_EXCLUDED,
                    tuple(issues),
                    "TARGET_NETWORK_NOT_FOUND：目标网段无法映射到当前工程",
                )
            )
            continue
        if len(candidates) > 1:
            matched.append(
                RouteMatchRecord(
                    record,
                    None,
                    None,
                    RouteMatchStatus.AMBIGUOUS,
                    RouteExclusionStatus.NOT_EXCLUDED,
                    tuple(issues),
                    "TARGET_NETWORK_AMBIGUOUS：目标网段对应多个导入 DBC",
                )
            )
            continue
        network_id = candidates[0]
        dbc_matches = tuple(
            (name, is_extended)
            for can_id, name, is_extended in network_messages.get(network_id, ())
            if can_id == record.can_id
        )
        if not dbc_matches:
            matched.append(
                RouteMatchRecord(
                    record,
                    network_id,
                    None,
                    RouteMatchStatus.NOT_FOUND,
                    RouteExclusionStatus.NOT_EXCLUDED,
                    tuple(issues),
                    "MESSAGE_NOT_FOUND：目标网段中没有相同 CAN ID 的可优化报文",
                )
            )
            continue
        if len(dbc_matches) > 1:
            matched.append(
                RouteMatchRecord(
                    record,
                    network_id,
                    None,
                    RouteMatchStatus.AMBIGUOUS,
                    RouteExclusionStatus.NOT_EXCLUDED,
                    tuple(issues),
                    "DBC_KEY_AMBIGUOUS：同一网段和 CAN ID 匹配多个报文："
                    + "、".join(name for name, _is_extended in dbc_matches),
                )
            )
            continue
        dbc_name, dbc_is_extended = dbc_matches[0]
        if record.message_name is not None and record.message_name != dbc_name:
            issues.append(RouteRecordIssue.NAME_MISMATCH_WARNING)
        key = (network_id, record.can_id)
        exclusion_status = (
            RouteExclusionStatus.ALREADY_EXCLUDED
            if key in excluded
            else RouteExclusionStatus.EXCLUDED
        )
        excluded.add(key)
        note_parts: list[str] = []
        if RouteRecordIssue.NAME_MISMATCH_WARNING in issues:
            note_parts.append(
                f"NAME_MISMATCH_WARNING：Excel={record.message_name}，DBC={dbc_name}"
            )
        if RouteRecordIssue.DUPLICATE_CONFLICT_WARNING in issues:
            note_parts.append("DUPLICATE_CONFLICT_WARNING：同一主键的辅助信息冲突")
        matched.append(
            RouteMatchRecord(
                record,
                network_id,
                dbc_name,
                RouteMatchStatus.MATCHED,
                exclusion_status,
                tuple(dict.fromkeys(issues)),
                "；".join(note_parts) or "按目标网段 + CAN ID 匹配并排除",
                dbc_is_extended,
            )
        )
    return RoutingExclusionReport(table_count=table_count, records=tuple(matched))


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return ()
    return tuple(
        "".join(text.text or "" for text in item.findall(".//{*}t"))
        for item in root.findall("{*}si")
    )


def _cell_text(cell: ElementTree.Element, shared: tuple[str, ...]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//{*}t"))
    value = cell.find("{*}v")
    raw = "" if value is None or value.text is None else value.text
    if kind == "s":
        index = int(raw)
        if not 0 <= index < len(shared):
            raise ValueError(f"共享字符串索引越界：{index}")
        return shared[index]
    return raw


def _column_index(reference: str) -> int:
    match = re.match(r"([A-Za-z]+)", reference)
    if match is None:
        raise ValueError(f"无效单元格引用：{reference}")
    result = 0
    for character in match.group(1).upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1
