from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ..models import ActionContext, ActionResult


class ContextAdapter:
    def __init__(self, operation: str):
        self.name = operation
        self.operation = operation

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        key = payload.get("key")
        if not isinstance(key, str) or not key.strip():
            raise AdapterError(f"{self.operation} requires with.key")
        key = key.strip()
        if self.operation == "context.set":
            if "value" not in payload:
                raise AdapterError("context.set requires with.value")
            context.values[key] = payload["value"]
        elif self.operation == "context.increment":
            amount = payload.get("amount", 1)
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise AdapterError("context.increment with.amount must be numeric")
            current = context.values.get(key, 0)
            if not isinstance(current, (int, float)) or isinstance(current, bool):
                raise AdapterError(f"context value {key!r} is not numeric")
            context.values[key] = current + amount
        else:
            context.values.pop(key, None)
        return ActionResult(True, {"key": key, "value": context.values.get(key)})


class ValueAdapter:
    name = "value.generate"

    async def execute(self, context: ActionContext, payload: dict[str, Any]) -> ActionResult:
        kind = payload.get("type")
        if kind == "integer":
            minimum, maximum = payload.get("min"), payload.get("max")
            if not all(isinstance(value, int) and not isinstance(value, bool) for value in (minimum, maximum)):
                raise AdapterError("value.generate integer requires integer min and max")
            value = context.rng.randint(minimum, maximum)
        elif kind == "float":
            minimum, maximum = payload.get("min"), payload.get("max")
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (minimum, maximum)):
                raise AdapterError("value.generate float requires numeric min and max")
            value = context.rng.uniform(float(minimum), float(maximum))
        elif kind == "choice":
            choices = payload.get("choices", payload.get("values"))
            if not isinstance(choices, list) or not choices:
                raise AdapterError("value.generate choice requires a non-empty choices list")
            value = context.rng.choice(choices)
        elif kind == "uuid":
            value = context.rng.uuid()
        else:
            raise AdapterError("value.generate type must be integer, float, choice, or uuid")
        return ActionResult(True, {"value": value, "type": kind})
