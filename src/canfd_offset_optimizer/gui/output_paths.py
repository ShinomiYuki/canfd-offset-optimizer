"""Portable, short and deterministic GUI output path helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re


BATCH_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S_%f"
OUTPUT_STEM_MAX_LENGTH = 48
WINDOWS_SAFE_DBC_PATH_LENGTH = 240


def create_timestamped_batch_directory(
    root: Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Path:
    """Atomically create a batch directory whose name contains only a timestamp."""

    resolved_root = root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    instant = (clock or datetime.now)()
    collision_offset = 0
    while True:
        candidate = resolved_root / (
            instant + timedelta(microseconds=collision_offset)
        ).strftime(BATCH_TIMESTAMP_FORMAT)
        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            collision_offset += 1
            continue
        return candidate


def short_output_stem(value: str, *, max_length: int = OUTPUT_STEM_MAX_LENGTH) -> str:
    """Keep ordinary network names and bound unusually long artifact stems."""

    if max_length < 10:
        raise ValueError("output stem limit must leave room for a stable hash")
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._")
    cleaned = cleaned or "network"
    if len(cleaned) <= max_length:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    prefix = cleaned[: max_length - len(digest) - 1].rstrip("._-") or "network"
    return f"{prefix}_{digest}"


def windows_utf16_path_length(path: Path) -> int:
    """Return the Windows path length in UTF-16 code units, excluding the NUL."""

    return len(str(path.resolve(strict=False)).encode("utf-16-le")) // 2


def dbc_output_destination(
    dbc_directory: Path,
    source_file: str,
    network_display_name: str,
    network_id: str,
) -> Path:
    """Keep the source basename and isolate only an actual flat-name collision."""

    direct = dbc_directory / Path(source_file).name
    if not direct.exists():
        return direct
    collision_directory = short_output_stem(
        f"{network_display_name}_{network_id[-8:]}", max_length=32
    )
    return dbc_directory / collision_directory / Path(source_file).name
