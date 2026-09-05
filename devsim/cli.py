from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import discover_scenarios, load_manifest
from .errors import DevSimError
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
    else:
        print("ok")
