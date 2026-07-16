"""! @file test_local_search.py
@brief 1-opt、热点候选与可复现 GCLS 测试。

@author 篠見由紀
"""

from math import ceil
from types import SimpleNamespace

from canfd_offset_optimizer.config import (
    ObjectiveConfig,
    OptimizationConfig,
    PeakToleranceConfig,
)
from canfd_offset_optimizer.models import (
    CanMessage,
    ObjectiveMode,
    PeakToleranceType,
)
from canfd_offset_optimizer.optimization.gcls import run_gcls
from canfd_offset_optimizer.optimization import gcls as gcls_module
from canfd_offset_optimizer.optimization.greedy import greedy_construct
from canfd_offset_optimizer.optimization.local_search import (
    SearchStatistics,
    conflict_candidates,
    conflict_pair_search,
    hot_slots,
    is_one_optimal,
    low_delta_variance_offsets,
    relocate_single_messages,
    variance_hot_slots,
)
from canfd_offset_optimizer.optimization.objective import score_state
from canfd_offset_optimizer.timeline.slot_map import SlotMap, build_windows, precompute_slot_map
from canfd_offset_optimizer.timeline.state import SearchState


def fixture() -> tuple[tuple[CanMessage, ...], SlotMap]:
    offsets = tuple(range(15_000, 100_001, 5_000))
    specs = ((0x391, 20_000, 180), (0x460, 100_000, 300), (0x15E, 10_000, 120), (0x31B, 50_000, 220))
    messages = tuple(
        CanMessage(f"M{can_id:X}", can_id, False, cycle, weight, offsets, None, "VCU", index)
        for index, (can_id, cycle, weight) in enumerate(specs)
    )
    startup, steady, _ = build_windows(messages, 5_000, 500_000)
    return messages, precompute_slot_map(messages, startup, steady)


def test_relocation_reaches_one_optimum_and_hot_candidates_are_bounded() -> None:
    messages, slot_map = fixture()
    state, _ = greedy_construct(messages, slot_map, 3_750)
    before = score_state(state, 3_750)
    relocate_single_messages(state, 3_750)
    assert score_state(state, 3_750) <= before
    assert is_one_optimal(state, 3_750)
    candidates = conflict_candidates(state, hot_slots(state, 2), 2)
    assert 0 < len(candidates) <= 2
    hot = set(hot_slots(state, 2))
    assert all(
        hot.intersection(state.slot_map.for_candidate(message, state.current_offsets[message.name]).steady)
        for message in candidates
    )


def test_pair_search_only_accepts_improvement_and_gcls_is_reproducible() -> None:
    messages, slot_map = fixture()
    state, _ = greedy_construct(messages, slot_map, 3_750)
    relocate_single_messages(state, 3_750)
    before = score_state(state, 3_750)
    conflict_pair_search(state, 3_750, 3, 3, (1, 2), 5_000)
    assert score_state(state, 3_750) <= before
    config = OptimizationConfig(random_restarts=2, conflict_candidate_cap=3)
    first = run_gcls(messages, slot_map, config, seed=123)
    second = run_gcls(messages, slot_map, config, seed=123)
    assert first.assignments == second.assignments
    assert first.objective == second.objective

    assert first.objective <= first.greedy_objective
    assert first.objective <= first.initial_objective
    assert tuple(record.seed for record in first.restart_records) == (123, 124, 125)


def test_pair_search_escapes_a_one_optimum_by_legal_swap() -> None:
    offsets = (5_000, 10_000, 15_000, 20_000)
    specs = ((10_000, 50), (20_000, 50), (20_000, 200))
    messages = tuple(
        CanMessage(f"P{index}", index + 1, False, cycle, weight, offsets, None, "ECU", index)
        for index, (cycle, weight) in enumerate(specs)
    )
    startup, steady, _ = build_windows(messages, 5_000, 40_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    state, _ = greedy_construct(messages, slot_map, 300)
    # 构造已知 1-opt 平台；只有两个 20 ms 报文协同交换才能降低启动峰值。
    for message in messages:
        state.remove(message)
    for message, offset in zip(messages, (15_000, 20_000, 10_000), strict=True):
        state.apply(message, offset)
    before = score_state(state, 300)
    assert is_one_optimal(state, 300)
    statistics = conflict_pair_search(state, 300, 4, 3, (1, 2, 3), 5_000)
    assert statistics.accepted_moves >= 1
    assert score_state(state, 300) < before
    assert state.current_offsets["P1"] == 10_000
    assert state.current_offsets["P2"] == 20_000


def test_balanced_uses_peak_reference_budget_and_preserves_guardrails() -> None:
    messages, slot_map = fixture()
    config = OptimizationConfig(random_restarts=2, conflict_candidate_cap=4)
    first = run_gcls(
        messages,
        slot_map,
        config,
        seed=9,
        objective_config=ObjectiveConfig(ObjectiveMode.BALANCED),
    )
    second = run_gcls(
        messages,
        slot_map,
        config,
        seed=9,
        objective_config=ObjectiveConfig(ObjectiveMode.BALANCED),
    )
    reference = first.peak_reference_objective
    assert reference is not None
    assert first.peak_budget_us == ceil(reference.steady_peak * 1.05)
    assert first.objective.steady_peak <= first.peak_budget_us
    assert first.objective.sum_square_load <= reference.sum_square_load
    assert (first.objective.violation_count, first.objective.violation_excess) <= (
        reference.violation_count,
        reference.violation_excess,
    )
    assert first.assignments == second.assignments
    assert first.objective == second.objective

    absolute = run_gcls(
        messages,
        slot_map,
        config,
        seed=9,
        objective_config=ObjectiveConfig(
            ObjectiveMode.BALANCED,
            PeakToleranceConfig(PeakToleranceType.ABSOLUTE, 20),
        ),
    )
    absolute_reference = absolute.peak_reference_objective
    assert absolute_reference is not None
    assert absolute.peak_budget_us == absolute_reference.steady_peak + 20


def test_variance_hotspots_and_low_delta_offsets_are_bounded_and_stable() -> None:
    messages, slot_map = fixture()
    state, _ = greedy_construct(messages, slot_map, 3_750)
    slots = variance_hot_slots(state)
    total = sum(state.steady_slot_loads)
    assert slots
    assert all(
        state.steady_slot_loads[slot] * len(state.steady_slot_loads) > total
        for slot in slots
    )
    message = messages[0]
    old = state.remove(message)
    before = state.clone()
    offsets = low_delta_variance_offsets(state, message, 3)
    assert offsets == low_delta_variance_offsets(state, message, 3)
    assert 0 < len(offsets) <= 3
    assert set(offsets) <= set(message.allowed_offsets_us)
    assert state.current_offsets == before.current_offsets
    assert state.steady_slot_loads == before.steady_slot_loads
    state.apply(message, old)
    state.validate_invariants(require_complete=True)


def test_balanced_post_validation_falls_back_and_records_reason(monkeypatch: object) -> None:
    messages, slot_map = fixture()
    original_guard = gcls_module._balanced_guardrail_failures
    calls = 0

    def forced_once(*args: object, **kwargs: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ("forced acceptance-test failure",)
        return original_guard(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(  # type: ignore[attr-defined]
        gcls_module, "_balanced_guardrail_failures", forced_once
    )
    result = run_gcls(
        messages,
        slot_map,
        OptimizationConfig(random_restarts=0, conflict_candidate_cap=3),
        seed=5,
        objective_config=ObjectiveConfig(ObjectiveMode.BALANCED),
    )
    reference = result.peak_reference_objective
    assert reference is not None
    assert result.balanced_fallback_reason == "forced acceptance-test failure"
    assert result.objective.steady_peak == reference.steady_peak
    assert result.objective.sum_square_load == reference.sum_square_load


def test_balanced_keeps_a_better_eligible_baseline(monkeypatch: object) -> None:
    offsets = (5_000, 10_000)
    messages = (
        CanMessage("A", 1, False, 10_000, 100, offsets, 5_000, "ECU", 0),
        CanMessage("B", 2, False, 10_000, 100, offsets, 10_000, "ECU", 1),
    )
    startup, steady, _ = build_windows(messages, 5_000, 10_000)
    slot_map = precompute_slot_map(messages, startup, steady)
    incumbent_assignments = {"A": 5_000, "B": 5_000}
    incumbent_state = SearchState(messages, slot_map)
    incumbent_state.apply_assignments(incumbent_assignments)
    peak_reference = SimpleNamespace(
        objective=score_state(incumbent_state, 3_750),
        restart_records=(),
        evaluation_count=0,
        elapsed_seconds=0.0,
    )

    def no_search(*args: object, **kwargs: object) -> SearchStatistics:
        return SearchStatistics()

    def fixed_greedy(*args: object, **kwargs: object) -> tuple[SearchState, int]:
        state = SearchState(messages, slot_map)
        state.apply_assignments(incumbent_assignments)
        return state, 0

    monkeypatch.setattr(gcls_module, "relocate_single_messages", no_search)  # type: ignore[attr-defined]
    monkeypatch.setattr(gcls_module, "conflict_pair_search", no_search)  # type: ignore[attr-defined]
    monkeypatch.setattr(gcls_module, "greedy_construct", fixed_greedy)  # type: ignore[attr-defined]
    result = gcls_module._run_gcls_with_policy(
        messages,
        slot_map,
        OptimizationConfig(random_restarts=0),
        gcls_module.ObjectivePolicy(ObjectiveMode.BALANCED, 3_750, 200),
        seed=0,
        incumbent_assignments=incumbent_assignments,
        peak_reference_result=peak_reference,  # type: ignore[arg-type]
    )

    assert result.offset_by_name() == {"A": 5_000, "B": 10_000}
    assert result.objective.sum_square_load < peak_reference.objective.sum_square_load
