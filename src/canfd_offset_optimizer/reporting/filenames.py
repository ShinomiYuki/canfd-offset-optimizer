"""! @file filenames.py
@brief Build stable, filesystem-safe network prefixes for report artifacts.
"""

from __future__ import annotations

import re
from pathlib import Path


_NETWORK_BEFORE_MESSAGE_LIST = re.compile(
    r"(?:^|[_\s])([A-Za-z0-9]+)\s+Message\s+list(?:\s|$)", re.IGNORECASE
)


def infer_report_prefix(dbc_path: Path, fallback: str) -> str:
    """! @brief Infer a network label from a communication-matrix DBC filename."""
    match = _NETWORK_BEFORE_MESSAGE_LIST.search(dbc_path.stem)
    candidate = match.group(1).upper() if match else fallback
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("_.-")
    return cleaned or "network"


def prefixed_report_name(filename: str, report_prefix: str | None) -> str:
    """! @brief Prefix a report filename while keeping direct writer use optional."""
    return f"{report_prefix}_{filename}" if report_prefix else filename
