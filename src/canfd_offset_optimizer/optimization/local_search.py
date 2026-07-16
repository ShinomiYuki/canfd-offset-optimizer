"""! @file local_search.py
@brief 单报文重定位与冲突导向有限双报文邻域搜索。

@author 篠見由紀
"""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from ..models import CanMessage, ObjectiveMode, ObjectiveValue
from ..timeline.state import SearchState
from .objective import ObjectivePolicy, coerce_objective_policy, score_state


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


def delta_q_for_relocations(
    state: SearchState,
    moves: tuple[tuple[CanMessage, int | None], ...],
) -> int:
    """Return the exact steady-state ``ΔQ`` for simultaneous relocations/removals.

    ``state`` must still contain every moved message at its old Offset.  Slot changes are
    accumulated before squaring, so old/new intersections and changes from two messages
    cancel by their net load rather than being added and removed independently.
    ``None`` means that the message is removed and not re-added.
    """
    if len({message.name for message, _ in moves}) != len(moves):
        raise ValueError("each message may appear in moves at most once")
    delta_loads: defaultdict[int, int] = defaultdict(int)
    for message, new_offset in moves:
        old_offset = state.current_offsets.get(message.name)
        if old_offset is None:
            raise ValueError(f"message {message.name} must be applied before relocation")
        if new_offset is not None and new_offset not in message.allowed_offsets_us:
            raise ValueError(f"illegal offset {new_offset} for {message.name}")
        old_hits = Counter(
            state.slot_map.for_candidate(message, old_offset).steady
        )
        new_hits = (
            Counter(state.slot_map.for_candidate(message, new_offset).steady)
            if new_offset is not None
            else Counter()
        )
        for slot in old_hits.keys() | new_hits.keys():
            net_releases = new_hits[slot] - old_hits[slot]
            if net_releases:
                delta_loads[slot] += net_releases * message.frame_time_us
    return sum(
        (state.steady_slot_loads[slot] + delta) ** 2
        - state.steady_slot_loads[slot] ** 2
        for slot, delta in delta_loads.items()
        if delta
    )


def relocate_single_messages(
    state: SearchState,
    policy: ObjectivePolicy | int | None,
    message_order: tuple[CanMessage, ...] | None = None,
) -> SearchStatistics:
    """! @brief 重复执行最佳单报文移动直至达到 1-opt 局部最优。

    @invariant 只接受全局目标严格改善的移动。
    """
    policy = coerce_objective_policy(policy)
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
            old_score = score_state(state, policy)
            state.remove(message, old_offset)
            best_offset = old_offset
            best_score = old_score
            for offset in message.allowed_offsets_us:
                state.apply(message, offset)
                candidate = score_state(state, policy)
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
    state: SearchState,
    slots: tuple[int, ...],
    candidate_cap: int,
    policy: ObjectivePolicy | None = None,
) -> tuple[CanMessage, ...]:
    """! @brief 提取命中热点且移除后最能削峰或降低平方和的报文。"""
    if candidate_cap <= 0:
        raise ValueError("candidate_cap must be positive")
    selected: list[tuple[int, CanMessage]] = []
    hot = set(slots)
    for message in state.messages:
        offset = state.current_offsets[message.name]
        hits = state.slot_map.for_candidate(message, offset).steady
        if policy is not None and policy.mode is not ObjectiveMode.PEAK:
            # Eligibility still comes from variance hotspots, while ranking uses the
            # message's true full-window Qss improvement after removal.
            contribution = (
                -delta_q_for_relocations(state, ((message, None),))
                if hot.intersection(hits)
                else 0
            )
        else:
            contribution = sum(slot in hot for slot in hits) * message.frame_time_us
        if contribution:
            selected.append((contribution, message))
    selected.sort(
        key=lambda item: (
            -item[0],
            item[1].definition_index,
            item[1].can_id,
            item[1].name,
        )
    )
    return tuple(message for _, message in selected[:candidate_cap])


def variance_hot_slots(state: SearchState) -> tuple[int, ...]:
    """! @brief 返回严格高于当前稳态平均负载的全部时隙。"""
    loads = state.steady_slot_loads
    if not loads:
        return ()
    total = sum(loads)
    slots = tuple(index for index, load in enumerate(loads) if load * len(loads) > total)
    return slots or hot_slots(state, 1)


def low_delta_variance_offsets(
    state: SearchState,
    message: CanMessage,
    cap: int,
    excluded_offset: int | None = None,
) -> tuple[int, ...]:
    """! @brief 返回把未应用报文加入当前状态时 ΔQ 最低的有限 Offset。"""
    if cap <= 0:
        raise ValueError("variance offset cap must be positive")
    if message.name in state.current_offsets:
        raise ValueError("message must be removed before evaluating variance offsets")
    ranked: list[tuple[int, int]] = []
    for offset in message.allowed_offsets_us:
        if offset == excluded_offset:
            continue
        delta = 0
        hits = state.slot_map.for_candidate(message, offset).steady
        for slot, occurrences in Counter(hits).items():
            added = occurrences * message.frame_time_us
            load = state.steady_slot_loads[slot]
            delta += (load + added) * (load + added) - load * load
        ranked.append((delta, offset))
    ranked.sort()
    return tuple(offset for _, offset in ranked[:cap])


def lowest_delta_relocation_offsets(
    state: SearchState,
    message: CanMessage,
    cap: int,
    excluded_offset: int | None = None,
) -> tuple[int, ...]:
    """Return the globally lowest exact-``ΔQ`` legal relocation Offsets."""
    if cap <= 0:
        raise ValueError("variance offset cap must be positive")
    if message.name not in state.current_offsets:
        raise ValueError("message must be applied before evaluating relocations")
    ranked = sorted(
        (
            delta_q_for_relocations(state, ((message, offset),)),
            offset,
        )
        for offset in message.allowed_offsets_us
        if offset != excluded_offset
    )
    return tuple(offset for _, offset in ranked[:cap])


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


def _state_signature(
    state: SearchState, policy: ObjectivePolicy
) -> tuple[object, ...]:
    """Capture every mutable search component plus the derived objective cache value."""
    return (
        tuple(sorted(state.current_offsets.items())),
        tuple(state.steady_slot_loads),
        tuple(state.startup_slot_loads),
        tuple(state.steady_slot_counts),
        tuple(state.startup_slot_counts),
        score_state(state, policy),
    )


def conflict_pair_search(
    state: SearchState,
    policy: ObjectivePolicy | int | None,
    hot_slot_count: int,
    candidate_cap: int,
    neighbor_steps: tuple[int, ...],
    offset_step_us: int,
    variance_offset_cap: int = 3,
) -> SearchStatistics:
    """! @brief 在热点贡献报文的有限邻域中尝试双移动与合法 Offset 交换。

    @details
    每次接受最佳严格改善后先恢复 1-opt，再重新提取热点；未扫描无关报文对。
    """
    policy = coerce_objective_policy(policy)
    total = SearchStatistics()
    while True:
        baseline = score_state(state, policy)
        selected_slots = (
            hot_slots(state, hot_slot_count)
            if policy.mode is ObjectiveMode.PEAK
            else variance_hot_slots(state)
        )
        candidates = conflict_candidates(
            state, selected_slots, candidate_cap, policy
        )
        best: tuple[ObjectiveValue, int, int, CanMessage, CanMessage] | None = None
        evaluations = 0
        for first, second in combinations(candidates, 2):
            pair_signature = _state_signature(state, policy)
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
            if policy.mode is not ObjectiveMode.PEAK:
                first_offsets.update(
                    lowest_delta_relocation_offsets(
                        state, first, variance_offset_cap, first_old
                    )
                )
                second_offsets.update(
                    lowest_delta_relocation_offsets(
                        state, second, variance_offset_cap, second_old
                    )
                )
            state.remove(first)
            state.remove(second)
            try:
                removed_signature = _state_signature(state, policy)
                for first_new in sorted(first_offsets):
                    for second_new in sorted(second_offsets):
                        # Pair search must move both messages. Allowing one side to stay
                        # silently turns this bounded neighborhood into another 1-opt pass.
                        if first_new == first_old or second_new == second_old:
                            continue
                        first_applied = False
                        second_applied = False
                        try:
                            state.apply(first, first_new)
                            first_applied = True
                            state.apply(second, second_new)
                            second_applied = True
                            score = score_state(state, policy)
                            evaluations += 1
                        finally:
                            if second_applied:
                                state.rollback(second, second_new)
                            if first_applied:
                                state.rollback(first, first_new)
                        if _state_signature(state, policy) != removed_signature:
                            raise RuntimeError("pair-search trial rollback was not exact")
                        key = (score, first_new, second_new, first, second)
                        if score < baseline and (
                            best is None or key[:3] < best[:3]
                        ):
                            best = key
            finally:
                if first.name not in state.current_offsets:
                    state.apply(first, first_old)
                if second.name not in state.current_offsets:
                    state.apply(second, second_old)
            if _state_signature(state, policy) != pair_signature:
                raise RuntimeError("pair-search pair rollback was not exact")
        total += SearchStatistics(evaluations, 0)
        if best is None:
            break
        _, first_new, second_new, first, second = best
        state.remove(first)
        state.remove(second)
        state.apply(first, first_new)
        state.apply(second, second_new)
        total += SearchStatistics(0, 1)
        total += relocate_single_messages(state, policy)
    state.validate_invariants(require_complete=True)
    return total


def is_one_optimal(
    state: SearchState, policy: ObjectivePolicy | int | None
) -> bool:
    """! @brief 穷举单报文邻域验证不存在严格改善。"""
    policy = coerce_objective_policy(policy)
    baseline = score_state(state, policy)
    for message in state.messages:
        old = state.remove(message)
        try:
            for offset in message.allowed_offsets_us:
                state.apply(message, offset)
                candidate = score_state(state, policy)
                state.rollback(message, offset)
                if candidate < baseline:
                    return False
        finally:
            state.apply(message, old)
    return True
