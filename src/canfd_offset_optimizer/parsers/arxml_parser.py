"""! @file arxml_parser.py
@brief 递归扫描 AUTOSAR XML 并索引通道相关 bitrate/BRS 参数。

@details
解析使用 local-name 与候选参数尾名，不依赖 namespace 前缀、文件名或供应商顺序。

@author 篠見由紀
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ..exceptions import DataConflictError, InputFileError, MissingFieldError


PARAMETER_NAMES: dict[str, tuple[str, ...]] = {
    "nominal_bitrate": (
        "cancontrollerbaudrate",
        "cannominalbitrate",
        "nominalbitrate",
    ),
    "data_bitrate": (
        "cancontrollerfddatarate",
        "cancontrollerfdbaudrate",
        "databitrate",
    ),
    "brs": (
        "cancontrollerfdbrs",
        "canfdbrsenabled",
        "brsenabled",
        "cancontrollertxbitrateswitch",
    ),
}

KBIT_PER_SECOND_PARAMETER_NAMES = {
    "cancontrollerbaudrate",
    "cancontrollerfddatarate",
    "cancontrollerfdbaudrate",
}


@dataclass(frozen=True, slots=True)
class ArxmlChannelData:
    """! @brief 一个目标 CAN 通道的可选配置字段和来源。"""

    name: str
    nominal_bitrate: int | None
    data_bitrate: int | None
    brs: bool | None
    field_sources: tuple[tuple[str, str], ...]
    files: tuple[Path, ...]


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _child_text(element: etree._Element, local_name: str) -> str | None:
    for child in element:
        if _local_name(child) == local_name and child.text:
            return child.text.strip()
    return None


def _parameter_spec(reference: str) -> tuple[str, int] | None:
    tail = reference.rsplit("/", 1)[-1].lower().replace("-", "").replace("_", "")
    for key, candidates in PARAMETER_NAMES.items():
        for candidate in candidates:
            if tail == candidate or tail.endswith(candidate):
                scale = 1000 if candidate in KBIT_PER_SECOND_PARAMETER_NAMES else 1
                return key, scale
    return None


def _parse_scaled_integer(value_text: str, scale: int, source: str) -> int:
    """! @brief Parse a numeric AUTOSAR value and convert it to an integer base unit."""
    try:
        scaled = Decimal(value_text) * scale
    except InvalidOperation as exc:
        raise InputFileError(f"invalid numeric value {value_text!r} at {source}") from exc
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise InputFileError(
            f"value {value_text!r} does not convert to an integral bit rate at {source}"
        )
    value = int(scaled)
    if value <= 0:
        raise InputFileError(f"bit rate must be positive at {source}, got {value_text!r}")
    return value


def _parse_bool(value: str, source: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise InputFileError(f"invalid BRS boolean {value!r} at {source}")


def _short_name_path(element: etree._Element) -> str | None:
    """! @brief 构造 AUTOSAR SHORT-NAME 祖先路径，供引用稳定解析。"""
    names: list[str] = []
    current: etree._Element | None = element
    while current is not None:
        short_name = _child_text(current, "SHORT-NAME")
        if short_name is not None:
            names.append(short_name)
        current = current.getparent()
    return "/" + "/".join(reversed(names)) if names else None


def _referenced_elements(
    container: etree._Element,
    by_path: dict[str, list[etree._Element]],
    by_short_name: dict[str, list[etree._Element]],
) -> tuple[etree._Element, ...]:
    """! @brief 解析容器子树中的实例引用；歧义的短名回退不会静默选择。"""
    targets: list[etree._Element] = []
    for element in container.iter():
        local_name = _local_name(element)
        if not local_name.endswith("-REF") or local_name == "DEFINITION-REF":
            continue
        reference = (element.text or "").strip()
        if not reference:
            continue
        exact = by_path.get(reference, [])
        if len(exact) > 1:
            raise InputFileError(f"ambiguous AUTOSAR reference {reference!r}")
        target = exact[0] if exact else None
        if target is None:
            candidates = by_short_name.get(reference.rsplit("/", 1)[-1], [])
            if len(candidates) == 1:
                target = candidates[0]
        if target is not None:
            targets.append(target)
    return tuple(targets)


def parse_arxml_directory(directory: Path, channel_name: str) -> ArxmlChannelData:
    """! @brief 递归读取 `.arxml` 并定位目标通道容器中的关键参数。

    @raises MissingFieldError 找不到目标通道或其中不存在任何可识别字段时抛出。
    """
    if not directory.is_dir():
        raise InputFileError(f"ARXML directory does not exist: {directory}")
    files = tuple(
        sorted(path.resolve() for path in directory.rglob("*") if path.suffix.lower() == ".arxml")
    )
    if not files:
        raise InputFileError(f"ARXML directory contains no .arxml files: {directory}")
    matching_containers: list[tuple[Path, etree._Element]] = []
    short_name_index: dict[str, list[etree._Element]] = {}
    path_index: dict[str, list[etree._Element]] = {}
    owner: dict[int, Path] = {}
    trees: list[etree._ElementTree] = []
    for path in files:
        try:
            tree = etree.parse(
                str(path),
                parser=etree.XMLParser(resolve_entities=False, no_network=True),
            )
        except (OSError, etree.XMLSyntaxError) as exc:
            raise InputFileError(f"cannot parse ARXML {path}: {exc}") from exc
        trees.append(tree)
        for element in tree.iter():
            owner[id(element)] = path
            short_name = _child_text(element, "SHORT-NAME")
            if short_name is not None:
                short_name_index.setdefault(short_name, []).append(element)
                absolute_path = _short_name_path(element)
                if absolute_path is not None:
                    path_index.setdefault(absolute_path, []).append(element)
                if short_name == channel_name:
                    matching_containers.append((path, element))
    if not matching_containers:
        known = ", ".join(sorted(short_name_index)[:10])
        raise MissingFieldError(
            f"ARXML channel {channel_name!r} was not found; indexed SHORT-NAME values: {known}"
        )
    values: dict[str, int | bool] = {}
    sources: dict[str, str] = {}
    queue = [container for _, container in matching_containers]
    visited: set[int] = set()
    while queue:
        container = queue.pop(0)
        identity = id(container)
        if identity in visited:
            continue
        visited.add(identity)
        queue.extend(_referenced_elements(container, path_index, short_name_index))
        path = owner[identity]
        for element in container.iter():
            reference = _child_text(element, "DEFINITION-REF")
            value_text = _child_text(element, "VALUE")
            if reference is None or value_text is None:
                continue
            spec = _parameter_spec(reference)
            if spec is None:
                continue
            key, scale = spec
            conversion = " [kbit/s -> bit/s]" if scale == 1000 else ""
            source = f"{path}:{element.sourceline or '?'}:{reference}{conversion}"
            value: int | bool = (
                _parse_bool(value_text, source)
                if key == "brs"
                else _parse_scaled_integer(value_text, scale, source)
            )
            if key in values and values[key] != value:
                raise DataConflictError(
                    f"conflicting ARXML values for {key}: {values[key]!r} at "
                    f"{sources[key]} vs {value!r} at {source}"
                )
            values[key] = value
            sources[key] = source
    if not values:
        raise MissingFieldError(
            f"ARXML channel {channel_name!r} contains no recognized bitrate or BRS parameters"
        )
    return ArxmlChannelData(
        channel_name,
        int(values["nominal_bitrate"]) if "nominal_bitrate" in values else None,
        int(values["data_bitrate"]) if "data_bitrate" in values else None,
        bool(values["brs"]) if "brs" in values else None,
        tuple(sorted(sources.items())),
        files,
    )
