from __future__ import annotations

import json
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import GuiOptimizationResult
from canfd_offset_optimizer.gui.formatting import export_assignments_csv, export_summary_json
from canfd_offset_optimizer.gui.widgets.load_chart import LoadChart


def test_csv_json_and_png_exports_are_explicit_user_outputs(
    qtbot, gui_result: GuiOptimizationResult, tmp_path: Path
) -> None:
    output = tmp_path / "user-output"
    csv_path = export_assignments_csv(gui_result, output / "offsets.csv")
    json_path = export_summary_json(gui_result, output / "summary.json")
    chart = LoadChart()
    qtbot.addWidget(chart)
    chart.resize(640, 360)
    chart.set_result(gui_result)
    png_path = chart.export_png(output / "load_curve.png")

    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "报文,CAN ID" in csv_path.read_text(encoding="utf-8-sig")
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary["network"] == gui_result.network_name
    assert summary["original_metrics"]["Zss"] == gui_result.original_metrics.zss
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not (tmp_path / "output" / "diagnostics").exists()
