import json
from pathlib import Path

import pytest

from devsim.cli import dispatch
from devsim.errors import ScenarioChangedError


def test_init_creates_manifest_and_state_directory(tmp_path: Path) -> None:
    result = dispatch(type("Args", (), {"command": "init", "project_dir": tmp_path})())
    assert result["ok"] is True
    assert (tmp_path / "devsim.yaml").exists()
    assert (tmp_path / ".devsim").is_dir()
    assert ".devsim/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / "devsim" / "scenarios").is_dir()


def test_status_json_shape_is_serializable(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        """version: 1
project: {name: sample}
database: {engine: postgres}
runtime: {base_url: http://127.0.0.1:8000}
""",
        encoding="utf-8",
    )
    result = dispatch(type("Args", (), {"command": "status", "project_dir": tmp_path})())
    assert json.loads(json.dumps(result))["state"]["project"] == "sample"


def write_replay_project(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        """version: 1
project: {name: sample}
database: {engine: postgres}
scenarios: {path: scenarios}
runtime: {base_url: http://127.0.0.1:8000}
""",
        encoding="utf-8",
    )
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "demo.yaml").write_text(
        """version: 1
name: demo
clock: {speed: 1000}
timeline:
  - at: 0ms
    action: command.run
    with:
      command: 'printf "%s" "$DEVSIM_SEED"'
    expect: {exit_code: 0}
""",
        encoding="utf-8",
    )


def args(tmp_path: Path, scenario_command: str, **values: object):
    defaults = {"command": "scenario", "scenario_command": scenario_command, "project_dir": tmp_path}
    defaults.update(values)
    return type("Args", (), defaults)()


def test_inspect_and_replay_preserve_seed_and_identity(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    run_result = dispatch(args(tmp_path, "run", name="demo", seed=42))
    run_id = run_result["state"]["run_id"]
    inspected = dispatch(args(tmp_path, "inspect", run_id=run_id))
    assert inspected["scenario"] == "demo"
    assert inspected["seed"] == 42
    assert inspected["event_count"] == 1
    assert inspected["completed"] is True

    replayed = dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=False))
    assert replayed["state"]["seed"] == 42
    assert replayed["state"]["run_id"] != run_id


def test_replay_fails_closed_when_scenario_changed(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    run_id = dispatch(args(tmp_path, "run", name="demo", seed=7))["state"]["run_id"]
    scenario_path = tmp_path / "scenarios" / "demo.yaml"
    scenario_path.write_text(scenario_path.read_text(encoding="utf-8") + "description: changed\n", encoding="utf-8")
    with pytest.raises(ScenarioChangedError, match="scenario .* changed"):
        dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=False))
    replayed = dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=True))
    assert replayed["allow_changed_scenario"] is True


def test_run_id_path_traversal_is_rejected(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    with pytest.raises(Exception, match="invalid run id"):
        dispatch(args(tmp_path, "inspect", run_id="../state"))
