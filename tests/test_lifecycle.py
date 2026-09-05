from pathlib import Path

import pytest

from devsim.errors import AdapterError
from devsim.lifecycle import Lifecycle
from devsim.models import CommandSpec, Manifest
from devsim.state import StateStore


def test_reset_runs_steps_in_canonical_order(tmp_path: Path) -> None:
    (tmp_path / "step.py").write_text(
        """import os
from pathlib import Path
path = Path('steps.txt')
path.write_text(path.read_text() + os.environ['STEP'] + ',' if path.exists() else os.environ['STEP'] + ',')
""",
        encoding="utf-8",
    )
    commands = {name: CommandSpec("python step.py", env={"STEP": name}) for name in ("reset", "migrate")}
    manifest = Manifest(1, "sample", "development", "postgres", commands, CommandSpec("python step.py", env={"STEP": "seed"}), "scenarios", "http://127.0.0.1:8000", ("http", "command"))
    state = Lifecycle(tmp_path, manifest, StateStore(tmp_path)).run("reset", seed=42)
    assert state.status == "idle"
    assert (tmp_path / "steps.txt").read_text(encoding="utf-8") == "reset,migrate,seed,"


def test_failed_step_stops_reset(tmp_path: Path) -> None:
    commands = {
        "reset": CommandSpec("python -c \"raise SystemExit(7)\""),
        "migrate": CommandSpec("python -c \"raise SystemExit(8)\""),
    }
    manifest = Manifest(1, "sample", "development", "postgres", commands, CommandSpec("python -c \"raise SystemExit(9)\""), "scenarios", "http://127.0.0.1:8000", ("http", "command"))
    with pytest.raises(AdapterError):
        Lifecycle(tmp_path, manifest, StateStore(tmp_path)).run("reset")
    assert StateStore(tmp_path).load("sample").status == "failed"
