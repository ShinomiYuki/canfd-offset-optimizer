"""! @file local_search.py
@brief 单报文重定位与冲突导向有限双报文邻域搜索。

@author 篠見由紀
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from ..models import CanMessage, ObjectiveValue
from ..timeline.state import SearchState
from .objective import score_state


@dataclass(frozen=True, slots=True)
class SearchStatistics:
    """! @brief 局部搜索的候选评价和严格接受计数。"""

    evaluations: int = 0
    accepted_moves: int = 0

    def __add__(self, other: SearchStatistics) -> SearchStatistics:
        return SearchStatistics(
            self.evaluations + other.evaluations,
            self.accepted_moves + other.accepted_moves,
        )


def relocate_single_messages(
    state: SearchState,
    load_threshold: int | None,
    message_order: tuple[CanMessage, ...] | None = None,
) -> SearchStatistics:
    """! @brief 重复执行最佳单报文移动直至达到 1-opt 局部最优。

    @invariant 只接受全局目标严格改善的移动。
    """
    order = state.messages if message_order is None else message_order
    if len(order) != len(state.messages) or set(order) != set(state.messages):
        raise ValueError("message_order must be a permutation of state.messages")
    evaluations = 0
    accepted = 0
    improved = True
    while improved:
        improved = False
        for message in order:
            old_offset = state.current_offsets[message.name]
            old_score = score_state(state, load_threshold)
            state.remove(message, old_offset)
            best_offset = old_offset
            best_score = old_score
            for offset in message.allowed_offsets_us:
                state.apply(message, offset)
                candidate = score_state(state, load_threshold)
                evaluations += 1
                state.rollback(message, offset)
                if candidate < best_score:
                    best_offset = offset
                    best_score = candidate
            state.apply(message, best_offset)
            if best_score < old_score:
                accepted += 1
                improved = True
    state.validate_invariants(require_complete=True)
    return SearchStatistics(evaluations, accepted)


def hot_slots(state: SearchState, count: int) -> tuple[int, ...]:
    """! @brief 返回负载最高的有限稳态时隙，负载相同时索引较小者优先。"""
    if count <= 0:
        raise ValueError("hot slot count must be positive")
    ranked = sorted(
        range(len(state.steady_slot_loads)),
        key=lambda slot: (-state.steady_slot_loads[slot], slot),
    )
    return tuple(ranked[:count])


def conflict_candidates(
    state: SearchState, slots: tuple[int, ...], candidate_cap: int
) -> tuple[CanMessage, ...]:
    """! @brief 提取真正命中热点的报文并按加权贡献排序、截断。"""
    if candidate_cap <= 0:
        raise ValueError("candidate_cap must be positive")
    selected: list[tuple[int, CanMessage]] = []
    hot = set(slots)
    for message in state.messages:
        offset = state.current_offsets[message.name]
        hits = state.slot_map.for_candidate(message, offset).steady
        contribution = sum(slot in hot for slot in hits) * message.frame_time_us
        if contribution:
            selected.append((contribution, message))
    selected.sort(
        key=lambda item: (-item[0], item[1].definition_index, item[1].can_id)
    )
    return tuple(message for _, message in selected[:candidate_cap])


def _neighbor_offsets(
    message: CanMessage,
    current: int,
    neighbor_steps: tuple[int, ...],
    offset_step_us: int,
) -> tuple[int, ...]:
    candidates = {current}
    legal = set(message.allowed_offsets_us)
    for step in neighbor_steps:
        candidates.add(current - step * offset_step_us)
        candidates.add(current + step * offset_step_us)
    return tuple(sorted(candidates & legal))


def conflict_pair_search(
    state: SearchState,
    load_threshold: int | None,
    hot_slot_count: int,
    candidate_cap: int,
    neighbor_steps: tuple[int, ...],
    offset_step_us: int,
) -> SearchStatistics:
    """! @brief 在热点贡献报文的有限邻域中尝试双移动与合法 Offset 交换。

    @details
    每次接受最佳严格改善后先恢复 1-opt，再重新提取热点；未扫描无关报文对。
    """
    total = SearchStatistics()
    while True:
        baseline = score_state(state, load_threshold)
        candidates = conflict_candidates(
            state, hot_slots(state, hot_slot_count), candidate_cap
        )
        best: tuple[ObjectiveValue, int, int, CanMessage, CanMessage] | None = None
        evaluations = 0
        for first, second in combinations(candidates, 2):
            first_old = state.current_offsets[first.name]
            second_old = state.current_offsets[second.name]
            first_offsets = set(
                _neighbor_offsets(first, first_old, neighbor_steps, offset_step_us)
            )
            second_offsets = set(
                _neighbor_offsets(second, second_old, neighbor_steps, offset_step_us)
            )
            if second_old in first.allowed_offsets_us and first_old in second.allowed_offsets_us:
                first_offsets.add(second_old)
                second_offsets.add(first_old)
            state.remove(first)
            state.remove(second)
            for first_new in sorted(first_offsets):
                for second_new in sorted(second_offsets):
                    # Pair search must move both messages. Allowing one side to stay
                    # silently turns this bounded neighborhood into another 1-opt pass.
                    if first_new == first_old or second_new == second_old:
                        continue
                    state.apply(first, first_new)
                    state.apply(second, second_new)
                    score = score_state(state, load_threshold)
                    evaluations += 1
                    state.rollback(second, second_new)
                    state.rollback(first, first_new)
                    key = (score, first_new, second_new, first, second)
                    if score < baseline and (
                        best is None or key[:3] < best[:3]
                    ):
                        best = key
            state.apply(first, first_old)
            state.apply(second, second_old)
        total += SearchStatistics(evaluations, 0)
        if best is None:
            break
        _, first_new, second_new, first, second = best
        state.remove(first)
        state.remove(second)
        state.apply(first, first_new)
        state.apply(second, second_new)
        total += SearchStatistics(0, 1)
        total += relocate_single_messages(state, load_threshold)
    state.validate_invariants(require_complete=True)
    return total


def is_one_optimal(state: SearchState, load_threshold: int | None) -> bool:
    """! @brief 穷举单报文邻域验证不存在严格改善。"""
    baseline = score_state(state, load_threshold)
    for message in state.messages:
        old = state.remove(message)
        try:
            for offset in message.allowed_offsets_us:
                state.apply(message, offset)
                candidate = score_state(state, load_threshold)
                state.rollback(message, offset)
                if candidate < baseline:
                    return False
        finally:
            state.apply(message, old)
    return True
