from __future__ import annotations

import re

from .errors import ConfigError

_DURATION = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>ms|s|m)$")


def parse_duration(value: object, *, field: str = "duration") -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < 0:
            raise ConfigError(f"{field} must not be negative")
        return int(value * 1000)
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a duration such as 250ms, 2s, or 1m")
    match = _DURATION.fullmatch(value.strip())
    if not match:
        raise ConfigError(f"invalid {field} {value!r}; use ms, s, or m")
    multiplier = {"ms": 1, "s": 1000, "m": 60_000}[match.group("unit")]
    return int(float(match.group("value")) * multiplier)
