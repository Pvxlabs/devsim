from __future__ import annotations

from typing import Any

from ..models import ActionContext, ActionResult


class LifecycleAdapter:
    """Internal adapter for runner lifecycle markers."""

    name = "lifecycle"

    def __init__(self, action: str):
        self.action = action

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        return ActionResult(ok=True, data={"action": self.action})
