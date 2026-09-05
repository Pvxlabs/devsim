from __future__ import annotations

from urllib.parse import urlparse

from .errors import SafetyError
from .models import Manifest


def _is_safe_host(host: str | None) -> bool:
    if not host:
        return True
    host = host.lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127."):
        return True
    if "." not in host:
        # Local Docker service names such as `api` and `postgres`.
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        first, second = int(parts[0]), int(parts[1])
        return first == 10 or first == 127 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168)
    return False


def assert_safe(manifest: Manifest, operation: str) -> None:
    """Fail closed for operations that can alter application data."""
    if operation not in {"reset", "seed", "down"}:
        return
    mode = manifest.environment_mode.lower()
    if mode not in {"development", "dev", "test", "preview"}:
        raise SafetyError(f"refusing {operation}: environment.mode={manifest.environment_mode!r} is not a development mode")
    parsed = urlparse(manifest.base_url)
    host = parsed.hostname
    suspicious = host and any(token in host.lower().split(".") for token in ("prod", "production", "live"))
    if not _is_safe_host(host) or suspicious:
        raise SafetyError(f"refusing {operation}: runtime.base_url {manifest.base_url!r} is not a local/private development endpoint")
