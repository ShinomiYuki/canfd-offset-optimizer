"""Final experiment fail-closed semantics and Original baseline tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from canfd_offset_optimizer.exceptions import ConfigurationError, MissingFieldError
from canfd_offset_optimizer.final_experiment import (
    FinalExperimentInput,
    evaluate_original_baseline,
    load_final_experiment_project,
)
from canfd_offset_optimizer.parsers.project_loader import load_project


FIXTURES = Path(__file__).parents[1] / "fixtures"
ROUTING_EXCEL = Path("input/网关路由配置表V02_V4.7_to_V4.8.xlsx")


def _spec(dbc_path: Path, *, sender: str | None = "VCU") -> FinalExperimentInput:
    return FinalExperimentInput(
        network_id="TEST",
        dbc_path=dbc_path,
        selected_sender=sender,
        protocol="CAN_FD",
        routing_excel_path=ROUTING_EXCEL,
        routing_target_network="TEST",
        arxml_dir=FIXTURES / "arxml",
        config_path=FIXTURES / "config" / "project.yaml",
        channel="CAN1",
    )


def test_final_experiment_requires_explicit_sender() -> None:
    with pytest.raises(ConfigurationError, match="requires explicit selected_sender"):
        _spec(FIXTURES / "dbc" / "minimal.dbc", sender=None)


def test_unknown_start_delay_fails_closed_on_final_path(tmp_path: Path) -> None:
    text = (FIXTURES / "dbc" / "minimal.dbc").read_text(encoding="utf-8")
    text = "\n".join(
        line
        for line in text.splitlines()
        if "GenMsgStartDelayTime" not in line
    )
    text += (
        '\nBA_DEF_ BO_ "GenMsgDelayTime" INT 0 10000;\n'
        'BA_DEF_DEF_ "GenMsgDelayTime" 0;\n'
        'BA_ "GenMsgDelayTime" BO_ 913 25;\n'
    )
    dbc_path = tmp_path / "delay-only.dbc"
    dbc_path.write_text(text, encoding="utf-8")

    with pytest.raises(MissingFieldError, match="GenMsgStartDelayTime"):
        load_final_experiment_project(_spec(dbc_path))


def test_original_baseline_preserves_start_delay_zero_outside_candidate_grid() -> None:
    loaded = load_project(
        FIXTURES / "dbc" / "minimal.dbc",
        FIXTURES / "arxml",
        FIXTURES / "config" / "project.yaml",
        selected_sender="VCU",
        require_original_offsets=True,
    )

    result = evaluate_original_baseline(loaded)
    assignments = {item.message_name: item.offset_us for item in result.assignments}

    assert min(loaded.config.optimization.allowed_offsets_us) == 15_000
    assert assignments["Msg391"] == 15_000
    assert assignments["Msg460Ext"] == 0
