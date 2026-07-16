"""! @file gcls.py
@brief 编排贪心、1-opt、冲突双搜索和可复现随机重启。

@author 篠見由紀
"""

from __future__ import annotations

import random
from collections import defaultdict
from time import perf_counter

from ..config import OptimizationConfig
from ..models import (
    CanMessage,
    OffsetAssignment,
    OptimizationResult,
    RestartRecord,
    WeightMode,
)
from ..timeline.slot_map import SlotMap
from ..timeline.state import SearchState
from .greedy import greedy_construct, greedy_order
from .local_search import (
    SearchStatistics,
    conflict_pair_search,
    relocate_single_messages,
)
from .objective import score_state, slot_load_threshold_us


def _restart_order(messages: tuple[CanMessage, ...], seed: int) -> tuple[CanMessage, ...]:
    """! @brief 只在同周期、同权重组内按 seed 扰动顺序。"""
    base = greedy_order(messages)
    groups: dict[tuple[int, int], list[CanMessage]] = defaultdict(list)
    group_sequence: list[tuple[int, int]] = []
    for message in base:
        key = (message.cycle_time_us, message.frame_time_us)
        if key not in groups:
            group_sequence.append(key)
        groups[key].append(message)
    generator = random.Random(seed)
    ordered: list[CanMessage] = []
    for key in group_sequence:
        group = groups[key]
        generator.shuffle(group)
        ordered.extend(group)
    return tuple(ordered)


def _assignment_key(state: SearchState) -> tuple[int, ...]:
    return tuple(
        state.current_offsets[message.name]
        for message in sorted(
            state.messages,
            key=lambda item: (item.definition_index, item.can_id, item.name),
        )
    )


def run_gcls(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    config: OptimizationConfig,
    average_load_limit: float = 0.75,
    seed: int = 0,
    weight_mode: WeightMode = WeightMode.FRAME_TIME_US,
) -> OptimizationResult:
    """! @brief 运行完整 GCLS 并返回全局词典序最优结果。

    @note `random_restarts` 表示首次确定性运行后的附加重启次数。
    """
    started = perf_counter()
    load_threshold = (
        slot_load_threshold_us(config.slot_width_us, average_load_limit)
        if weight_mode is WeightMode.FRAME_TIME_US
        else None
    )
    attempt_count = config.random_restarts + 1
    baseline_state = SearchState(messages, slot_map)
    for message in messages:
        original = message.original_offset_us
        baseline_offset = (
            original
            if original is not None and original in message.allowed_offsets_us
            else min(message.allowed_offsets_us)
        )
        baseline_state.apply(message, baseline_offset)
    initial_score = score_state(baseline_state, load_threshold)
    # 先把合法原始配置也推进到同一局部最优条件；这样既不会推荐更差结果，
    # 也不会因直接保留一个未经搜索的基线而破坏最终 1-opt 不变量。
    total = relocate_single_messages(
        baseline_state, load_threshold, greedy_order(messages)
    )
    total += conflict_pair_search(
        baseline_state,
        load_threshold,
        config.hot_slot_count,
        config.conflict_candidate_cap,
        config.pair_neighbor_steps,
        config.offset_step_us,
    )
    best_state = baseline_state.clone()
    best_score = score_state(baseline_state, load_threshold)
    first_greedy_score = None
    records: list[RestartRecord] = []
    for attempt in range(attempt_count):
        actual_seed = seed + attempt
        order = greedy_order(messages) if attempt == 0 else _restart_order(messages, actual_seed)
        state, evaluations = greedy_construct(messages, slot_map, load_threshold, order)
        greedy_score = score_state(state, load_threshold)
        if first_greedy_score is None:
            first_greedy_score = greedy_score
        stats = SearchStatistics(evaluations, 0)
        stats += relocate_single_messages(state, load_threshold, order)
        stats += conflict_pair_search(
            state,
            load_threshold,
            config.hot_slot_count,
            config.conflict_candidate_cap,
            config.pair_neighbor_steps,
            config.offset_step_us,
        )
        total += stats
        score = score_state(state, load_threshold)
        records.append(RestartRecord(actual_seed, score))
        if score < best_score or (
            score == best_score and _assignment_key(state) < _assignment_key(best_state)
        ):
            best_state = state.clone()
            best_score = score
    if first_greedy_score is None:
        raise RuntimeError("GCLS produced no attempt")
    ordered_messages = tuple(
        sorted(messages, key=lambda item: (item.definition_index, item.can_id, item.name))
    )
    assignments = tuple(
        OffsetAssignment(
            message.name, message.can_id, best_state.current_offsets[message.name]
        )
        for message in ordered_messages
    )
    return OptimizationResult(
        messages=ordered_messages,
        assignments=assignments,
        objective=best_score,
        initial_objective=initial_score,
        greedy_objective=first_greedy_score,
        steady_slot_loads=tuple(best_state.steady_slot_loads),
        startup_slot_loads=tuple(best_state.startup_slot_loads),
        steady_slot_counts=tuple(best_state.steady_slot_counts),
        startup_slot_counts=tuple(best_state.startup_slot_counts),
        restart_records=tuple(records),
        evaluation_count=total.evaluations,
        accepted_moves=total.accepted_moves,
        elapsed_seconds=perf_counter() - started,
    )
