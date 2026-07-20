"""! @file dbc_parser.py
@brief 使用 cantools 将 DBC 周期报文转换为库无关中间模型。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import importlib
from pathlib import Path
import re
from typing import Any, cast

from ..exceptions import InputFileError, MissingFieldError, UnsupportedMessageError
from ..models import CAN_FD_PAYLOAD_LENGTHS, FrameProtocol


DBC_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "cycle_time": ("GenMsgCycleTime", "CycleTime", "MsgCycleTime"),
    "start_delay": ("GenMsgStartDelayTime", "GenMsgDelayTime", "MsgStartDelayTime"),
    "send_type": ("GenMsgSendType", "SendType", "MsgSendType"),
    "frame_format": ("VFrameFormat", "FrameFormat", "BusType"),
}


@dataclass(frozen=True, slots=True)
class ParsedDbcMessage:
    """! @brief DBC 字段的规范化、未加权中间表示。"""

    name: str
    can_id: int
    is_extended: bool
    payload_bytes: int
    sender_ecu: str
    cycle_time_us: int
    original_offset_us: int | None
    definition_index: int
    field_sources: tuple[tuple[str, str], ...]
    frame_protocol: FrameProtocol = FrameProtocol.CAN_FD


@dataclass(frozen=True, slots=True)
class DbcParseResult:
    """! @brief DBC 周期报文与解析诊断。"""

    messages: tuple[ParsedDbcMessage, ...]
    warnings: tuple[str, ...] = ()


def _attribute_value(
    message: Any, names: tuple[str, ...]
) -> tuple[object | None, str | None]:
    dbc_specifics = getattr(message, "dbc", None)
    attributes = getattr(dbc_specifics, "attributes", {})
    for name in names:
        attribute = attributes.get(name)
        if attribute is not None:
            return cast(object, getattr(attribute, "value", attribute)), name
    return None, None


def _milliseconds_to_us(value: object) -> int | None:
    """! @brief 无损地把 DBC 毫秒数转换为整数微秒。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        microseconds = Decimal(str(value)) * 1_000
    except InvalidOperation:
        return None
    if not microseconds.is_finite() or microseconds != microseconds.to_integral_value():
        return None
    result = int(microseconds)
    return result if result >= 0 else None


def _cycle_us(message: Any) -> tuple[int | None, str | None]:
    direct = getattr(message, "cycle_time", None)
    if direct is not None:
        converted = _milliseconds_to_us(direct)
        return (converted if converted and converted > 0 else None), "cantools.Message.cycle_time"
    value, attribute_name = _attribute_value(message, DBC_ATTRIBUTES["cycle_time"])
    converted = _milliseconds_to_us(value) if value is not None else None
    return (
        converted if converted and converted > 0 else None,
        attribute_name,
    )


def _is_declared_periodic(message: Any) -> bool:
    value, _ = _attribute_value(message, DBC_ATTRIBUTES["send_type"])
    if value is None:
        return False
    normalized = str(value).lower().replace("-", "").replace("_", "")
    return any(token in normalized for token in ("cyclic", "periodic", "cycle"))


def _is_explicitly_event_driven(message: Any) -> bool:
    value, _ = _attribute_value(message, DBC_ATTRIBUTES["send_type"])
    if value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Vector GenMsgSendType commonly uses 0=cyclic and 1=event.
        return int(value) != 0
    normalized = str(value).lower().replace("-", "").replace("_", "")
    return any(token in normalized for token in ("event", "spontaneous", "onchange"))


def _is_excluded_traffic_class(message: Any) -> bool:
    """Exclude diagnostic, NM and calibration traffic without network-name rules."""
    name = str(getattr(message, "name", ""))
    words = tuple(part for part in re.split(r"[^A-Za-z0-9]+", name.upper()) if part)
    upper = name.upper()
    return (
        "DIAG" in upper
        or "XCP" in upper
        or "CALIBRATION" in upper
        or any(word == "NM" or word.startswith("NM") for word in words)
    )


def _is_fd_message(message: Any) -> bool:
    """! @brief 优先使用集中映射的格式属性，回退到 cantools 帧标志。"""
    value, _ = _attribute_value(message, DBC_ATTRIBUTES["frame_format"])
    if value is not None:
        normalized = str(value).lower().replace("-", "").replace("_", "")
        if "fd" in normalized:
            return True
        if "can" in normalized:
            return False
    return bool(getattr(message, "is_fd", False))


def _tx_sender(message: Any) -> str | None:
    """! @brief 返回第一个具体发送节点；外部占位发送方返回 None。

    @details
    Vector DBC 常用 `Vector__XXX` 作为外部发送方占位符；这类报文是当前 ECU
    的 RX 报文。具体发送节点不依赖 BU_ 列表是否完整。
    """
    senders = tuple(str(sender) for sender in (getattr(message, "senders", ()) or ()))
    concrete = tuple(sender for sender in senders if sender and sender != "Vector__XXX")
    if not concrete:
        return None
    return concrete[0]


def parse_dbc(
    path: Path,
    *,
    allowed_offsets_us: tuple[int, ...] | None = None,
) -> DbcParseResult:
    """! @brief 解析一个 DBC，过滤事件报文并保留稳定定义顺序。

    @raises MissingFieldError 声明为周期的报文缺少必要字段时抛出。
    @raises InputFileError 文件不存在或 cantools 无法解析时抛出。
    """
    path = path.resolve()
    if not path.is_file():
        raise InputFileError(f"DBC file does not exist: {path}")
    cantools = importlib.import_module("cantools")
    try:
        database = cantools.database.load_file(str(path), strict=False)
    except Exception as exc:  # 外部解析库可能按格式失败点抛出多种异常，统一转为领域错误。
        raise InputFileError(f"cannot parse DBC {path}: {exc}") from exc
    parsed: list[ParsedDbcMessage] = []
    warnings: list[str] = []
    for definition_index, message in enumerate(database.messages):
        sender = _tx_sender(message)
        # cantools represents the reserved Vector__XXX sender as an empty list.
        if sender is None:
            continue
        cycle_us, cycle_source = _cycle_us(message)
        if cycle_us is None:
            if _is_declared_periodic(message):
                raise MissingFieldError(
                    f"{path}: message {message.name} is cyclic but has no valid cycle time"
                )
            continue
        frame_protocol = (
            FrameProtocol.CAN_FD
            if _is_fd_message(message)
            else FrameProtocol.CLASSIC_CAN
        )
        length = getattr(message, "length", None)
        valid_lengths = (
            CAN_FD_PAYLOAD_LENGTHS
            if frame_protocol is FrameProtocol.CAN_FD
            else frozenset(range(9))
        )
        if (
            isinstance(length, bool)
            or not isinstance(length, int)
            or length not in valid_lengths
        ):
            raise MissingFieldError(
                f"{path}: message {message.name} has payload length {length!r} "
                f"that is invalid for {frame_protocol.value}"
            )
        is_extended = bool(getattr(message, "is_extended_frame", False))
        raw_id = int(message.frame_id)
        # cantools normally removes DBC's bit-31 extended marker. Accept that marker
        # defensively, but reject every other out-of-range bit instead of masking it.
        can_id = raw_id & 0x1FFFFFFF if is_extended and raw_id & 0x80000000 else raw_id
        maximum = 0x1FFFFFFF if is_extended else 0x7FF
        allowed_raw = can_id | (0x80000000 if is_extended and raw_id & 0x80000000 else 0)
        if not 0 <= can_id <= maximum or raw_id != allowed_raw:
            raise UnsupportedMessageError(
                f"{path}: message {message.name} has unsupported CAN ID 0x{raw_id:X}"
            )
        original, original_source = _attribute_value(
            message, DBC_ATTRIBUTES["start_delay"]
        )
        original_offset_us = None
        if original is not None:
            original_offset_us = _milliseconds_to_us(original)
            if original_offset_us is None:
                raise MissingFieldError(
                    f"{path}: message {message.name} has invalid original Offset"
                )
        if frame_protocol is FrameProtocol.CLASSIC_CAN and original_offset_us is None:
            rendered = (
                "missing"
                if original_offset_us is None
                else f"{original_offset_us / 1000:g} ms"
            )
            warnings.append(
                f"Classic CAN message {message.name} was excluded: original Offset "
                f"{rendered}; Classic CAN requires a real baseline Offset"
            )
            continue
        if frame_protocol is FrameProtocol.CLASSIC_CAN and (
            _is_explicitly_event_driven(message)
            or _is_excluded_traffic_class(message)
        ):
            warnings.append(
                f"Classic CAN message {message.name} was excluded as "
                "event/diagnostic/NM traffic"
            )
            continue
        source_prefix = f"{path}:{message.name}"
        field_sources = [
            ("can_id", f"{source_prefix}:BO_"),
            ("frame_format", f"{source_prefix}:cantools frame flags"),
            ("cycle_time_us", f"{source_prefix}:{cycle_source}"),
            ("payload_bytes", f"{source_prefix}:BO_"),
            ("sender_ecu", f"{source_prefix}:BO_"),
        ]
        if original_source is not None:
            field_sources.append(
                ("original_offset_us", f"{source_prefix}:{original_source}")
            )
        parsed.append(
            ParsedDbcMessage(
                name=str(message.name),
                can_id=can_id,
                is_extended=is_extended,
                payload_bytes=length,
                sender_ecu=sender,
                cycle_time_us=cycle_us,
                original_offset_us=original_offset_us,
                definition_index=definition_index,
                field_sources=tuple(field_sources),
                frame_protocol=frame_protocol,
            )
        )
    if not parsed:
        raise InputFileError(f"{path}: no eligible periodic TX messages were found")
    protocols = {message.frame_protocol for message in parsed}
    if len(protocols) != 1:
        raise UnsupportedMessageError(
            f"{path}: one physical network mixes eligible Classic CAN and CAN FD "
            "periodic TX messages; Byte and microsecond weights cannot be mixed"
        )
    return DbcParseResult(tuple(parsed), tuple(warnings))
