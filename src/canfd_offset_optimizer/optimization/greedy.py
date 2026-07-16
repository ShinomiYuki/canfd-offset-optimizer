"""! @file greedy.py
@brief 按固定键和确定性 tie-break 构造完整贪心 Offset 解。

@author 篠見由紀
"""

from __future__ import annotations

from ..models import CanMessage
from ..timeline.slot_map import SlotMap
from ..timeline.state import SearchState
from .objective import ObjectivePolicy, score_state


def greedy_order(messages: tuple[CanMessage, ...]) -> tuple[CanMessage, ...]:
    """! @brief 按 `(cycle, -frame_time, can_id, definition_index)` 稳定排序。"""
    return tuple(
        sorted(
            messages,
            key=lambda message: (
                message.cycle_time_us,
                -message.frame_time_us,
                message.can_id,
                message.definition_index,
                message.name,
            ),
        )
    )


def greedy_construct(
    messages: tuple[CanMessage, ...],
    slot_map: SlotMap,
    policy: ObjectivePolicy | int | None,
    ordered_messages: tuple[CanMessage, ...] | None = None,
) -> tuple[SearchState, int]:
    """! @brief 对每条报文选择令当前词典序目标最小的候选 Offset。

    @return 完整状态与候选评价次数。
    @note 同分候选通过升序遍历 Offset 固定选择较小值。
    """
    order = greedy_order(messages) if ordered_messages is None else ordered_messages
    if set(order) != set(messages) or len(order) != len(messages):
        raise ValueError("ordered_messages must be a permutation of messages")
    state = SearchState(messages, slot_map)
    evaluations = 0
    for message in order:
        best_offset: int | None = None
        best_score = None
        for offset in message.allowed_offsets_us:
            state.apply(message, offset)
            score = score_state(state, policy)
            evaluations += 1
            state.rollback(message, offset)
            if best_score is None or score < best_score:
                best_score = score
                best_offset = offset
        if best_offset is None:
            raise RuntimeError(f"no candidate offset for {message.name}")
        state.apply(message, best_offset)
    state.validate_invariants(require_complete=True)
    return state, evaluations
