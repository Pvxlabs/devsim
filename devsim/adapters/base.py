from __future__ import annotations

from typing import Any, Protocol

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class ActionAdapter(Protocol):
    name: str

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        ...


class AdapterRegistry:
    def __init__(self, adapters: list[ActionAdapter]):
        self._adapters = {adapter.name: adapter for adapter in adapters}

    def get(self, name: str) -> ActionAdapter:
        if name == "api" and "http" in self._adapters:
            return self._adapters["http"]
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise AdapterError(f"adapter {name!r} is not configured") from exc
