"""! @file frame_time.py
@brief 计算可审计的整数 CAN FD 帧时间或显式近似权重。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import (
    CAN_FD_PAYLOAD_LENGTHS,
    ChannelConfig,
    FrameProtocol,
    WeightMode,
)


@dataclass(frozen=True, slots=True)
class FrameTimeEstimate:
    """! @brief 权重、模式与保守位数分解。"""

    frame_time_us: int
    mode: WeightMode
    nominal_bits: int
    data_bits: int
    intermission_bits: int
    warning: str | None = None


def _stuffed(bits: int) -> int:
    """! @brief 对适用动态位填充的字段取每连续 4 位后的保守上界。"""
    return bits + (bits - 1) // 4 if bits else 0


def estimate_frame_weight(
    payload_bytes: int,
    is_extended: bool,
    channel: ChannelConfig,
    mode: WeightMode,
    frame_protocol: FrameProtocol = FrameProtocol.CAN_FD,
) -> FrameTimeEstimate:
    """! @brief 按显式模式返回正整数权重。

    @details
    `frame_time_us` 是 ISO CAN FD 的保守上界估计：动态填充按最坏上界计算，
    CRC 字段包含 stuff-count、parity 和固定填充位；包含 3 个 nominal-rate
    intermission bits。
    BRS 开启时在 BRS 之后使用 data bitrate，并把尾段保守地计入 nominal phase。
    该模式不声称是逐位精确仿真。
    """
    valid_lengths = (
        frozenset(range(9))
        if frame_protocol is FrameProtocol.CLASSIC_CAN
        else CAN_FD_PAYLOAD_LENGTHS
    )
    if payload_bytes not in valid_lengths:
        if frame_protocol is FrameProtocol.CAN_FD:
            raise ValueError(
                f"payload_bytes={payload_bytes} is not representable by a CAN FD DLC"
            )
        raise ValueError(
            f"payload_bytes={payload_bytes} is invalid for {frame_protocol.value}"
        )
    if mode is WeightMode.UNIT:
        return FrameTimeEstimate(1, mode, 0, 0, 0, "unit weight is an approximation")
    if mode is WeightMode.PAYLOAD_BYTES:
        return FrameTimeEstimate(
            max(1, payload_bytes),
            mode,
            0,
            0,
            0,
            (
                "classic_weight_model = \"payload_bytes_approximation\"; "
                "relative balancing only; no physical bus-load interpretation"
                if frame_protocol is FrameProtocol.CLASSIC_CAN
                else "payload_bytes weight ignores CAN FD protocol overhead and bitrate"
            ),
        )
    if frame_protocol is FrameProtocol.CLASSIC_CAN:
        raise ValueError(
            "precise Classic CAN frame_time_us is not implemented; use payload_bytes"
        )
    if channel.nominal_bitrate is None or channel.brs is None:
        raise ValueError("frame_time_us mode requires nominal bitrate and BRS")
    if channel.brs and channel.data_bitrate is None:
        raise ValueError("frame_time_us mode with BRS requires data bitrate")

    # SOF through BRS has 17 bits in FBFF and 36 bits in FEFF. CRC delimiter,
    # ACK field and EOF contribute another ten non-stuffed bits.
    prefix_bits = 36 if is_extended else 17
    tail_bits = 10
    crc_bits = 21 if payload_bytes > 16 else 17
    dynamic_data_bits = 5 + payload_bytes * 8  # ESI, DLC and payload.
    # CRC field: leading fixed bit, four stuff-count/parity bits, CRC sequence,
    # and one fixed bit after each complete group of four protected bits.
    crc_protected_bits = 4 + crc_bits
    crc_field_bits = crc_protected_bits + 1 + crc_protected_bits // 4
    intermission_bits = 3
    if not channel.brs:
        nominal_bits = (
            _stuffed(prefix_bits + dynamic_data_bits) + crc_field_bits + tail_bits
        )
        data_bits = 0
        frame_time_us = (
            (nominal_bits + intermission_bits) * 1_000_000
            + channel.nominal_bitrate
            - 1
        ) // channel.nominal_bitrate
    else:
        nominal_bits = _stuffed(prefix_bits) + tail_bits
        data_bits = _stuffed(dynamic_data_bits) + crc_field_bits
        assert channel.data_bitrate is not None
        nominal_us = (
            (nominal_bits + intermission_bits) * 1_000_000
            + channel.nominal_bitrate
            - 1
        ) // channel.nominal_bitrate
        data_us = (
            data_bits * 1_000_000 + channel.data_bitrate - 1
        ) // channel.data_bitrate
        frame_time_us = nominal_us + data_us
    return FrameTimeEstimate(
        max(1, frame_time_us),
        mode,
        nominal_bits,
        data_bits,
        intermission_bits,
        "frame_time_us is a conservative ISO CAN FD estimate including 3 nominal-rate "
        "intermission bits; "
        "not an exact stuffed-bit simulation",
    )
