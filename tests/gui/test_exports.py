from __future__ import annotations

import csv
import json
from pathlib import Path

from canfd_offset_optimizer.gui.contracts import BatchOptimizationResult
from canfd_offset_optimizer.gui.formatting import (
    export_assignments_csv,
    export_batch_summary_csv,
    export_batch_summary_json,
    export_network_summary_json,
)
from canfd_offset_optimizer.gui.widgets.load_chart import LoadChart


def test_batch_csv_json_and_per_network_artifacts_are_readable(
    batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    output = tmp_path / "explicit_exports"
    csv_path = export_batch_summary_csv(batch_result, output / "summary.csv")
    json_path = export_batch_summary_json(batch_result, output / "summary.json")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(rows) == len(batch_result.network_results)
    assert {row["网段"] for row in rows} == {
        item.network_name for item in batch_result.network_results
    }
    assert payload["project_name"] == batch_result.project_name
    assert len(payload["networks"]) == len(batch_result.network_results)


def test_selected_network_can_be_exported_without_mutating_batch(
    qtbot, batch_result: BatchOptimizationResult, tmp_path: Path
) -> None:
    result = batch_result.network_results[0].result
    assert result is not None
    output = tmp_path / "selected_network"
    csv_path = export_assignments_csv(result, output / "offsets.csv")
    json_path = export_network_summary_json(result, output / "metrics.json")
    chart = LoadChart()
    qtbot.addWidget(chart)
    chart.resize(640, 360)
    chart.set_result(result)
    png_path = chart.export_png(output / "load_curve.png")

    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "报文,CAN ID" in csv_path.read_text(encoding="utf-8-sig")
    assert json.loads(json_path.read_text(encoding="utf-8"))["network"] == result.network_name
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
