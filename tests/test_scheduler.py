from pathlib import Path

from devsim.config import load_scenario
from devsim.scheduler import build_schedule


def test_schedule_is_stable_and_repeating_boundaries_are_inclusive(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """version: 1
name: stable
clock:
  speed: 1
timeline:
  - at: 2s
    action: lifecycle.start
  - every: 1s
    until: 3s
    action: command.run
    with:
      command: echo ok
  - at: 1s
    action: lifecycle.complete
""",
        encoding="utf-8",
    )
    events = build_schedule(load_scenario(scenario_path))
    assert [(event.virtual_ms, event.timeline_index, event.occurrence) for event in events] == [
        (1000, 1, 0),
        (1000, 2, 0),
        (2000, 0, 0),
        (2000, 1, 1),
        (3000, 1, 2),
    ]
