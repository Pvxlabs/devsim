from __future__ import annotations

import argparse
from pathlib import Path

from .config import discover_scenarios, load_manifest
from .runner import ScenarioRunner
from .runtime import RuntimeOwnership
from .state import StateStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--max-duration-ms", type=int)
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    manifest = load_manifest(project_dir)
    scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
    scenario = scenarios[args.scenario]
    ownership = RuntimeOwnership(project_dir)
    runner = ScenarioRunner(project_dir, manifest.project_name, manifest.base_url, StateStore(project_dir), manifest.adapter_types)
    runner.run(scenario, args.seed, run_id=args.run_id, ownership=ownership, max_events=args.max_events, max_duration_ms=args.max_duration_ms)


if __name__ == "__main__":
    main()
