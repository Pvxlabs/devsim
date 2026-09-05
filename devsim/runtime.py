from __future__ import annotations

import json
import os
import signal
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ScenarioError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RuntimeOwnership:
    """Small single-project ownership record for a managed runtime."""

    def __init__(self, project_dir: Path):
        self.directory = project_dir / ".devsim" / "runtime"
        self.path = self.directory / "ownership.json"
        self.control_path = self.directory / "control.json"
        self.lock_path = self.directory / "owner.lock"

    def load(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def is_alive(self, metadata: dict[str, Any] | None = None) -> bool:
        metadata = metadata or self.load()
        if not metadata or not metadata.get("pid"):
            return False
        try:
            os.kill(int(metadata["pid"]), 0)
        except (OSError, ValueError):
            return False
        return True

    def claim(self, metadata: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        existing = self.load()
        if existing and existing.get("status") in {"RUNNING", "PAUSED", "STARTING"} and self.is_alive(existing):
            raise ScenarioError(f"runtime is already owned by pid {existing.get('pid')} (run {existing.get('run_id')})")
        if self.lock_path.exists():
            if existing and existing.get("status") in {"RUNNING", "PAUSED", "STARTING"} and not self.is_alive(existing):
                self.lock_path.unlink(missing_ok=True)
            elif not existing or existing.get("status") not in {"RUNNING", "PAUSED", "STARTING"}:
                self.lock_path.unlink(missing_ok=True)
            else:
                raise ScenarioError("runtime ownership lock is held")
        try:
            self.lock_path.mkdir()
        except FileExistsError as exc:
            raise ScenarioError("runtime ownership lock is held") from exc
        if existing and existing.get("status") in {"RUNNING", "PAUSED", "STARTING"}:
            existing["status"] = "STALE"
            self._write(existing)
        metadata = {"started_at": _now(), "heartbeat": _now(), **metadata}
        self._write(metadata)
        self.write_control("run")

    def update(self, **changes: Any) -> dict[str, Any]:
        current = self.load() or {}
        current.update(changes)
        current["heartbeat"] = _now()
        self._write(current)
        return current

    def write_control(self, command: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.control_path, {"command": command, "at": _now()})

    def control(self) -> str:
        try:
            return str(json.loads(self.control_path.read_text(encoding="utf-8")).get("command", "run"))
        except (OSError, json.JSONDecodeError):
            return "run"

    def request(self, command: str) -> dict[str, Any] | None:
        metadata = self.load()
        if not metadata:
            return None
        self.write_control(command)
        return metadata

    def clear(self) -> None:
        for path in (self.path, self.control_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if self.lock_path.is_dir():
            try:
                self.lock_path.rmdir()
            except OSError:
                # A concurrently finishing owner may already have removed it.
                pass

    def status(self) -> dict[str, Any] | None:
        metadata = self.load()
        if not metadata:
            return None
        result = dict(metadata)
        result["process_alive"] = self.is_alive(metadata)
        if result.get("status") in {"RUNNING", "PAUSED", "STARTING"} and not result["process_alive"]:
            result["status"] = "STALE"
        return result

    def _write(self, value: dict[str, Any]) -> None:
        self._atomic_write(self.path, value)

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def terminate_process(pid: int, timeout: float = 5.0) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True
