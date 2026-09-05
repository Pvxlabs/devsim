from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .context import environment_secret_values
from .errors import ScenarioError
from .models import RuntimeState
from .redaction import redact


class StateStore:
    max_event_bytes = 64 * 1024
    def __init__(self, project_dir: Path):
        self.directory = project_dir / ".devsim"
        self.path = self.directory / "state.json"
        self.runs_dir = self.directory / "runs"

    def load(self, project: str) -> RuntimeState:
        if not self.path.exists():
            return RuntimeState(project=project)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RuntimeState(project=project)
        return RuntimeState.from_dict(data, project)

    def save(self, state: RuntimeState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.path, state.to_dict())

    def save_run_event(self, run_id: str, event: dict[str, Any], *, secret_values: Iterable[str] = ()) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_path(run_id)
        safe_event = redact(event, set(environment_secret_values()) | {str(value) for value in secret_values})
        safe_event = self._bound_event(safe_event)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_event, sort_keys=True, separators=(",", ":")) + "\n")

    def _bound_event(self, event: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= self.max_event_bytes:
            return event
        bounded = dict(event)
        bounded["result_summary_truncated"] = True
        for key in ("payload", "result", "error", "expect"):
            if key in bounded:
                bounded[key] = _truncate_value(bounded[key], 2048)
        encoded = json.dumps(bounded, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self.max_event_bytes:
            bounded = {"type": event.get("type"), "status": event.get("status"), "run_id": event.get("run_id"), "sequence": event.get("sequence"), "result_summary_truncated": True}
        return bounded

    def run_path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
            raise ScenarioError(f"invalid run id {run_id!r}")
        return self.runs_dir / f"{run_id}.jsonl"

    def read_run_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.run_path(run_id)
        if not path.exists():
            raise ScenarioError(f"run artifact {run_id!r} was not found")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ScenarioError(f"cannot read run artifact {run_id!r}: {exc}") from exc
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ScenarioError(f"invalid JSON in run artifact {run_id!r} at line {line_number}") from exc
            if not isinstance(event, dict):
                raise ScenarioError(f"run artifact {run_id!r} line {line_number} is not an object")
            events.append(event)
        return events

    def reset_runtime(self, project: str) -> RuntimeState:
        state = RuntimeState(project=project, last_operation="scenario.reset")
        self.save(state)
        return state

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _truncate_value(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value[:limit] + ("...[truncated]" if len(value) > limit else "")
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, limit) for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return [_truncate_value(item, limit) for item in value[:100]]
    return value
