from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import ConfigError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class VirtualClock:
    speed: float
    virtual_started_at: str
    real_started_monotonic: float
    virtual_elapsed_ms: int = 0

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ConfigError("clock speed must be a positive number")

    @classmethod
    def start(cls, speed: float) -> "VirtualClock":
        return cls(speed, utc_now(), time.monotonic())

    def now_ms(self) -> int:
        elapsed = (time.monotonic() - self.real_started_monotonic) * self.speed * 1000
        return max(self.virtual_elapsed_ms, int(elapsed))

    async def wait_until(self, target_ms: int) -> None:
        remaining_virtual_ms = target_ms - self.now_ms()
        if remaining_virtual_ms > 0:
            await asyncio.sleep(remaining_virtual_ms / 1000 / self.speed)
        self.virtual_elapsed_ms = max(self.virtual_elapsed_ms, target_ms)
