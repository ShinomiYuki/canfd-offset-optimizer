"""Resolve message-level CAN FD timing metadata without touching optimization."""

from __future__ import annotations

from .contracts import NetworkTimingConfig, TimingConfigSource


def resolve_effective_brs(
    dbc_brs: bool | None,
    dbc_brs_source: str | None,
    timing_config: NetworkTimingConfig | None,
) -> tuple[bool | None, str | None]:
    """Apply DBC-per-message precedence over the network default."""

    if dbc_brs is not None:
        return dbc_brs, dbc_brs_source or "dbc"
    if timing_config is None or timing_config.default_brs is None:
        return None, None
    source = (
        "dbc_network_default"
        if timing_config.brs_source is TimingConfigSource.DBC
        else "user_network_default"
    )
    return timing_config.default_brs, source
