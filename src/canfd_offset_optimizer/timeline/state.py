"""! @file state.py
@brief 支持 apply、remove、rollback 与不变量校验的增量搜索状态。

@author 篠見由紀
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from ..exceptions import OptimizationError
from ..models import CanMessage
from .slot_map import SlotMap


class SearchState:
    """! @brief 维护当前 Offset 对启动/稳态负载与释放计数的贡献。

    @invariant 数组非负；每条已应用报文恰好有一个合法 Offset；稳态总量守恒。
    """

    def __init__(self, messages: tuple[CanMessage, ...], slot_map: SlotMap) -> None:
        self.messages = messages
        self.slot_map = slot_map
        self._by_name = {message.name: message for message in messages}
        if len(self._by_name) != len(messages):
            raise OptimizationError("message names must be unique")
        self.steady_slot_loads = [0] * slot_map.steady_window.slot_count
        self.startup_slot_loads = [0] * slot_map.startup_window.slot_count
        self.steady_slot_counts = [0] * slot_map.steady_window.slot_count
        self.startup_slot_counts = [0] * slot_map.startup_window.slot_count
        self.current_offsets: dict[str, int] = {}

    def apply(self, message: CanMessage, offset_us: int) -> None:
        """! @brief 将尚未分配的报文贡献加入候选 Offset。

        @raises OptimizationError 报文已分配或候选非法时抛出。
        """
        self._check_message(message)
        if message.name in self.current_offsets:
            raise OptimizationError(f"message {message.name} is already applied")
        if offset_us not in message.allowed_offsets_us:
            raise OptimizationError(f"illegal offset {offset_us} for {message.name}")
        try:
            hits = self.slot_map.for_candidate(message, offset_us)
        except ValueError as exc:
            raise OptimizationError(str(exc)) from exc
        self._change_contribution(message, hits.steady, hits.startup, 1)
        self.current_offsets[message.name] = offset_us

    def remove(self, message: CanMessage, offset_us: int | None = None) -> int:
        """! @brief 移除报文当前贡献并返回被移除 Offset。

        @raises OptimizationError 报文未分配或显式 Offset 与当前值不符时抛出。
        """
        self._check_message(message)
        current = self.current_offsets.get(message.name)
        if current is None:
            raise OptimizationError(f"message {message.name} is not applied")
        if offset_us is not None and current != offset_us:
            raise OptimizationError(
                f"offset mismatch for {message.name}: current={current}, requested={offset_us}"
            )
        try:
            hits = self.slot_map.for_candidate(message, current)
        except ValueError as exc:
            raise OptimizationError(str(exc)) from exc
        self._change_contribution(message, hits.steady, hits.startup, -1)
        del self.current_offsets[message.name]
        return current

    def rollback(self, message: CanMessage, offset_us: int) -> None:
        """! @brief 无损撤销一次候选 `apply`，语义等同受校验的 remove。"""
        self.remove(message, offset_us)

    def replace(self, message: CanMessage, new_offset_us: int) -> int:
        """! @brief 原子地将已分配报文移动到新 Offset，并返回旧值。"""
        old = self.remove(message)
        try:
            self.apply(message, new_offset_us)
        except Exception:
            self.apply(message, old)
            raise
        return old

    def clone(self) -> SearchState:
        """! @brief 返回可独立修改的逐元素状态副本。"""
        cloned = SearchState(self.messages, self.slot_map)
        cloned.steady_slot_loads = self.steady_slot_loads.copy()
        cloned.startup_slot_loads = self.startup_slot_loads.copy()
        cloned.steady_slot_counts = self.steady_slot_counts.copy()
        cloned.startup_slot_counts = self.startup_slot_counts.copy()
        cloned.current_offsets = self.current_offsets.copy()
        return cloned

    def apply_assignments(self, assignments: Mapping[str, int]) -> None:
        """! @brief 按报文定义顺序原子地应用一组完整或部分分配。"""
        unknown = set(assignments) - self._by_name.keys()
        if unknown:
            raise OptimizationError(f"assignment contains unknown messages: {sorted(unknown)}")
        applied: list[CanMessage] = []
        try:
            for message in self.messages:
                if message.name in assignments:
                    self.apply(message, assignments[message.name])
                    applied.append(message)
        except Exception:
            for message in reversed(applied):
                self.remove(message)
            raise

    def validate_invariants(self, require_complete: bool = False) -> None:
        """! @brief 重算当前状态并验证非负、合法性和稳态守恒。

        @raises OptimizationError 任一数组或总量与预计算贡献不一致时抛出。
        """
        arrays = (
            self.steady_slot_loads,
            self.startup_slot_loads,
            self.steady_slot_counts,
            self.startup_slot_counts,
        )
        if any(value < 0 for array in arrays for value in array):
            raise OptimizationError("slot loads and counts must be non-negative")
        if require_complete and len(self.current_offsets) != len(self.messages):
            raise OptimizationError("state does not contain a complete assignment")
        expected_steady_load = 0
        expected_steady_count = 0
        rebuilt = SearchState(self.messages, self.slot_map)
        for message in self.messages:
            offset = self.current_offsets.get(message.name)
            if offset is None:
                continue
            if offset not in message.allowed_offsets_us:
                raise OptimizationError(f"illegal current offset for {message.name}")
            release_count = len(self.slot_map.for_candidate(message, offset).steady)
            expected_cycles = self.slot_map.steady_window.slot_count * self.slot_map.steady_window.slot_width_us // message.cycle_time_us
            if release_count != expected_cycles:
                raise OptimizationError(f"steady release conservation failed for {message.name}")
            expected_steady_count += release_count
            expected_steady_load += release_count * message.frame_time_us
            rebuilt.apply(message, offset)
        if sum(self.steady_slot_counts) != expected_steady_count:
            raise OptimizationError("total steady release count is not conserved")
        if sum(self.steady_slot_loads) != expected_steady_load:
            raise OptimizationError("total steady weighted load is not conserved")
        if (
            self.steady_slot_loads != rebuilt.steady_slot_loads
            or self.startup_slot_loads != rebuilt.startup_slot_loads
            or self.steady_slot_counts != rebuilt.steady_slot_counts
            or self.startup_slot_counts != rebuilt.startup_slot_counts
        ):
            raise OptimizationError("incremental arrays differ from a full rebuild")

    def _check_message(self, message: CanMessage) -> None:
        if self._by_name.get(message.name) != message:
            raise OptimizationError(f"message {message.name} does not belong to this state")

    @staticmethod
    def _update(
        loads: list[int],
        counts: list[int],
        slots: tuple[int, ...],
        weight: int,
        direction: int,
    ) -> None:
        for slot in slots:
            loads[slot] += direction * weight
            counts[slot] += direction

    def _change_contribution(
        self,
        message: CanMessage,
        steady_slots: tuple[int, ...],
        startup_slots: tuple[int, ...],
        direction: int,
    ) -> None:
        """! @brief 预检两个窗口后一次性增减贡献，避免部分数组更新。"""
        changes = (
            (self.steady_slot_loads, self.steady_slot_counts, steady_slots),
            (self.startup_slot_loads, self.startup_slot_counts, startup_slots),
        )
        if direction not in (-1, 1):
            raise OptimizationError("contribution direction must be -1 or 1")
        for loads, counts, slots in changes:
            for slot, occurrences in Counter(slots).items():
                if not 0 <= slot < len(loads) or len(loads) != len(counts):
                    raise OptimizationError(
                        f"precomputed slot index {slot} is invalid for {message.name}"
                    )
                if direction < 0 and (
                    loads[slot] < occurrences * message.frame_time_us
                    or counts[slot] < occurrences
                ):
                    raise OptimizationError(
                        f"removing {message.name} would make slot state negative"
                    )
        for loads, counts, slots in changes:
            self._update(loads, counts, slots, message.frame_time_us, direction)
