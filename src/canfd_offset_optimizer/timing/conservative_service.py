"""Protocol-level conservative CAN/CAN FD bus service-time estimates.

This diagnostic model is intentionally independent from optimizer weights.
It describes one normal, successful transmission, includes the normal
three-bit intermission, and excludes errors, retransmissions, arbitration
waiting, queuing and software/ECU delays.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from ..models import CAN_FD_PAYLOAD_LENGTHS, FrameProtocol


CONSERVATIVE_ESTIMATOR_VERSION = "can-conservative-service-v2"


class ConservativeEstimateStatus(str, Enum):
    """Whether a conservative service-time estimate is usable."""

    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConservativeFrameEstimate:
    """One immutable protocol-level upper-bound result.

    ``nominal_bits_upper_bound`` and ``data_bits_upper_bound`` count complete
    phase bits. For BRS-on CAN FD the two sample-point transition bits are
    represented separately by ``transition_guard_duration_us`` because their
    exact split is unavailable without bit-timing segment parameters.
    ``total_bits_upper_bound`` remains a safe legacy accounting bound, not a
    physical wire-bit count reconstructed from one payload bit pattern.
    """

    conservative_bus_service_time_us: int | None
    total_bits_upper_bound: int | None
    status: ConservativeEstimateStatus
    unavailable_reason: str | None = None
    assumptions: tuple[str, ...] = ()
    estimator_version: str = CONSERVATIVE_ESTIMATOR_VERSION
    nominal_bits_upper_bound: int | None = None
    data_bits_upper_bound: int | None = None
    effective_brs: bool | None = None
    nominal_phase_duration_us: Fraction | None = None
    data_phase_duration_us: Fraction | None = None
    transition_guard_duration_us: Fraction | None = None

    def __post_init__(self) -> None:
        if self.status is ConservativeEstimateStatus.COMPLETE:
            if (
                self.conservative_bus_service_time_us is None
                or self.total_bits_upper_bound is None
                or self.nominal_bits_upper_bound is None
                or self.data_bits_upper_bound is None
                or self.nominal_phase_duration_us is None
                or self.data_phase_duration_us is None
                or self.transition_guard_duration_us is None
                or self.conservative_bus_service_time_us <= 0
                or self.total_bits_upper_bound <= 0
                or self.nominal_bits_upper_bound <= 0
                or self.data_bits_upper_bound < 0
                or self.total_bits_upper_bound
                < self.nominal_bits_upper_bound + self.data_bits_upper_bound
                or self.nominal_phase_duration_us <= 0
                or self.data_phase_duration_us < 0
                or self.transition_guard_duration_us < 0
                or self.unavailable_reason is not None
            ):
                raise ValueError("complete conservative estimate is inconsistent")
        elif (
            self.conservative_bus_service_time_us is not None
            or self.total_bits_upper_bound is not None
            or self.nominal_bits_upper_bound is not None
            or self.data_bits_upper_bound is not None
            or self.nominal_phase_duration_us is not None
            or self.data_phase_duration_us is not None
            or self.transition_guard_duration_us is not None
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
    data_bitrate_bps: int | None = None,
    effective_brs: bool | None = None,
) -> ConservativeFrameEstimate:
    """Estimate one normal successful frame plus three-bit intermission.

    Classic CAN uses the nominal rate.  CAN FD with explicitly disabled BRS
    also uses the nominal rate for the whole frame.  CAN FD with enabled BRS
    uses a protocol-field-aware nominal/data phase decomposition and therefore
    requires both rates.  Unknown BRS is intentionally unavailable rather than
    guessed.
    """

    normalized_protocol = _normalize_protocol(protocol)
    if normalized_protocol is None:
        return _unavailable("unknown_protocol")
    if not _is_positive_int(nominal_bitrate_bps):
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

    assert nominal_bitrate_bps is not None
    if normalized_protocol is FrameProtocol.CLASSIC_CAN:
        total_bits = _classic_total_bits_upper_bound(extended, payload_bytes)
        assumptions.append("all_classic_can_bits_at_nominal_bitrate")
        return _complete_single_rate(
            total_bits,
            nominal_bitrate_bps,
            assumptions,
            effective_brs=None,
        )

    assumptions.extend(
        (
            "iso_can_fd_crc17_through_16_bytes_crc21_above_16_bytes",
            "can_fd_fixed_crc_stuff_bits_included",
        )
    )
    if effective_brs is None:
        return _unavailable("unknown_brs")
    if not isinstance(effective_brs, bool):
        return _unavailable("invalid_brs")
    if not effective_brs:
        total_bits = _can_fd_total_bits_upper_bound(extended, payload_bytes)
        assumptions.append("can_fd_brs_off_all_bits_at_nominal_bitrate")
        return _complete_single_rate(
            total_bits,
            nominal_bitrate_bps,
            assumptions,
            effective_brs=False,
        )
    if not _is_positive_int(data_bitrate_bps):
        return _unavailable(
            "missing_can_fd_data_bitrate", effective_brs=True
        )

    assert data_bitrate_bps is not None
    nominal_bits, data_bits = _can_fd_brs_on_phase_bits_upper_bound(
        extended, payload_bytes
    )
    assumptions.extend(
        (
            "can_fd_phase_aware_brs_timing",
            "brs_switch_at_brs_sample_point",
            "switch_back_at_crc_delimiter_sample_point",
            "sample_point_transition_guard_expressed_as_exact_duration",
            "phase_specific_dynamic_stuffing_upper_bounds",
        )
    )
    if data_bitrate_bps < nominal_bitrate_bps:
        assumptions.append("data_bitrate_lower_than_nominal_bitrate_unusual_configuration")
    nominal_duration_us = Fraction(
        nominal_bits * 1_000_000, nominal_bitrate_bps
    )
    data_duration_us = Fraction(data_bits * 1_000_000, data_bitrate_bps)
    # Each sample-point transition lies inside one bit. Without the network's
    # timing-segment lengths, bound each side by one complete adjacent-rate bit
    # duration instead of assigning the transition to an invented integer phase.
    transition_guard_us = 2 * (
        Fraction(1_000_000, nominal_bitrate_bps)
        + Fraction(1_000_000, data_bitrate_bps)
    )
    service_time_us = _ceil_fraction(
        nominal_duration_us + data_duration_us + transition_guard_us
    )
    return ConservativeFrameEstimate(
        service_time_us,
        nominal_bits + data_bits + 4,
        ConservativeEstimateStatus.COMPLETE,
        assumptions=tuple(assumptions),
        nominal_bits_upper_bound=nominal_bits,
        data_bits_upper_bound=data_bits,
        effective_brs=True,
        nominal_phase_duration_us=nominal_duration_us,
        data_phase_duration_us=data_duration_us,
        transition_guard_duration_us=transition_guard_us,
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
    return stuffed_dynamic_bits + _can_fd_crc_field_bits(payload_bytes) + 13


def _can_fd_brs_on_phase_bits_upper_bound(
    is_extended: bool, payload_bytes: int
) -> tuple[int, int]:
    """Return safe phase accounting bounds for ISO CAN FD with BRS enabled.

    The rate switches at the sample point of BRS and switches back at the
    sample point of the CRC delimiter.  Network timing metadata in this project
    intentionally contains rates, not sample-point segment lengths.  Each of
    those two transition bits is therefore bounded at both adjacent rates.

    Dynamic stuffing is continuous from SOF through the data field.  The prefix
    starts with known empty stuffing history; the suffix may inherit four equal
    bits, so its standalone bound uses ``ceil(N/4)``.  This may count one more
    stuff bit than a fully reconstructed payload, but remains protocol-level and
    phase safe for every positive pair of bitrates.
    """

    prefix_through_brs = 36 if is_extended else 17
    data_dynamic_bits = 5 + payload_bytes * 8  # ESI, DLC and payload.
    prefix_stuff = worst_case_dynamic_stuff_bits(prefix_through_brs)
    data_stuff_with_carry = _ceil_div(data_dynamic_bits, 4)

    # Complete nominal-rate bits exclude the BRS and CRC-delimiter transition
    # bits, whose partial-rate boundaries are represented as durations.
    nominal_bits = (prefix_through_brs - 1) + prefix_stuff + 12
    # Complete data-rate bits likewise exclude both transition bits.
    data_bits = (
        data_dynamic_bits
        + data_stuff_with_carry
        + _can_fd_crc_field_bits(payload_bytes)
    )
    return nominal_bits, data_bits


def _can_fd_crc_field_bits(payload_bytes: int) -> int:
    crc_length = 17 if payload_bytes <= 16 else 21
    # ISO CAN FD CRC field: 3-bit stuff count + parity (4 bits), a fixed stuff
    # bit before the sequence and one fixed stuff bit after each four protected
    # bits. This yields 27 bits for CRC17 and 32 bits for CRC21.
    crc_protected_bits = 4 + crc_length
    return crc_protected_bits + 1 + crc_protected_bits // 4


def _complete_single_rate(
    total_bits: int,
    nominal_bitrate_bps: int,
    assumptions: list[str],
    *,
    effective_brs: bool | None,
) -> ConservativeFrameEstimate:
    return ConservativeFrameEstimate(
        _ceil_div(total_bits * 1_000_000, nominal_bitrate_bps),
        total_bits,
        ConservativeEstimateStatus.COMPLETE,
        assumptions=tuple(assumptions),
        nominal_bits_upper_bound=total_bits,
        data_bits_upper_bound=0,
        effective_brs=effective_brs,
        nominal_phase_duration_us=Fraction(
            total_bits * 1_000_000, nominal_bitrate_bps
        ),
        data_phase_duration_us=Fraction(0),
        transition_guard_duration_us=Fraction(0),
    )


def _ceil_fraction(value: Fraction) -> int:
    return _ceil_div(value.numerator, value.denominator)


def _normalize_protocol(protocol: FrameProtocol | str | None) -> FrameProtocol | None:
    if isinstance(protocol, FrameProtocol):
        return protocol
    if isinstance(protocol, str):
        try:
            return FrameProtocol(protocol)
        except ValueError:
            return None
    return None


def _unavailable(
    reason: str, *, effective_brs: bool | None = None
) -> ConservativeFrameEstimate:
    return ConservativeFrameEstimate(
        None,
        None,
        ConservativeEstimateStatus.UNAVAILABLE,
        unavailable_reason=reason,
        effective_brs=effective_brs,
    )


def _is_positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator
