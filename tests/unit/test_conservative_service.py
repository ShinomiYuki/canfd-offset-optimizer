from __future__ import annotations

import pytest

from canfd_offset_optimizer.models import FrameProtocol
from canfd_offset_optimizer.timing.conservative_service import (
    ConservativeEstimateStatus,
    estimate_conservative_bus_service_time,
    worst_case_dynamic_stuff_bits,
)


def estimate(protocol: FrameProtocol, extended: bool, payload: int, bitrate: int = 500_000):
    return estimate_conservative_bus_service_time(
        protocol=protocol,
        is_extended=extended,
        payload_bytes=payload,
        nominal_bitrate_bps=bitrate,
    )


@pytest.mark.parametrize(
    ("extended", "payload", "expected_bits", "expected_us"),
    (
        (False, 0, 55, 110),
        (False, 8, 135, 270),
        (True, 8, 160, 320),
    ),
)
def test_classic_can_known_protocol_upper_bounds(
    extended: bool, payload: int, expected_bits: int, expected_us: int
) -> None:
    result = estimate(FrameProtocol.CLASSIC_CAN, extended, payload)
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert result.total_bits_upper_bound == expected_bits
    assert result.conservative_bus_service_time_us == expected_us
    assert "includes_3_bit_intermission_at_nominal_bitrate" in result.assumptions


@pytest.mark.parametrize(
    ("payload", "expected_bits"),
    ((8, 147), (12, 187), (16, 227), (20, 272), (64, 712)),
)
def test_can_fd_standard_known_protocol_upper_bounds(
    payload: int, expected_bits: int
) -> None:
    result = estimate(FrameProtocol.CAN_FD, False, payload)
    assert result.total_bits_upper_bound == expected_bits
    assert result.conservative_bus_service_time_us == expected_bits * 2


def test_can_fd_extended_64_byte_upper_bound() -> None:
    result = estimate(FrameProtocol.CAN_FD, True, 64)
    assert result.total_bits_upper_bound == 736
    assert result.conservative_bus_service_time_us == 1472


def test_crc17_crc21_boundary_and_fixed_crc_stuff_are_structural() -> None:
    at_16 = estimate(FrameProtocol.CAN_FD, False, 16)
    at_20 = estimate(FrameProtocol.CAN_FD, False, 20)
    assert at_16.total_bits_upper_bound == 227
    assert at_20.total_bits_upper_bound == 272
    assert "can_fd_fixed_crc_stuff_bits_included" in at_16.assumptions


def test_dynamic_stuff_upper_bound_is_not_empirical_multiplier() -> None:
    assert worst_case_dynamic_stuff_bits(34) == 8
    assert worst_case_dynamic_stuff_bits(98) == 24
    assert worst_case_dynamic_stuff_bits(534) == 133


def test_bitrate_halving_only_changes_conservative_time_and_uses_ceil() -> None:
    at_500k = estimate(FrameProtocol.CAN_FD, False, 8, 500_000)
    at_250k = estimate(FrameProtocol.CAN_FD, False, 8, 250_000)
    awkward = estimate(FrameProtocol.CLASSIC_CAN, False, 0, 333_333)
    assert at_250k.total_bits_upper_bound == at_500k.total_bits_upper_bound
    assert at_250k.conservative_bus_service_time_us == 2 * at_500k.conservative_bus_service_time_us
    assert awkward.total_bits_upper_bound == 55
    assert awkward.conservative_bus_service_time_us == 166


def test_can_fd_needs_no_data_bitrate_brs_or_arxml() -> None:
    result = estimate(FrameProtocol.CAN_FD, False, 64)
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert "all_can_fd_bits_at_nominal_bitrate" in result.assumptions
    assert "data_phase_bitrate_assumed_not_lower_than_nominal_bitrate" in result.assumptions


@pytest.mark.parametrize(
    ("protocol", "extended", "payload", "bitrate", "reason"),
    (
        (None, False, 8, 500_000, "unknown_protocol"),
        (FrameProtocol.CAN_FD, False, 8, None, "missing_nominal_bitrate"),
        (FrameProtocol.CAN_FD, False, 10, 500_000, "invalid_payload_length"),
        (FrameProtocol.CLASSIC_CAN, False, 9, 500_000, "invalid_payload_length"),
        (FrameProtocol.CAN_FD, False, 8, 0, "missing_nominal_bitrate"),
    ),
)
def test_invalid_or_missing_metadata_is_unavailable_not_zero(
    protocol: FrameProtocol | None,
    extended: bool,
    payload: int,
    bitrate: int | None,
    reason: str,
) -> None:
    result = estimate_conservative_bus_service_time(
        protocol=protocol,
        is_extended=extended,
        payload_bytes=payload,
        nominal_bitrate_bps=bitrate,
    )
    assert result.status is ConservativeEstimateStatus.UNAVAILABLE
    assert result.conservative_bus_service_time_us is None
    assert result.total_bits_upper_bound is None
    assert result.unavailable_reason == reason
