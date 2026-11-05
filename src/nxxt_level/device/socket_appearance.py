"""Presentation states for the physical MTTL-W01 outlet visualization.

The cover indicates *measured electrical load*, not physical plug insertion.
An unpowered or offline outlet cannot reveal whether a plug is inserted.
USB ports have no confirmed per-port telemetry and are excluded.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class SocketAppearance(str, Enum):
    UNKNOWN = "unknown"
    OFF = "off"
    ON_IDLE = "on_idle"
    ON_LOADED = "on_loaded"


def socket_appearance(
    reading: Mapping[str, Any] | None,
    *,
    online: bool,
    threshold_w: float = 2.0,
) -> SocketAppearance:
    """Derive a conservative UI state from a fresh per-outlet reading.

    ON_LOADED: show cover and orange glow.
    ON_IDLE: show uncovered socket and orange glow.
    OFF: show uncovered socket without glow.
    UNKNOWN: no authoritative telemetry; don't imply a relay or load state.
    """
    if threshold_w < 0:
        raise ValueError("Load threshold cannot be negative")
    if not online or not reading or not isinstance(reading.get("on"), bool):
        return SocketAppearance.UNKNOWN
    if not reading["on"]:
        return SocketAppearance.OFF
    power = reading.get("power_w")
    if not isinstance(power, (int, float)) or isinstance(power, bool):
        return SocketAppearance.UNKNOWN
    if not (float("-inf") < float(power) < float("inf")):
        return SocketAppearance.UNKNOWN
    return (
        SocketAppearance.ON_LOADED
        if power > 0 and power >= threshold_w
        else SocketAppearance.ON_IDLE
    )
