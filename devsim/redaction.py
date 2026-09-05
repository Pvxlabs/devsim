from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


SENSITIVE = "[REDACTED]"


def redact(value: Any, secret_values: Iterable[str] = ()) -> Any:
    secrets = sorted({item for item in secret_values if len(str(item)) >= 4}, key=len, reverse=True)
    if isinstance(value, Mapping):
        return {
            key: SENSITIVE if _is_sensitive_key(str(key)) else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, SENSITIVE)
        return result
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(token in normalized for token in ("password", "authorization", "token", "cookie", "secret", "apikey", "privatekey", "credential"))
