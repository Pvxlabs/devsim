from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from .errors import ContextError
from .models import ActionContext


_PLACEHOLDER = re.compile(r"\$\{([^{}]+)\}")


def resolve(value: Any, context: ActionContext) -> Any:
    """Resolve the intentionally small, non-executable scenario reference syntax."""
    if isinstance(value, dict):
        return {key: resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve(item, context) for item in value)
    if not isinstance(value, str):
        return value

    match = _PLACEHOLDER.fullmatch(value)
    if match:
        return lookup(match.group(1), context)

    return _PLACEHOLDER.sub(lambda item: str(lookup(item.group(1), context)), value)


def lookup(reference: str, context: ActionContext) -> Any:
    if reference.startswith("env."):
        name = reference[4:]
        if not name:
            raise ContextError("empty environment variable reference")
        try:
            return os.environ[name]
        except KeyError as exc:
            raise ContextError(f"environment variable {name!r} is not set") from exc

    if reference.startswith("run."):
        return _walk(context.run, reference[4:], f"run reference {reference!r}")

    if reference.startswith("steps."):
        remainder = reference[6:]
        step_id, separator, path = remainder.partition(".")
        if not step_id or not separator:
            raise ContextError(f"step reference {reference!r} must include a field path")
        if step_id not in context.steps:
            raise ContextError(f"step {step_id!r} has no completed result")
        return _walk(context.steps[step_id], path, f"step reference {reference!r}")

    raise ContextError(
        f"unsupported variable reference {reference!r}; use env.*, run.*, or steps.<id>.*"
    )


def _walk(value: Any, path: str, label: str) -> Any:
    current = value
    for part in path.split("."):
        if not part:
            raise ContextError(f"{label} contains an empty path segment")
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        raise ContextError(f"{label} could not resolve {part!r}")
    return current


def normalize_result(data: dict[str, Any]) -> dict[str, Any]:
    """Expose stable names for values that can be referenced by later steps."""
    normalized = dict(data)
    if "body" in normalized and "json" not in normalized:
        normalized["json"] = normalized["body"]
    if "returncode" in normalized and "exit_code" not in normalized:
        normalized["exit_code"] = normalized["returncode"]
    return normalized


def collect_secret_values(value: Any, *, parent_key: str = "") -> set[str]:
    """Collect values under obviously sensitive keys for artifact redaction."""
    values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_key(str(key)) and isinstance(item, (str, int, float)):
                text = str(item)
                if text:
                    values.add(text)
            values.update(collect_secret_values(item, parent_key=str(key)))
    elif isinstance(value, list):
        for item in value:
            values.update(collect_secret_values(item, parent_key=parent_key))
    elif parent_key and _is_sensitive_key(parent_key) and isinstance(value, (str, int, float)):
        text = str(value)
        if text:
            values.add(text)
    return values


def environment_secret_values() -> set[str]:
    return {
        value
        for key, value in os.environ.items()
        if _is_sensitive_key(key) and value
    }


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(token in normalized for token in ("password", "authorization", "token", "cookie", "secret", "apikey", "privatekey", "credential"))
