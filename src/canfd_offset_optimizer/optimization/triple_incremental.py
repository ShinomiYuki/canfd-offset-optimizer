"""Read-only exact objective evaluation for simultaneous three-message moves."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..models import CanMessage, ObjectiveValue
from ..timeline.slot_map import SlotMap
from ..timeline.state import SearchState
from .objective import ObjectivePolicy, calculate_objective


@dataclass(frozen=True, slots=True)
class SparseContribution:
    """Precomputed weighted load and release-count contributions for one candidate."""

    steady: tuple[tuple[int, int, int], ...]
    startup: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SparseRelocation:
    """Net sparse slot changes produced by replacing one old Offset with one new one."""

    steady: tuple[tuple[int, int, int], ...]
    startup: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class PairObjectiveSnapshot:
    """Exact immutable state after two prepared relocations."""

    steady_loads: tuple[int, ...]
    startup_loads: tuple[int, ...]
    steady_counts: tuple[int, ...]
    objective: ObjectiveValue
    steady_order: tuple[int, ...]
    startup_order: tuple[int, ...]
    count_order: tuple[int, ...]


class TripleContributionCache:
    """Precompute every message/Offset contribution without retaining mutable state."""

    def __init__(self, messages: tuple[CanMessage, ...], slot_map: SlotMap) -> None:
        self._messages = {message.name: message for message in messages}
        if len(self._messages) != len(messages):
            raise ValueError("triple contribution cache requires unique message names")
        self._by_candidate: dict[tuple[str, int], SparseContribution] = {}
        for message in messages:
            for offset in message.allowed_offsets_us:
                hits = slot_map.for_candidate(message, offset)
                self._by_candidate[(message.name, offset)] = SparseContribution(
                    steady=tuple(
                        (slot, occurrences * message.frame_time_us, occurrences)
                        for slot, occurrences in sorted(Counter(hits.steady).items())
                    ),
                    startup=tuple(
                        (slot, occurrences * message.frame_time_us)
                        for slot, occurrences in sorted(Counter(hits.startup).items())
                    ),
                )

    def contribution(self, message: CanMessage, offset_us: int) -> SparseContribution:
        """Return one immutable precomputed contribution after identity validation."""
        if self._messages.get(message.name) != message:
            raise ValueError(f"message {message.name} is not part of this cache")
        try:
            return self._by_candidate[(message.name, offset_us)]
        except KeyError as exc:
            raise ValueError(f"illegal offset {offset_us} for {message.name}") from exc

    def relocation(
        self, message: CanMessage, old_offset_us: int, new_offset_us: int
    ) -> SparseRelocation:
        """Build one exact sparse old-to-new contribution difference."""
        old = self.contribution(message, old_offset_us)
        new = self.contribution(message, new_offset_us)
        steady: dict[int, tuple[int, int]] = {
            slot: (-load, -count) for slot, load, count in old.steady
        }
        for slot, load, count in new.steady:
            previous_load, previous_count = steady.get(slot, (0, 0))
            steady[slot] = (previous_load + load, previous_count + count)
        startup = {slot: -load for slot, load in old.startup}
        for slot, load in new.startup:
            startup[slot] = startup.get(slot, 0) + load
        return SparseRelocation(
            steady=tuple(
                (slot, load, count)
                for slot, (load, count) in sorted(steady.items())
                if load or count
            ),
            startup=tuple(
                (slot, load)
                for slot, load in sorted(startup.items())
                if load
            ),
        )


class ReadOnlyTripleObjectiveEvaluator:
    """Evaluate exact Balanced metrics from sparse deltas without touching SearchState.

    The evaluator snapshots one complete state. It reuses private scratch arrays and is
    therefore intentionally single-threaded; candidate evaluation never reads or writes
    the formal ``SearchState`` after construction.
    """

    def __init__(
        self,
        state: SearchState,
        policy: ObjectivePolicy,
        contributions: TripleContributionCache,
    ) -> None:
        self._policy = policy
        self._contributions = contributions
        self._offsets = state.current_offsets.copy()
        if len(self._offsets) != len(state.messages):
            raise ValueError("incremental evaluation requires a complete assignment")
        self._steady_loads = tuple(state.steady_slot_loads)
        self._startup_loads = tuple(state.startup_slot_loads)
        self._steady_counts = tuple(state.steady_slot_counts)
        self._baseline = calculate_objective(
            self._steady_loads,
            self._startup_loads,
            self._steady_counts,
            policy,
        )
        self._steady_order = tuple(
            sorted(
                range(len(self._steady_loads)),
                key=lambda slot: (-self._steady_loads[slot], slot),
            )
        )
        self._startup_order = tuple(
            sorted(
                range(len(self._startup_loads)),
                key=lambda slot: (-self._startup_loads[slot], slot),
            )
        )
        self._count_order = tuple(
            sorted(
                range(len(self._steady_counts)),
                key=lambda slot: (-self._steady_counts[slot], slot),
            )
        )
        self._relocations: dict[tuple[str, int], SparseRelocation] = {}
        self._steady_deltas = [0] * len(self._steady_loads)
        self._count_deltas = [0] * len(self._steady_counts)
        self._startup_deltas = [0] * len(self._startup_loads)
        self._steady_marks = [0] * len(self._steady_loads)
        self._startup_marks = [0] * len(self._startup_loads)
        self._generation = 0

    @property
    def baseline(self) -> ObjectiveValue:
        """Return the exact objective of the snapshotted state."""
        return self._baseline

    def relocations_for(self, message: CanMessage) -> dict[int, SparseRelocation]:
        """Prepare and return all legal old-to-new relocations for one message."""
        try:
            old_offset = self._offsets[message.name]
        except KeyError as exc:
            raise ValueError(f"message {message.name} is absent from the snapshot") from exc
        prepared: dict[int, SparseRelocation] = {}
        for new_offset in message.allowed_offsets_us:
            key = (message.name, new_offset)
            relocation = self._relocations.get(key)
            if relocation is None:
                relocation = self._contributions.relocation(
                    message, old_offset, new_offset
                )
                self._relocations[key] = relocation
            prepared[new_offset] = relocation
        return prepared

    def evaluate(
        self,
        triplet: tuple[CanMessage, CanMessage, CanMessage],
        new_offsets_us: tuple[int, int, int],
    ) -> ObjectiveValue:
        """Evaluate one legal three-message assignment using the read-only snapshot."""
        if len({message.name for message in triplet}) != 3:
            raise ValueError("incremental triple evaluation requires three messages")
        relocations = tuple(
            self.relocations_for(message)[offset]
            for message, offset in zip(triplet, new_offsets_us, strict=True)
        )
        return self.evaluate_relocations(relocations[0], relocations[1], relocations[2])

    def evaluate_relocations(
        self,
        first: SparseRelocation,
        second: SparseRelocation,
        third: SparseRelocation,
    ) -> ObjectiveValue:
        """Evaluate three already-prepared relocations with reusable scratch storage."""
        self._generation += 1
        generation = self._generation
        steady_touched: list[int] = []
        startup_touched: list[int] = []
        for relocation in (first, second, third):
            for slot, load_delta, count_delta in relocation.steady:
                if self._steady_marks[slot] != generation:
                    self._steady_marks[slot] = generation
                    self._steady_deltas[slot] = 0
                    self._count_deltas[slot] = 0
                    steady_touched.append(slot)
                self._steady_deltas[slot] += load_delta
                self._count_deltas[slot] += count_delta
            for slot, load_delta in relocation.startup:
                if self._startup_marks[slot] != generation:
                    self._startup_marks[slot] = generation
                    self._startup_deltas[slot] = 0
                    startup_touched.append(slot)
                self._startup_deltas[slot] += load_delta

        violation_count = self._baseline.violation_count
        violation_excess = self._baseline.violation_excess
        steady_square = self._baseline.sum_square_load
        affected_steady_peak = 0
        affected_max_count = 0
        threshold = self._policy.load_threshold_us
        for slot in steady_touched:
            old_load = self._steady_loads[slot]
            new_load = old_load + self._steady_deltas[slot]
            old_count = self._steady_counts[slot]
            new_count = old_count + self._count_deltas[slot]
            if new_load < 0 or new_count < 0:
                raise ValueError("incremental relocation produced a negative steady slot")
            steady_square += new_load * new_load - old_load * old_load
            affected_steady_peak = max(affected_steady_peak, new_load)
            affected_max_count = max(affected_max_count, new_count)
            if threshold is not None:
                old_excess = max(0, old_load - threshold)
                new_excess = max(0, new_load - threshold)
                violation_count += int(new_excess > 0) - int(old_excess > 0)
                violation_excess += new_excess - old_excess

        startup_square = self._baseline.startup_sum_square_load
        affected_startup_peak = 0
        for slot in startup_touched:
            old_load = self._startup_loads[slot]
            new_load = old_load + self._startup_deltas[slot]
            if new_load < 0:
                raise ValueError("incremental relocation produced a negative startup slot")
            startup_square += new_load * new_load - old_load * old_load
            affected_startup_peak = max(affected_startup_peak, new_load)

        steady_peak = max(
            affected_steady_peak,
            self._unaffected_max(
                self._steady_loads,
                self._steady_order,
                self._steady_marks,
                generation,
            ),
        )
        startup_peak = max(
            affected_startup_peak,
            self._unaffected_max(
                self._startup_loads,
                self._startup_order,
                self._startup_marks,
                generation,
            ),
        )
        max_release_count = max(
            affected_max_count,
            self._unaffected_max(
                self._steady_counts,
                self._count_order,
                self._steady_marks,
                generation,
            ),
        )
        return ObjectiveValue(
            violation_count=violation_count,
            violation_excess=violation_excess,
            steady_peak=steady_peak,
            startup_peak=startup_peak,
            sum_square_load=steady_square,
            max_release_count=max_release_count,
            startup_sum_square_load=startup_square,
            mode=self._policy.mode,
            peak_budget_us=self._policy.peak_budget_us,
        )

    def prepare_pair(
        self,
        first: SparseRelocation,
        second: SparseRelocation,
    ) -> PairObjectiveSnapshot:
        """Materialize an immutable two-relocation snapshot reused by all third Offsets."""
        steady_loads = list(self._steady_loads)
        startup_loads = list(self._startup_loads)
        steady_counts = list(self._steady_counts)
        for relocation in (first, second):
            for slot, load_delta, count_delta in relocation.steady:
                steady_loads[slot] += load_delta
                steady_counts[slot] += count_delta
            for slot, load_delta in relocation.startup:
                startup_loads[slot] += load_delta
        if (
            any(load < 0 for load in steady_loads)
            or any(load < 0 for load in startup_loads)
            or any(count < 0 for count in steady_counts)
        ):
            raise ValueError("incremental pair relocation produced a negative slot")
        steady = tuple(steady_loads)
        startup = tuple(startup_loads)
        counts = tuple(steady_counts)
        return PairObjectiveSnapshot(
            steady_loads=steady,
            startup_loads=startup,
            steady_counts=counts,
            objective=calculate_objective(steady, startup, counts, self._policy),
            steady_order=tuple(
                sorted(range(len(steady)), key=lambda slot: (-steady[slot], slot))
            ),
            startup_order=tuple(
                sorted(range(len(startup)), key=lambda slot: (-startup[slot], slot))
            ),
            count_order=tuple(
                sorted(range(len(counts)), key=lambda slot: (-counts[slot], slot))
            ),
        )

    def evaluate_pair_with_relocation(
        self,
        pair: PairObjectiveSnapshot,
        third: SparseRelocation,
    ) -> ObjectiveValue:
        """Evaluate one third relocation against a reused exact pair snapshot."""
        if not third.steady and not third.startup:
            return pair.objective
        self._generation += 1
        generation = self._generation
        for slot, _, _ in third.steady:
            self._steady_marks[slot] = generation
        for slot, _ in third.startup:
            self._startup_marks[slot] = generation

        violation_count = pair.objective.violation_count
        violation_excess = pair.objective.violation_excess
        steady_square = pair.objective.sum_square_load
        affected_steady_peak = 0
        affected_max_count = 0
        threshold = self._policy.load_threshold_us
        for slot, load_delta, count_delta in third.steady:
            old_load = pair.steady_loads[slot]
            new_load = old_load + load_delta
            old_count = pair.steady_counts[slot]
            new_count = old_count + count_delta
            if new_load < 0 or new_count < 0:
                raise ValueError("incremental relocation produced a negative steady slot")
            steady_square += new_load * new_load - old_load * old_load
            affected_steady_peak = max(affected_steady_peak, new_load)
            affected_max_count = max(affected_max_count, new_count)
            if threshold is not None:
                old_excess = max(0, old_load - threshold)
                new_excess = max(0, new_load - threshold)
                violation_count += int(new_excess > 0) - int(old_excess > 0)
                violation_excess += new_excess - old_excess

        startup_square = pair.objective.startup_sum_square_load
        affected_startup_peak = 0
        for slot, load_delta in third.startup:
            old_load = pair.startup_loads[slot]
            new_load = old_load + load_delta
            if new_load < 0:
                raise ValueError("incremental relocation produced a negative startup slot")
            startup_square += new_load * new_load - old_load * old_load
            affected_startup_peak = max(affected_startup_peak, new_load)

        return ObjectiveValue(
            violation_count=violation_count,
            violation_excess=violation_excess,
            steady_peak=max(
                affected_steady_peak,
                self._unaffected_max(
                    pair.steady_loads,
                    pair.steady_order,
                    self._steady_marks,
                    generation,
                ),
            ),
            startup_peak=max(
                affected_startup_peak,
                self._unaffected_max(
                    pair.startup_loads,
                    pair.startup_order,
                    self._startup_marks,
                    generation,
                ),
            ),
            sum_square_load=steady_square,
            max_release_count=max(
                affected_max_count,
                self._unaffected_max(
                    pair.steady_counts,
                    pair.count_order,
                    self._steady_marks,
                    generation,
                ),
            ),
            startup_sum_square_load=startup_square,
            mode=self._policy.mode,
            peak_budget_us=self._policy.peak_budget_us,
        )

    @staticmethod
    def _unaffected_max(
        values: tuple[int, ...],
        ranked_slots: tuple[int, ...],
        marks: list[int],
        generation: int,
    ) -> int:
        for slot in ranked_slots:
            if marks[slot] != generation:
                return values[slot]
        return 0
