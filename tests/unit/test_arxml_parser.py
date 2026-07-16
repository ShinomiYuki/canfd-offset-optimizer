"""! @file test_arxml_parser.py
@brief namespace 无关的最小 ARXML 通道解析测试。

@author 篠見由紀
"""

from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import InputFileError
from canfd_offset_optimizer.parsers.arxml_parser import parse_arxml_directory


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "arxml"


def test_parse_channel_parameters() -> None:
    channel = parse_arxml_directory(FIXTURE_DIR, "CAN1")
    assert channel.nominal_bitrate == 500_000
    assert channel.data_bitrate == 2_000_000
    assert channel.brs is True
    assert dict(channel.field_sources)["brs"].endswith("/Can/CanControllerFdBrs")


def test_channel_parameters_can_be_resolved_through_autosar_references(
    tmp_path: Path,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "channel.arxml").write_text(
        """<?xml version="1.0"?>
<AUTOSAR xmlns="urn:test"><AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Pkg</SHORT-NAME>
<ELEMENTS><ECUC-CONTAINER-VALUE><SHORT-NAME>CAN1</SHORT-NAME>
<REFERENCE-VALUES><ECUC-REFERENCE-VALUE><DEFINITION-REF>/Defs/ControllerRef</DEFINITION-REF>
<VALUE-REF>/Pkg/Controller</VALUE-REF></ECUC-REFERENCE-VALUE></REFERENCE-VALUES>
</ECUC-CONTAINER-VALUE></ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>""",
        encoding="utf-8",
    )
    (tmp_path / "nested" / "controller.ARXML").write_text(
        """<?xml version="1.0"?>
<AUTOSAR xmlns="urn:test"><AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Pkg</SHORT-NAME>
<ELEMENTS><ECUC-CONTAINER-VALUE><SHORT-NAME>Controller</SHORT-NAME><PARAMETER-VALUES>
<P><DEFINITION-REF>/Can/CanControllerBaudrate</DEFINITION-REF><VALUE>500000</VALUE></P>
<P><DEFINITION-REF>/Can/CanControllerFdDataRate</DEFINITION-REF><VALUE>2000000</VALUE></P>
<P><DEFINITION-REF>/Can/CanControllerFdBrs</DEFINITION-REF><VALUE>true</VALUE></P>
</PARAMETER-VALUES></ECUC-CONTAINER-VALUE></ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>""",
        encoding="utf-8",
    )
    channel = parse_arxml_directory(tmp_path, "CAN1")
    assert (channel.nominal_bitrate, channel.data_bitrate, channel.brs) == (
        500_000,
        2_000_000,
        True,
    )


def test_arxml_bitrate_must_be_positive(tmp_path: Path) -> None:
    text = (FIXTURE_DIR / "minimal.arxml").read_text(encoding="utf-8").replace(
        "<VALUE>500000</VALUE>", "<VALUE>0</VALUE>", 1
    )
    (tmp_path / "invalid.arxml").write_text(text, encoding="utf-8")
    with pytest.raises(InputFileError, match="nominal_bitrate.*positive"):
        parse_arxml_directory(tmp_path, "CAN1")
