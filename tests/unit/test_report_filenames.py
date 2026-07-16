"""! @file test_report_filenames.py
@brief 报告网段前缀和全网段逐报文汇总测试。
"""

from __future__ import annotations

import csv
from pathlib import Path

from canfd_offset_optimizer.reporting.filenames import (
    infer_report_prefix,
    prefixed_report_name,
)
from canfd_offset_optimizer.reporting.weight_mode_writer import (
    write_all_network_offsets_report,
)


def test_report_prefix_prefers_network_name_in_dbc_filename() -> None:
    dbc = Path("E0X_PT_Car FLZCU_VCU_SU Message list V1.2.dbc")
    assert infer_report_prefix(dbc, "fallback") == "SU"
    assert prefixed_report_name("startup_congestion_heatmap.png", "SU") == (
        "SU_startup_congestion_heatmap.png"
    )


def test_all_network_message_table_is_sorted_and_uses_chinese_fields(
    tmp_path: Path,
) -> None:
    fields = [
        "报文名称",
        "CAN_ID",
        "周期(ms)",
        "载荷长度(Byte)",
        "保守帧占用时间(μs)",
        "DBC原始Offset(ms)",
        "payload_bytes_GCLS_Offset(ms)",
        "frame_time_us_GCLS_Offset(ms)",
        "是否变化",
    ]
    for network in ("SU", "DA"):
        results = tmp_path / network / "results"
        results.mkdir(parents=True)
        (results / "weight_mode_summary.json").write_text("{}", encoding="utf-8")
        with (results / f"{network}_offsets_weight_mode_comparison.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "报文名称": f"{network}_Message",
                    "CAN_ID": "0x100",
                    "周期(ms)": "20",
                    "载荷长度(Byte)": "8",
                    "保守帧占用时间(μs)": "125",
                    "DBC原始Offset(ms)": "15",
                    "payload_bytes_GCLS_Offset(ms)": "20",
                    "frame_time_us_GCLS_Offset(ms)": "25",
                    "是否变化": "True",
                }
            )
    path = write_all_network_offsets_report(tmp_path)
    assert path.name == "ALL_offsets_weight_mode_comparison.csv"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert reader.fieldnames == ["网段", *fields[:-1]]
    assert [row["网段"] for row in rows] == ["DA", "SU"]
