"""Protocol-level conservative CAN/CAN FD bus service-time estimates.

This diagnostic model is intentionally independent from optimizer weights.
It describes one normal, successful transmission, includes the normal
three-bit intermission, and excludes errors, retransmissions, arbitration
waiting, queuing and software/ECU delays.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..models import CAN_FD_PAYLOAD_LENGTHS, FrameProtocol


CONSERVATIVE_ESTIMATOR_VERSION = "can-conservative-service-v1"


class ConservativeEstimateStatus(str, Enum):
    """Whether a conservative service-time estimate is usable."""

    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConservativeFrameEstimate:
    """One immutable protocol-level upper-bound result."""

    conservative_bus_service_time_us: int | None
    total_bits_upper_bound: int | None
    status: ConservativeEstimateStatus
    unavailable_reason: str | None = None
    assumptions: tuple[str, ...] = ()
    estimator_version: str = CONSERVATIVE_ESTIMATOR_VERSION

    def __post_init__(self) -> None:
        if self.status is ConservativeEstimateStatus.COMPLETE:
            if (
                self.conservative_bus_service_time_us is None
                or self.total_bits_upper_bound is None
                or self.conservative_bus_service_time_us <= 0
                or self.total_bits_upper_bound <= 0
                or self.unavailable_reason is not None
            ):
                raise ValueError("complete conservative estimate is inconsistent")
        elif (
            self.conservative_bus_service_time_us is not None
            or self.total_bits_upper_bound is not None
            or not self.unavailable_reason
        ):
            raise ValueError("unavailable conservative estimate is inconsistent")


def worst_case_dynamic_stuff_bits(bit_count: int) -> int:
    """Return the ISO CAN worst-case dynamic stuff-bit upper bound."""

    if isinstance(bit_count, bool) or not isinstance(bit_count, int) or bit_count <= 0:
        raise ValueError("dynamic stuffing region must contain a positive bit count")
    return (bit_count - 1) // 4


def estimate_conservative_bus_service_time(
    *,
    protocol: FrameProtocol | str | None,
    is_extended: bool | None,
    payload_bytes: int | None,
    nominal_bitrate_bps: int | None,
) -> ConservativeFrameEstimate:
    """Estimate one normal successful frame plus three-bit intermission.

    For CAN FD the entire frame is deliberately timed at nominal bitrate. This
    does not model BRS acceleration and is conservative under the explicit
    assumption that data-phase bitrate is not lower than nominal bitrate.
    """

    normalized_protocol = _normalize_protocol(protocol)
    if normalized_protocol is None:
        return _unavailable("unknown_protocol")
    if (
        nominal_bitrate_bps is None
        or isinstance(nominal_bitrate_bps, bool)
        or not isinstance(nominal_bitrate_bps, int)
        or nominal_bitrate_bps <= 0
    ):
        return _unavailable("missing_nominal_bitrate")
    if isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int):
        return _unavailable("invalid_payload_length")
    valid_lengths = (
        frozenset(range(9))
        if normalized_protocol is FrameProtocol.CLASSIC_CAN
        else CAN_FD_PAYLOAD_LENGTHS
    )
    if payload_bytes not in valid_lengths:
        return _unavailable("invalid_payload_length")

    assumptions = [
        "protocol_level_worst_case_dynamic_stuffing",
        "normal_successful_transmission_without_errors_or_retransmissions",
        "includes_3_bit_intermission_at_nominal_bitrate",
    ]
    extended = is_extended
    if extended is None:
        extended = True
        assumptions.append("extended_frame_assumed_for_missing_format")
    elif not isinstance(extended, bool):
        return _unavailable("invalid_frame_metadata")

    if normalized_protocol is FrameProtocol.CLASSIC_CAN:
        total_bits = _classic_total_bits_upper_bound(extended, payload_bytes)
        assumptions.append("all_classic_can_bits_at_nominal_bitrate")
    else:
        total_bits = _can_fd_total_bits_upper_bound(extended, payload_bytes)
        assumptions.extend(
            (
                "iso_can_fd_crc17_through_16_bytes_crc21_above_16_bytes",
                "can_fd_fixed_crc_stuff_bits_included",
                "all_can_fd_bits_at_nominal_bitrate",
                "data_phase_bitrate_assumed_not_lower_than_nominal_bitrate",
            )
        )
    service_time_us = _ceil_div(total_bits * 1_000_000, nominal_bitrate_bps)
    return ConservativeFrameEstimate(
        service_time_us,
        total_bits,
        ConservativeEstimateStatus.COMPLETE,
        assumptions=tuple(assumptions),
    )


def _classic_total_bits_upper_bound(is_extended: bool, payload_bytes: int) -> int:
    # SOF through the 15-bit CRC sequence is subject to dynamic bit stuffing.
    # Standard: 1 SOF + 12 arbitration + 6 control + data + 15 CRC = 34 + data.
    # Extended: 1 SOF + 32 arbitration + 6 control + data + 15 CRC = 54 + data.
    dynamic_bits = (54 if is_extended else 34) + payload_bytes * 8
    # CRC delimiter + ACK slot/delimiter + EOF = 10 fixed bits; the service-time
    # definition additionally includes the normal 3-bit intermission.
    return dynamic_bits + worst_case_dynamic_stuff_bits(dynamic_bits) + 13


def _can_fd_total_bits_upper_bound(is_extended: bool, payload_bytes: int) -> int:
    # ISO CAN FD dynamic stuffing runs from SOF through the data field.
    # Standard header through DLC is 22 bits; extended is 41 bits.
    dynamic_bits = (41 if is_extended else 22) + payload_bytes * 8
    stuffed_dynamic_bits = dynamic_bits + worst_case_dynamic_stuff_bits(dynamic_bits)

    crc_length = 17 if payload_bytes <= 16 else 21
    # ISO CAN FD CRC field: 3-bit stuff count + parity (4 bits), a fixed stuff
    # bit before the sequence and one fixed stuff bit after each four protected
    # bits. This yields 27 bits for CRC17 and 32 bits for CRC21.
    crc_protected_bits = 4 + crc_length
    crc_field_bits = crc_protected_bits + 1 + crc_protected_bits // 4

    # CRC delimiter + ACK slot/delimiter + EOF = 10 bits, plus 3-bit intermission.
    return stuffed_dynamic_bits + crc_field_bits + 13


def _normalize_protocol(protocol: FrameProtocol | str | None) -> FrameProtocol | None:
    if isinstance(protocol, FrameProtocol):
        return protocol
    if isinstance(protocol, str):
        try:
            return FrameProtocol(protocol)
        except ValueError:
            return None
    return None


def _unavailable(reason: str) -> ConservativeFrameEstimate:
    return ConservativeFrameEstimate(
        None,
        None,
        ConservativeEstimateStatus.UNAVAILABLE,
        unavailable_reason=reason,
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator
