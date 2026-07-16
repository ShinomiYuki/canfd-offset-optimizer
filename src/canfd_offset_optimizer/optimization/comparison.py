"""! @file comparison.py
@brief 编排原始基线、最小 Offset、Greedy、1-opt 与完整 GCLS 对比。

@details
本模块只复用现有算法并保存不可变快照，不实现新的评分或搜索规则。
"""

from __future__ import annotations

from time import perf_counter

from ..config import ObjectiveConfig, OptimizationConfig
from ..models import (
    AlgorithmComparisonResult,
    CanMessage,
    ComparisonStageResult,
    ObjectiveMode,
    OffsetAssignment,
    OptimizationResult,
    WeightMode,
)
from ..timeline.slot_map import SlotMap
from ..timeline.state import SearchState
from .gcls import run_gcls
from .greedy import greedy_construct, greedy_order
from .local_search import relocate_single_messages
from .objective import ObjectivePolicy, score_state, slot_load_threshold_us


def _snapshot(
    name: str,
    kind: str,
    state: SearchState,
    policy: ObjectivePolicy,
    evaluations: int,
    accepted_moves: int,
    elapsed_seconds: float,
) -> ComparisonStageResult:
    """! @brief 校验增量状态并复制为与后续搜索隔离的阶段结果。"""
    state.validate_invariants(require_complete=True)
    messages = tuple(
        sorted(
            state.messages,
            key=lambda message: (message.definition_index, message.can_id, message.name),
        )
    )
    assignments = tuple(
        OffsetAssignment(
            message.name,
            message.can_id,
            state.current_offsets[message.name],
            message.definition_index,
        )
        for message in messages
    )
    return ComparisonStageResult(
        name=name,
        kind=kind,
        assignments=assignments,
        objective=score_state(state, policy),
        steady_slot_loads=tuple(state.steady_slot_loads),
        startup_slot_loads=tuple(state.startup_slot_loads),
        steady_slot_counts=tuple(state.steady_slot_counts),
        startup_slot_counts=tuple(state.startup_slot_counts),
        evaluation_count=evaluations,
        accepted_moves=accepted_moves,
        elapsed_seconds=elapsed_seconds,
    )


def _assigned_state(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    assignment: dict[str, int],
) -> tuple[SearchState, float]:
    started = perf_counter()
    state = SearchState(messages, slot_map)
    state.apply_assignments(assignment)
    return state, perf_counter() - started


def compare_algorithms(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    config: OptimizationConfig,
    average_load_limit: float = 0.75,
    seed: int = 0,
    weight_mode: WeightMode = WeightMode.FRAME_TIME_US,
    objective_config: ObjectiveConfig | None = None,
    peak_reference_result: OptimizationResult | None = None,
) -> AlgorithmComparisonResult:
    """! @brief 运行固定五阶段对比并返回独立状态快照。

    @note 近似权重模式传递 None 阈值，物理违规两项目标固定为零。
    """
    load_threshold = (
        slot_load_threshold_us(config.slot_width_us, average_load_limit)
        if weight_mode is WeightMode.FRAME_TIME_US
        else None
    )
    selected_objective = objective_config or ObjectiveConfig(mode=ObjectiveMode.PEAK)
    gcls_result = run_gcls(
        messages,
        slot_map,
        config,
        average_load_limit,
        seed,
        weight_mode,
        selected_objective,
        peak_reference_result,
    )
    policy = ObjectivePolicy(
        gcls_result.objective.mode,
        load_threshold,
        gcls_result.peak_budget_us,
    )
    ordered = tuple(
        sorted(
            messages,
            key=lambda message: (message.definition_index, message.can_id, message.name),
        )
    )

    original_offsets = {
        message.name: (
            message.original_offset_us
            if message.original_offset_us in message.allowed_offsets_us
            else min(message.allowed_offsets_us)
        )
        for message in messages
    }
    original_state, original_elapsed = _assigned_state(
        messages, slot_map, original_offsets
    )
    original = _snapshot(
        "original", "baseline", original_state, policy, 0, 0, original_elapsed
    )

    minimum_state, minimum_elapsed = _assigned_state(
        messages,
        slot_map,
        {message.name: min(message.allowed_offsets_us) for message in messages},
    )
    minimum = _snapshot(
        "minimum", "baseline", minimum_state, policy, 0, 0, minimum_elapsed
    )

    greedy_started = perf_counter()
    greedy_state, greedy_evaluations = greedy_construct(
        messages, slot_map, policy, greedy_order(messages)
    )
    greedy_elapsed = perf_counter() - greedy_started
    greedy = _snapshot(
        "greedy",
        "algorithm",
        greedy_state,
        policy,
        greedy_evaluations,
        0,
        greedy_elapsed,
    )

    one_opt_state = greedy_state.clone()
    one_opt_started = perf_counter()
    one_opt_statistics = relocate_single_messages(
        one_opt_state, policy, greedy_order(messages)
    )
    one_opt_elapsed = greedy_elapsed + perf_counter() - one_opt_started
    greedy_one_opt = _snapshot(
        "greedy_1opt",
        "algorithm",
        one_opt_state,
        policy,
        greedy_evaluations + one_opt_statistics.evaluations,
        one_opt_statistics.accepted_moves,
        one_opt_elapsed,
    )

    gcls_state = SearchState(messages, slot_map)
    gcls_state.apply_assignments(gcls_result.offset_by_name())
    gcls = _snapshot(
        "gcls",
        "algorithm",
        gcls_state,
        policy,
        gcls_result.evaluation_count,
        gcls_result.accepted_moves,
        gcls_result.elapsed_seconds,
    )

    return AlgorithmComparisonResult(
        messages=ordered,
        stages=(original, minimum, greedy, greedy_one_opt, gcls),
        restart_records=gcls_result.restart_records,
        restart_execution=gcls_result.restart_execution,
        seed=seed,
        peak_reference_objective=gcls_result.peak_reference_objective,
        peak_budget_us=gcls_result.peak_budget_us,
        peak_reference_restart_records=gcls_result.peak_reference_restart_records,
        peak_reference_evaluation_count=gcls_result.peak_reference_evaluation_count,
        peak_reference_elapsed_seconds=gcls_result.peak_reference_elapsed_seconds,
        balanced_fallback_reason=gcls_result.balanced_fallback_reason,
        peak_candidate_archive=gcls_result.peak_candidate_archive,
        selected_peak_candidates=gcls_result.selected_peak_candidates,
        balanced_candidate_searches=gcls_result.balanced_candidate_searches,
    )


def extract_peak_optimization_result(
    comparison: AlgorithmComparisonResult,
) -> OptimizationResult:
    """! @brief 将已完成的 peak 对比快照恢复为可复用的 balanced 参考结果。

    @note 只复制不可变快照，不重新评价 Offset，也不修改比较报告。
    """
    gcls = comparison.stage("gcls")
    if gcls.objective.mode is not ObjectiveMode.PEAK:
        raise ValueError("only a peak comparison can be reused as a peak reference")
    return OptimizationResult(
        messages=comparison.messages,
        assignments=gcls.assignments,
        objective=gcls.objective,
        initial_objective=comparison.stage("original").objective,
        greedy_objective=comparison.stage("greedy").objective,
        steady_slot_loads=gcls.steady_slot_loads,
        startup_slot_loads=gcls.startup_slot_loads,
        steady_slot_counts=gcls.steady_slot_counts,
        startup_slot_counts=gcls.startup_slot_counts,
        restart_records=comparison.restart_records,
        restart_execution=comparison.restart_execution,
        evaluation_count=gcls.evaluation_count,
        accepted_moves=gcls.accepted_moves,
        elapsed_seconds=gcls.elapsed_seconds,
        peak_candidate_archive=comparison.peak_candidate_archive,
    )
