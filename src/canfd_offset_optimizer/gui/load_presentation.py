"""Display-only transformations for immutable backend load arrays."""

from __future__ import annotations


STEADY_REPEAT_COUNTS = (1, 2, 4, 10)
DEFAULT_STEADY_REPEAT_COUNT = 4
CONGESTION_COLORS = (
    "#FFFFFF",
    "#B7E4C7",
    "#FFE082",
    "#FFB74D",
    "#EF5350",
    "#000000",
)
CONGESTION_LABELS = ("0 帧", "1 帧", "2 帧", "3 帧", "4 帧", "5 帧及以上")


def congestion_level(release_count: int) -> int:
    """Map release counts exactly like main reporting.congestion_plotter."""

    if release_count < 0:
        raise ValueError("release_count must be non-negative")
    if release_count <= 4:
        return release_count
    return 5


def validate_steady_repeat_count(repeat_count: int) -> int:
    if repeat_count not in STEADY_REPEAT_COUNTS:
        raise ValueError("unsupported steady repeat count")
    return repeat_count


def repeat_for_display(values: tuple[int, ...], repeat_count: int) -> tuple[int, ...]:
    """Return a new repeated tuple without mutating the backend DTO."""

    if repeat_count <= 0:
        raise ValueError("repeat_count must be positive")
    return tuple(value for _ in range(repeat_count) for value in values)


def time_coordinates(
    sample_count: int, slot_width_ms: float
) -> tuple[float, ...]:
    if sample_count < 0:
        raise ValueError("sample_count must be non-negative")
    if slot_width_ms <= 0:
        raise ValueError("slot_width_ms must be positive")
    return tuple(index * slot_width_ms for index in range(sample_count))
