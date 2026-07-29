"""! @file test_frame_time.py
@brief 帧格式、BRS、DLC 和近似权重模式测试。

@author 篠見由紀
"""

import pytest

from canfd_offset_optimizer.models import ChannelConfig, FrameProtocol, WeightMode
from canfd_offset_optimizer.timing.frame_time import estimate_frame_weight


def test_frame_time_is_positive_and_distinguishes_format_brs_and_payload() -> None:
    brs = ChannelConfig("CAN1", 500_000, 2_000_000, True)
    no_brs = ChannelConfig("CAN1", 500_000, 2_000_000, False)
    standard = estimate_frame_weight(8, False, brs, WeightMode.FRAME_TIME_US)
    extended = estimate_frame_weight(8, True, brs, WeightMode.FRAME_TIME_US)
    long_frame = estimate_frame_weight(64, False, brs, WeightMode.FRAME_TIME_US)
    slow = estimate_frame_weight(8, False, no_brs, WeightMode.FRAME_TIME_US)
    assert 0 < standard.frame_time_us < extended.frame_time_us
    assert standard.frame_time_us < long_frame.frame_time_us
    assert standard.frame_time_us < slow.frame_time_us


def test_approximation_modes_are_explicit() -> None:
    unknown = ChannelConfig("unspecified", None, None, None)
    payload = estimate_frame_weight(16, False, unknown, WeightMode.PAYLOAD_BYTES)
    unit = estimate_frame_weight(16, False, unknown, WeightMode.UNIT)
    assert payload.frame_time_us == 16 and payload.warning
    assert unit.frame_time_us == 1 and unit.warning


def test_classic_can_payload_length_is_the_temporary_weight() -> None:
    unknown = ChannelConfig("classic", None, None, None)
    estimate = estimate_frame_weight(
        7,
        False,
        unknown,
        WeightMode.PAYLOAD_BYTES,
        FrameProtocol.CLASSIC_CAN,
    )
    assert estimate.frame_time_us == 7
    assert 'classic_weight_model = "payload_bytes_approximation"' in (
        estimate.warning or ""
    )
    with pytest.raises(ValueError, match="not implemented"):
        estimate_frame_weight(
            7,
            False,
            unknown,
            WeightMode.FRAME_TIME_US,
            FrameProtocol.CLASSIC_CAN,
        )


def test_iso_can_fd_estimate_has_auditable_phase_bit_counts() -> None:
    brs = ChannelConfig("CAN1", 500_000, 2_000_000, True)
    estimate = estimate_frame_weight(8, False, brs, WeightMode.FRAME_TIME_US)
    assert (
        estimate.nominal_bits,
        estimate.data_bits,
        estimate.intermission_bits,
        estimate.frame_time_us,
    ) == (
        31,
        113,
        3,
        125,
    )
    assert "estimate" in (estimate.warning or "")


def test_no_brs_does_not_require_an_unused_data_bitrate_and_dlc_is_validated() -> None:
    no_brs = ChannelConfig("CAN1", 500_000, None, False)
    estimate = estimate_frame_weight(8, False, no_brs, WeightMode.FRAME_TIME_US)
    assert estimate.data_bits == 0
    assert estimate.intermission_bits == 3
    assert estimate.frame_time_us == 294
    with pytest.raises(ValueError, match="DLC"):
        estimate_frame_weight(10, False, no_brs, WeightMode.FRAME_TIME_US)


def test_zero_length_fd_frame_still_has_positive_weight_in_every_mode() -> None:
    channel = ChannelConfig("CAN1", 500_000, 2_000_000, True)
    for mode in WeightMode:
        assert estimate_frame_weight(0, False, channel, mode).frame_time_us > 0
