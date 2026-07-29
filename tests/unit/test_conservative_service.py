from __future__ import annotations

import pytest

from canfd_offset_optimizer.models import FrameProtocol
from canfd_offset_optimizer.timing.conservative_service import (
    ConservativeEstimateStatus,
    estimate_conservative_bus_service_time,
    worst_case_dynamic_stuff_bits,
)


def estimate(
    protocol: FrameProtocol,
    extended: bool,
    payload: int,
    *,
    nominal: int = 500_000,
    data: int | None = None,
    brs: bool | None = None,
):
    return estimate_conservative_bus_service_time(
        protocol=protocol,
        is_extended=extended,
        payload_bytes=payload,
        nominal_bitrate_bps=nominal,
        data_bitrate_bps=data,
        effective_brs=brs,
    )


@pytest.mark.parametrize(
    ("extended", "payload", "bitrate", "expected_bits", "expected_us"),
    (
        (False, 4, 500_000, 95, 190),
        (False, 8, 500_000, 135, 270),
        (True, 8, 500_000, 160, 320),
        (True, 8, 250_000, 160, 640),
    ),
)
def test_classic_can_known_protocol_upper_bounds_are_unchanged(
    extended: bool,
    payload: int,
    bitrate: int,
    expected_bits: int,
    expected_us: int,
) -> None:
    result = estimate(
        FrameProtocol.CLASSIC_CAN, extended, payload, nominal=bitrate
    )
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert result.total_bits_upper_bound == expected_bits
    assert result.nominal_bits_upper_bound == expected_bits
    assert result.data_bits_upper_bound == 0
    assert result.conservative_bus_service_time_us == expected_us
    assert "includes_3_bit_intermission_at_nominal_bitrate" in result.assumptions


@pytest.mark.parametrize(
    ("payload", "nominal_bits", "data_bits", "expected_us"),
    (
        (8, 32, 114, 126),
        (16, 32, 194, 166),
        (20, 32, 239, 189),
        (32, 32, 359, 249),
        (48, 32, 519, 329),
        (64, 32, 679, 409),
    ),
)
def test_standard_can_fd_brs_on_has_exact_phase_decomposition(
    payload: int, nominal_bits: int, data_bits: int, expected_us: int
) -> None:
    result = estimate(
        FrameProtocol.CAN_FD,
        False,
        payload,
        data=2_000_000,
        brs=True,
    )
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert result.nominal_bits_upper_bound == nominal_bits
    assert result.data_bits_upper_bound == data_bits
    assert result.total_bits_upper_bound == nominal_bits + data_bits + 4
    assert result.conservative_bus_service_time_us == expected_us
    assert result.effective_brs is True
    assert "can_fd_phase_aware_brs_timing" in result.assumptions
    assert (
        "sample_point_transition_guard_expressed_as_exact_duration"
        in result.assumptions
    )
    assert result.transition_guard_duration_us is not None


def test_extended_can_fd_64_byte_brs_on_phase_decomposition() -> None:
    result = estimate(
        FrameProtocol.CAN_FD,
        True,
        64,
        data=2_000_000,
        brs=True,
    )
    assert result.nominal_bits_upper_bound == 55
    assert result.data_bits_upper_bound == 679
    assert result.conservative_bus_service_time_us == 455


@pytest.mark.parametrize(
    ("payload", "expected_bits", "expected_us"),
    (
        (8, 147, 294),
        (16, 227, 454),
        (20, 272, 544),
        (32, 392, 784),
        (48, 552, 1104),
        (64, 712, 1424),
    ),
)
def test_can_fd_brs_off_legitimately_uses_nominal_rate_for_whole_frame(
    payload: int, expected_bits: int, expected_us: int
) -> None:
    result = estimate(FrameProtocol.CAN_FD, False, payload, brs=False)
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert result.total_bits_upper_bound == expected_bits
    assert result.nominal_bits_upper_bound == expected_bits
    assert result.data_bits_upper_bound == 0
    assert result.conservative_bus_service_time_us == expected_us
    assert result.effective_brs is False


def test_crc17_crc21_boundary_and_fixed_crc_stuff_are_structural() -> None:
    at_16 = estimate(
        FrameProtocol.CAN_FD, False, 16, data=2_000_000, brs=True
    )
    at_20 = estimate(
        FrameProtocol.CAN_FD, False, 20, data=2_000_000, brs=True
    )
    assert at_16.data_bits_upper_bound == 194
    assert at_20.data_bits_upper_bound == 239
    assert "can_fd_fixed_crc_stuff_bits_included" in at_16.assumptions


def test_dynamic_stuff_upper_bound_is_not_empirical_multiplier() -> None:
    assert worst_case_dynamic_stuff_bits(34) == 8
    assert worst_case_dynamic_stuff_bits(98) == 24
    assert worst_case_dynamic_stuff_bits(534) == 133


def test_data_bitrate_changes_only_data_phase_duration_and_final_ceil() -> None:
    at_1m = estimate(
        FrameProtocol.CAN_FD, False, 8, data=1_000_000, brs=True
    )
    at_2m = estimate(
        FrameProtocol.CAN_FD, False, 8, data=2_000_000, brs=True
    )
    at_5m = estimate(
        FrameProtocol.CAN_FD, False, 8, data=5_000_000, brs=True
    )
    assert at_1m.nominal_bits_upper_bound == at_2m.nominal_bits_upper_bound
    assert at_1m.data_bits_upper_bound == at_2m.data_bits_upper_bound
    assert (
        at_1m.conservative_bus_service_time_us,
        at_2m.conservative_bus_service_time_us,
        at_5m.conservative_bus_service_time_us,
    ) == (184, 126, 92)


def test_brs_on_is_faster_than_same_frame_brs_off() -> None:
    on = estimate(
        FrameProtocol.CAN_FD, False, 48, data=2_000_000, brs=True
    )
    off = estimate(FrameProtocol.CAN_FD, False, 48, brs=False)
    assert on.conservative_bus_service_time_us == 329
    assert off.conservative_bus_service_time_us == 1104
    assert on.conservative_bus_service_time_us < off.conservative_bus_service_time_us


def test_data_rate_below_nominal_is_kept_and_reported_as_unusual() -> None:
    result = estimate(
        FrameProtocol.CAN_FD,
        False,
        8,
        nominal=500_000,
        data=250_000,
        brs=True,
    )
    assert result.status is ConservativeEstimateStatus.COMPLETE
    assert result.conservative_bus_service_time_us == 532
    assert "data_bitrate_lower_than_nominal_bitrate_unusual_configuration" in (
        result.assumptions
    )


@pytest.mark.parametrize(
    ("protocol", "extended", "payload", "nominal", "data", "brs", "reason"),
    (
        (None, False, 8, 500_000, None, None, "unknown_protocol"),
        (FrameProtocol.CAN_FD, False, 8, None, 2_000_000, True, "missing_nominal_bitrate"),
        (FrameProtocol.CAN_FD, False, 10, 500_000, 2_000_000, True, "invalid_payload_length"),
        (FrameProtocol.CLASSIC_CAN, False, 9, 500_000, None, None, "invalid_payload_length"),
        (FrameProtocol.CAN_FD, False, 8, 500_000, None, None, "unknown_brs"),
        (
            FrameProtocol.CAN_FD,
            False,
            8,
            500_000,
            None,
            True,
            "missing_can_fd_data_bitrate",
        ),
    ),
)
def test_invalid_or_missing_metadata_is_unavailable_not_zero(
    protocol: FrameProtocol | None,
    extended: bool,
    payload: int,
    nominal: int | None,
    data: int | None,
    brs: bool | None,
    reason: str,
) -> None:
    result = estimate_conservative_bus_service_time(
        protocol=protocol,
        is_extended=extended,
        payload_bytes=payload,
        nominal_bitrate_bps=nominal,
        data_bitrate_bps=data,
        effective_brs=brs,
    )
    assert result.status is ConservativeEstimateStatus.UNAVAILABLE
    assert result.conservative_bus_service_time_us is None
    assert result.total_bits_upper_bound is None
    assert result.nominal_bits_upper_bound is None
    assert result.data_bits_upper_bound is None
    assert result.unavailable_reason == reason
