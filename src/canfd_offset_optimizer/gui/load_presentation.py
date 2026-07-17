"""Display-only transformations for immutable backend load arrays."""

from __future__ import annotations


SLOT_WIDTH_MS = 5
STEADY_HYPERPERIOD_MS = 500
DISPLAY_DURATIONS_MS = (500, 1_000, 2_000, 5_000)
DEFAULT_DISPLAY_DURATION_MS = 2_000


def steady_repeat_count(display_duration_ms: int) -> int:
    if display_duration_ms not in DISPLAY_DURATIONS_MS:
        raise ValueError("unsupported steady display duration")
    if display_duration_ms % STEADY_HYPERPERIOD_MS:
        raise ValueError("steady display duration must be a 500 ms multiple")
    return display_duration_ms // STEADY_HYPERPERIOD_MS


def repeat_for_display(values: tuple[int, ...], repeat_count: int) -> tuple[int, ...]:
    """Return a new repeated tuple without mutating the backend DTO."""

    if repeat_count <= 0:
        raise ValueError("repeat_count must be positive")
    return tuple(value for _ in range(repeat_count) for value in values)


def time_coordinates(sample_count: int) -> tuple[int, ...]:
    return tuple(index * SLOT_WIDTH_MS for index in range(sample_count))
