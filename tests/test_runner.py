from pathlib import Path

import pytest
import json

from devsim.config import load_scenario
from devsim.errors import ExpectationError
from devsim.runner import ScenarioRunner
from devsim.state import StateStore


def test_runner_records_deterministic_event_order(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: command-run
clock:
  speed: 1000
timeline:
  - at: 0ms
    action: lifecycle.start
  - at: 1ms
    action: command.run
    with:
      command: printf '%s' "$DEVSIM_SEED"
  - at: 2ms
    action: lifecycle.complete
""",
        encoding="utf-8",
    )
    store = StateStore(tmp_path)
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", store, ("http", "command")).run(load_scenario(scenario_path), 42)
    assert state.status == "completed"
    assert state.event_sequence == 3
    events = (tmp_path / ".devsim" / "runs" / f"{state.run_id}.jsonl").read_text(encoding="utf-8").splitlines()
    assert '"sequence":1' in events[0]
    assert '"sequence":2' in events[2]
    for line in events:
        event = json.loads(line)
        assert {"run_id", "sequence", "scenario", "scenario_hash", "seed", "virtual_time", "real_time", "action", "step_id", "status"} <= set(event)


def test_runner_resolves_step_context_and_assertions(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: context-run
clock: {speed: 1000}
timeline:
  - at: 0ms
    id: create
    action: command.run
    with:
      command: "printf 'created-7'"
    expect: {exit_code: 0}
  - at: 1ms
    id: use
    action: command.run
    with:
      command: "test '${steps.create.stdout}' = 'created-7'"
    expect: {exit_code: 0}
""",
        encoding="utf-8",
    )
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(
        load_scenario(scenario_path), 42
    )
    assert state.status == "completed"


def test_runner_fails_when_expectation_does_not_match(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: assertion-fails
clock: {speed: 1000}
timeline:
  - at: 0ms
    action: command.run
    with: {command: "true"}
    expect: {exit_code: 1}
""",
        encoding="utf-8",
    )
    with pytest.raises(ExpectationError):
        ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(
            load_scenario(scenario_path), 42
        )
    assert StateStore(tmp_path).load("sample").status == "failed"


def test_runner_accepts_expected_nonzero_command_exit_code(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: expected-command-failure
clock: {speed: 1000}
timeline:
  - at: 0ms
    action: command.run
    with: {command: "exit 3"}
    expect: {exit_code: 3}
""",
        encoding="utf-8",
    )
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(
        load_scenario(scenario_path), 42
    )
    assert state.status == "completed"


def test_runner_redacts_sensitive_artifact_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "environment-secret-token")
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: redaction
clock: {speed: 1000}
timeline:
  - at: 0ms
    id: secret-step
    action: command.run
    with:
      command: "printf '%s' '${env.API_TOKEN}'"
      env: {token: environment-secret-token}
""",
        encoding="utf-8",
    )
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(
        load_scenario(scenario_path), 42
    )
    artifact = (tmp_path / ".devsim" / "runs" / f"{state.run_id}.jsonl").read_text(encoding="utf-8")
    assert "environment-secret-token" not in artifact
    assert "[REDACTED]" in artifact
