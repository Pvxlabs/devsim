from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import RuntimeState


class StateStore:
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

    def save_run_event(self, run_id: str, event: dict[str, Any]) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{run_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

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
