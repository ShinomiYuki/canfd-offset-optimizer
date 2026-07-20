from __future__ import annotations

import pytest

from canfd_offset_optimizer.config import (
    OffsetSearchConfig,
    OptimizationConfig,
    RestartPolicy,
)
from canfd_offset_optimizer.exceptions import ConfigurationError
from canfd_offset_optimizer.models import CanMessage
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.timeline.slot_map import build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


@pytest.mark.parametrize(
    ("minimum", "maximum", "step", "expected"),
    (
        (15, 100, 5, tuple(range(15, 101, 5))),
        (0, 100, 5, tuple(range(0, 101, 5))),
        (0, 200, 10, tuple(range(0, 201, 10))),
        (15, 100, 10, tuple(range(15, 96, 10))),
        (15, 102, 10, tuple(range(15, 96, 10))),
        (20, 20, 7, (20,)),
        (0, 0, 5, (0,)),
    ),
)
def test_offset_candidates_are_generated_without_rounding_or_appending_max(
    minimum: int, maximum: int, step: int, expected: tuple[int, ...]
) -> None:
    config = OffsetSearchConfig(minimum, maximum, step)
    assert config.candidate_offsets_ms == expected
    assert config.effective_max_offset_ms == expected[-1]
    assert config.candidate_count == len(expected)


@pytest.mark.parametrize("values", ((-1, 10, 5), (11, 10, 5), (0, 10, 0)))
def test_offset_search_rejects_invalid_values(values: tuple[int, int, int]) -> None:
    with pytest.raises(ConfigurationError):
        OffsetSearchConfig(*values)


def test_optimization_config_delegates_to_public_offset_search_config() -> None:
    config = OptimizationConfig(
        offset_min_us=15_000, offset_max_us=102_000, offset_step_us=10_000
    )
    assert config.allowed_offsets_us == tuple(range(15_000, 96_000, 10_000))
    assert config.offset_search.as_metadata() == {
        "min_offset_ms": 15,
        "max_offset_ms": 102,
        "offset_step_ms": 10,
        "effective_max_offset_ms": 95,
        "candidate_count": 9,
    }


def test_zero_only_candidate_builds_a_valid_search_state() -> None:
    message = CanMessage(
        "M", 1, False, 10_000, 100, (0,), 20_000, "ECU", 0
    )
    startup, steady, _ = build_windows((message,), 5_000)
    slot_map = precompute_slot_map((message,), startup, steady)
    state = SearchState((message,), slot_map)
    state.apply(message, 0)
    assert state.current_offsets["M"] == 0


def test_gcls_uses_dynamic_domain_but_scores_real_original_baseline() -> None:
    candidates = OffsetSearchConfig(15, 102, 10).candidate_offsets_us
    messages = (
        CanMessage("A", 1, False, 10_000, 100, candidates, 20_000, "ECU", 0),
        CanMessage("B", 2, False, 10_000, 100, candidates, 25_000, "ECU", 1),
    )
    startup, steady, _ = build_windows(messages, 5_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    result = run_gcls(
        messages,
        slot_map,
        OptimizationConfig(
            offset_min_us=15_000,
            offset_max_us=102_000,
            offset_step_us=10_000,
            restart_policy=RestartPolicy.fixed(1),
        ),
    )
    assert result.initial_objective.steady_peak == 100
    assert all(row.offset_us in candidates for row in result.assignments)
    assert messages[0].original_offset_us == 20_000
