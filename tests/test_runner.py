from pathlib import Path

from devsim.config import load_scenario
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
