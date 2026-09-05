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
    paused_at_monotonic: float | None = None
    paused_real_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ConfigError("clock speed must be a positive number")

    @classmethod
    def start(cls, speed: float) -> "VirtualClock":
        return cls(speed, utc_now(), time.monotonic())

    def now_ms(self) -> int:
        if self.paused_at_monotonic is not None:
            return self.virtual_elapsed_ms
        elapsed = (time.monotonic() - self.real_started_monotonic - self.paused_real_seconds) * self.speed * 1000
        return max(self.virtual_elapsed_ms, int(elapsed))

    def pause(self) -> None:
        if self.paused_at_monotonic is None:
            self.virtual_elapsed_ms = self.now_ms()
            self.paused_at_monotonic = time.monotonic()

    def resume(self) -> None:
        if self.paused_at_monotonic is not None:
            self.paused_real_seconds += time.monotonic() - self.paused_at_monotonic
            self.paused_at_monotonic = None

    async def wait_until(self, target_ms: int, *, paused=None, stopped=None) -> bool:
        while True:
            if stopped is not None and stopped():
                return False
            is_paused = paused is not None and paused()
            if is_paused:
                self.pause()
                await asyncio.sleep(0.05)
                continue
            self.resume()
            remaining_virtual_ms = target_ms - self.now_ms()
            if remaining_virtual_ms <= 0:
                self.virtual_elapsed_ms = max(self.virtual_elapsed_ms, target_ms)
                return True
            await asyncio.sleep(min(0.1, remaining_virtual_ms / 1000 / self.speed))
