"""! @file test_dbc_parser.py
@brief 最小脱敏 DBC 的标准/扩展 ID、周期和过滤测试。

@author 篠見由紀
"""

from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import MissingFieldError, UnsupportedMessageError
from canfd_offset_optimizer.models import FrameProtocol
from canfd_offset_optimizer.parsers.dbc_parser import parse_dbc


FIXTURE = Path(__file__).parents[1] / "fixtures" / "dbc" / "minimal.dbc"


def test_parse_minimal_dbc_normalizes_and_filters() -> None:
    result = parse_dbc(FIXTURE)
    # EventOnly 不是周期报文；RxCyclic 的发送方是 Vector__XXX，属于当前 ECU 的 RX。
    assert [message.name for message in result.messages] == ["Msg391", "Msg460Ext"]
    standard, extended = result.messages
    assert standard.can_id == 0x391
    assert standard.cycle_time_us == 20_000
    assert standard.original_offset_us == 15_000
    assert standard.sender_ecu == "VCU"
    assert extended.can_id == 0x460
    assert extended.is_extended
    assert extended.definition_index == 1


def test_tx_cyclic_message_without_cycle_has_locatable_error(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "GenMsgCycleTime" BO_ 913 20;\n', ""
    )
    path = tmp_path / "missing_cycle.dbc"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MissingFieldError, match="Msg391.*cycle time"):
        parse_dbc(path)


def test_mixed_classic_and_fd_messages_are_explicitly_rejected(
    tmp_path: Path,
) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    )
    path = tmp_path / "classic.dbc"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(UnsupportedMessageError, match=r"classic\.dbc.*mixes eligible"):
        parse_dbc(path)


def test_classic_can_periodic_tx_uses_payload_eligibility(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN_FD";',
        'BA_ "VFrameFormat" BO_ 913 "StandardCAN";',
    ).replace(
        'BA_ "VFrameFormat" BO_ 2147484768 "ExtendedCAN_FD";',
        'BA_ "VFrameFormat" BO_ 2147484768 "ExtendedCAN";',
    ).replace(
        "BO_ 2147484768 Msg460Ext: 16 VCU",
        "BO_ 2147484768 Msg460Ext: 16 Vector__XXX",
    )
    path = tmp_path / "classic_only.dbc"
    path.write_text(text, encoding="utf-8")
    result = parse_dbc(
        path,
        allowed_offsets_us=tuple(range(15_000, 100_001, 5_000)),
    )
    assert [message.name for message in result.messages] == ["Msg391"]
    assert result.messages[0].frame_protocol is FrameProtocol.CLASSIC_CAN
    assert result.messages[0].payload_bytes == 8


def test_rx_messages_are_filtered_before_tx_field_validation(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        'BA_ "GenMsgCycleTime" BO_ 400 50;\n', ""
    )
    path = tmp_path / "rx_missing_cycle.dbc"
    path.write_text(text, encoding="utf-8")
    result = parse_dbc(path)
    assert "RxCyclic" not in {message.name for message in result.messages}
