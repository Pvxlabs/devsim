from __future__ import annotations

from typing import Any, Protocol

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class ActionAdapter(Protocol):
    name: str

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        ...


class AdapterRegistry:
    """Resolve complete public action names to adapters.

    The list constructor remains as a small compatibility convenience for the
    V1 ``http``/``command`` adapter names. New code should use ``register``
    with the complete action name.
    """

    def __init__(self, adapters: list[ActionAdapter] | None = None):
        self._actions: dict[str, ActionAdapter] = {}
        for adapter in adapters or []:
            if adapter.name == "http":
                self.register("api.request", adapter)
            elif adapter.name == "command":
                self.register("command.run", adapter)
            else:
                self.register(adapter.name, adapter)

    def register(self, action: str, adapter: ActionAdapter) -> None:
        if not isinstance(action, str) or not action.strip():
            raise AdapterError("adapter action name must be a non-empty string")
        action = action.strip()
        if action in self._actions:
            raise AdapterError(f"adapter action {action!r} is already registered")
        self._actions[action] = adapter

    def resolve(self, action: str) -> ActionAdapter:
        try:
            return self._actions[action]
        except KeyError as exc:
            raise AdapterError(f"action adapter {action!r} is not registered") from exc

    def get(self, name: str) -> ActionAdapter:
        # V1 compatibility for callers that looked up adapter names directly.
        if name == "api":
            name = "api.request"
        elif name == "http":
            name = "api.request"
        return self.resolve(name)

    def actions(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))
