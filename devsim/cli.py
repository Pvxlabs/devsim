from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import discover_scenarios, load_manifest
from .errors import DevSimError, ScenarioChangedError, ScenarioError
from .lifecycle import Lifecycle
from .runner import ScenarioRunner
from .state import StateStore
from .clock import utc_now


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devsim", description="Deterministic preview runtime")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit stable machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    _add_json_flag(init)
    for name in ("up", "down", "reset", "seed", "status"):
        command = subparsers.add_parser(name)
        _add_json_flag(command)
        if name in {"reset", "seed"}:
            command.add_argument("--seed", type=int, default=0)
    scenario = subparsers.add_parser("scenario")
    _add_json_flag(scenario)
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    scenario_list = scenario_sub.add_parser("list")
    _add_json_flag(scenario_list)
    run = scenario_sub.add_parser("run")
    _add_json_flag(run)
    run.add_argument("name")
    run.add_argument("--seed", type=int, default=0)
    scenario_stop = scenario_sub.add_parser("stop")
    _add_json_flag(scenario_stop)
    scenario_reset = scenario_sub.add_parser("reset")
    _add_json_flag(scenario_reset)
    scenario_inspect = scenario_sub.add_parser("inspect")
    _add_json_flag(scenario_inspect)
    scenario_inspect.add_argument("run_id")
    scenario_replay = scenario_sub.add_parser("replay")
    _add_json_flag(scenario_replay)
    scenario_replay.add_argument("run_id")
    scenario_replay.add_argument("--allow-changed-scenario", action="store_true")
    clock = subparsers.add_parser("clock")
    _add_json_flag(clock)
    clock_sub = clock.add_subparsers(dest="clock_command", required=True)
    clock_status = clock_sub.add_parser("status")
    _add_json_flag(clock_status)
    return parser


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS preserves a top-level --json value when the flag appears before the command.
    parser.add_argument("--json", action="store_true", dest="json_output", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
        emit(result, args.json_output)
    except (DevSimError, OSError) as exc:
        error = {"ok": False, "error": {"code": getattr(exc, "code", "runtime_error"), "message": str(exc)}}
        emit(error, args.json_output)
        raise SystemExit(1) from exc


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    project_dir = args.project_dir.resolve()
    if args.command == "init":
        return init_project(project_dir)
    manifest = load_manifest(project_dir)
    store = StateStore(project_dir)
    if args.command in {"up", "down", "reset", "seed"}:
        state = Lifecycle(project_dir, manifest, store).run(args.command, seed=getattr(args, "seed", 0))
        return {"ok": True, "operation": args.command, "state": state.to_dict()}
    if args.command == "status":
        return {"ok": True, "state": store.load(manifest.project_name).to_dict()}
    if args.command == "scenario":
        if args.scenario_command == "list":
            scenarios = discover_scenarios(project_dir, manifest)
            return {
                "ok": True,
                "scenarios": [
                    {"name": item.name, "description": item.description, "version": item.version, "hash": item.content_hash}
                    for item in scenarios
                ],
            }
        if args.scenario_command == "run":
            scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
            if args.name not in scenarios:
                raise DevSimError(f"scenario {args.name!r} was not found")
            state = ScenarioRunner(
                project_dir,
                manifest.project_name,
                manifest.base_url,
                store,
                manifest.adapter_types,
            ).run(scenarios[args.name], args.seed)
            return {"ok": True, "scenario": args.name, "state": state.to_dict()}
        if args.scenario_command == "inspect":
            return inspect_run(store, args.run_id)
        if args.scenario_command == "replay":
            events = store.read_run_events(args.run_id)
            identity = _run_identity(events, args.run_id)
            scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
            scenario = scenarios.get(identity["scenario"])
            if scenario is None:
                raise ScenarioError(f"scenario {identity['scenario']!r} from run {args.run_id!r} was not found")
            if scenario.content_hash != identity["scenario_hash"] and not args.allow_changed_scenario:
                raise ScenarioChangedError(
                    f"scenario {scenario.name!r} changed: run has {identity['scenario_hash']}, current is {scenario.content_hash}"
                )
            state = ScenarioRunner(
                project_dir,
                manifest.project_name,
                manifest.base_url,
                store,
                manifest.adapter_types,
            ).run(scenario, identity["seed"])
            return {
                "ok": True,
                "scenario": scenario.name,
                "replay_of": args.run_id,
                "allow_changed_scenario": args.allow_changed_scenario,
                "state": state.to_dict(),
            }
        if args.scenario_command == "stop":
            state = store.load(manifest.project_name)
            if state.status == "running":
                state.stop_requested = True
                state.last_operation = "scenario.stop"
                store.save(state)
            return {"ok": True, "operation": "scenario.stop", "state": state.to_dict()}
        state = store.reset_runtime(manifest.project_name)
        return {"ok": True, "operation": "scenario.reset", "state": state.to_dict()}
    if args.command == "clock" and args.clock_command == "status":
        state = store.load(manifest.project_name)
        return {
            "ok": True,
            "clock": {
                "speed": state.clock_speed,
                "virtual_started_at": state.virtual_started_at,
                "virtual_time_ms": state.virtual_time_ms,
                "status": state.status,
                "observed_at": utc_now(),
            },
        }
    raise DevSimError("unknown command")


def inspect_run(store: StateStore, run_id: str) -> dict[str, Any]:
    events = store.read_run_events(run_id)
    identity = _run_identity(events, run_id)
    terminal = [event for event in events if event.get("status") in {"completed", "failed"}]
    completed = next((event for event in reversed(terminal) if event.get("status") == "completed"), None)
    failed = next((event for event in reversed(terminal) if event.get("status") == "failed"), None)
    return {
        "ok": True,
        "run_id": run_id,
        "scenario": identity["scenario"],
        "scenario_hash": identity["scenario_hash"],
        "seed": identity["seed"],
        "event_count": len(terminal),
        "raw_event_count": len(events),
        "started": events[0].get("real_time") if events else None,
        "completed": completed is not None and failed is None,
        "failed": failed is not None,
        "completed_at": completed.get("real_time") if completed else None,
        "failed_at": failed.get("real_time") if failed else None,
    }


def _run_identity(events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    if not events:
        raise ScenarioError(f"run artifact {run_id!r} is empty")
    event = events[0]
    required = ("scenario", "scenario_hash", "seed")
    missing = [key for key in required if key not in event]
    if missing:
        raise ScenarioError(f"run artifact {run_id!r} lacks scenario identity: {', '.join(missing)}")
    return {key: event[key] for key in required}


def init_project(project_dir: Path) -> dict[str, Any]:
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project_dir / "devsim.yaml"
    if manifest_path.exists():
        raise DevSimError(f"refusing to overwrite existing {manifest_path}")
    manifest_path.write_text(
        """version: 1\nproject:\n  name: example-app\nenvironment:\n  mode: development\ndatabase:\n  engine: postgres\n  lifecycle:\n    up:\n      command: docker compose up -d postgres\n    migrate:\n      command: python scripts/migrate.py\n    reset:\n      command: python scripts/reset_database.py\n    down:\n      command: docker compose down\nseed:\n  command: python devsim/seed.py\nscenarios:\n  path: devsim/scenarios\nruntime:\n  base_url: http://127.0.0.1:8000\n  adapters:\n    - type: http\n    - type: command\n""",
        encoding="utf-8",
    )
    StateStore(project_dir).directory.mkdir(parents=True, exist_ok=True)
    scenarios_dir = project_dir / "devsim" / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    gitignore_path = project_dir / ".gitignore"
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    if ".devsim/" not in {line.strip() for line in existing.splitlines()}:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitignore_path.write_text(f"{existing}{separator}.devsim/\n", encoding="utf-8")
    return {"ok": True, "initialized": str(manifest_path)}


def emit(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True))
        return
    if not value.get("ok"):
        print(f"error: {value['error']['message']}", file=sys.stderr)
        return
    if "state" in value:
        state = value["state"]
        print(f"{value.get('operation', value.get('scenario', 'status'))}: {state['status']}")
        if state.get("error"):
            print(f"error: {state['error']['message']}")
    elif "scenarios" in value:
        for scenario in value["scenarios"]:
            print(scenario["name"])
    elif "clock" in value:
        clock = value["clock"]
        print(f"clock: {clock['status']} at {clock['virtual_time_ms']}ms ({clock['speed']}x)")
    elif "event_count" in value:
        print(f"{value['scenario']}: {value['event_count']} events ({'failed' if value['failed'] else 'completed' if value['completed'] else 'incomplete'})")
    else:
        print("ok")
