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


def assert_database_url_safe(database_url: str) -> None:
    """Reject production-looking schema/seed targets before opening a connection."""
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg"} or not parsed.hostname:
        raise SafetyError(f"SEED_TARGET_UNSAFE: invalid PostgreSQL URL {database_url!r}")
    host = parsed.hostname
    database = parsed.path.lstrip("/").lower()
    suspicious = any(token in host.lower().split(".") for token in ("prod", "production", "live")) or any(
        token in database.split("-") for token in ("prod", "production", "live")
    )
    if suspicious or not _is_safe_host(host):
        raise SafetyError(f"SEED_TARGET_UNSAFE: PostgreSQL target {host}/{database} is not local/private development")


def assert_observation_url_safe(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _is_safe_host(parsed.hostname):
        raise SafetyError(f"BROWSER_TARGET_UNSAFE: observation URL {url!r} is not local/private development")
    host = (parsed.hostname or "").lower()
    if any(token in host.split(".") for token in ("prod", "production", "live")):
        raise SafetyError(f"BROWSER_TARGET_UNSAFE: observation URL {url!r} looks like production")
