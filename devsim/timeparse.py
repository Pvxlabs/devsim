from __future__ import annotations

import re

from .errors import ConfigError

_DURATION = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>ms|s|m|h)$")


def parse_duration(value: object, *, field: str = "duration", allow_hours: bool = False) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < 0:
            raise ConfigError(f"{field} must not be negative")
        return int(value * 1000)
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a duration such as 250ms, 2s, 1m, or 1h")
    match = _DURATION.fullmatch(value.strip())
    if not match:
        units = "ms, s, m, or h" if allow_hours else "ms, s, or m"
        raise ConfigError(f"invalid {field} {value!r}; use {units}")
    unit = match.group("unit")
    if unit == "h" and not allow_hours:
        raise ConfigError(f"invalid {field} {value!r}; use ms, s, or m")
    multiplier = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}[unit]
    return int(float(match.group("value")) * multiplier)
