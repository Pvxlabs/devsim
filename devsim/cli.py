from __future__ import annotations

import argparse
import json
import sys
import os
import shutil
import subprocess
import uuid
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from . import __version__
from .config import discover_scenarios, load_manifest
from .errors import DevSimError, ScenarioChangedError, ScenarioError
from .lifecycle import Lifecycle
from .runner import ScenarioRunner
from .state import StateStore
from .clock import utc_now
from .runner import ScenarioRunner
from .runtime import RuntimeOwnership


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
    doctor = subparsers.add_parser("doctor")
    _add_json_flag(doctor)
    scenario = subparsers.add_parser("scenario")
    _add_json_flag(scenario)
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    scenario_list = scenario_sub.add_parser("list")
    _add_json_flag(scenario_list)
    run = scenario_sub.add_parser("run")
    _add_json_flag(run)
    run.add_argument("name")
    run.add_argument("--seed", type=int, default=0)
    start = scenario_sub.add_parser("start")
    _add_json_flag(start)
    start.add_argument("name")
    start.add_argument("--seed", type=int, default=0)
    start.add_argument("--max-events", type=int)
    start.add_argument("--max-duration")
    scenario_stop = scenario_sub.add_parser("stop")
    _add_json_flag(scenario_stop)
    scenario_reset = scenario_sub.add_parser("reset")
    _add_json_flag(scenario_reset)
    scenario_pause = scenario_sub.add_parser("pause")
    _add_json_flag(scenario_pause)
    scenario_resume = scenario_sub.add_parser("resume")
    _add_json_flag(scenario_resume)
    validate = scenario_sub.add_parser("validate")
    _add_json_flag(validate)
    validate.add_argument("name", nargs="?")
    validate.add_argument("--all", action="store_true")
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
    ownership = RuntimeOwnership(project_dir)
    if args.command in {"up", "down", "reset", "seed"}:
        state = Lifecycle(project_dir, manifest, store).run(args.command, seed=getattr(args, "seed", 0))
        return {"ok": True, "operation": args.command, "state": state.to_dict()}
    if args.command == "status":
        return status_result(project_dir, manifest, store, ownership)
    if args.command == "doctor":
        return doctor_result(project_dir, manifest, store, ownership)
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
        if args.scenario_command == "start":
            scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
            if args.name not in scenarios:
                raise DevSimError(f"scenario {args.name!r} was not found")
            scenario = scenarios[args.name]
            if scenario.runtime_mode != "persistent":
                raise ScenarioError(f"scenario {args.name!r} is finite; use scenario run")
            current = ownership.status()
            if current and current.get("status") in {"RUNNING", "PAUSED", "STARTING"} and current.get("process_alive"):
                raise ScenarioError(f"runtime is already running (run {current.get('run_id')})")
            run_id = str(uuid.uuid4())
            command = [sys.executable, "-m", "devsim.runtime_process", "--project-dir", str(project_dir), "--scenario", args.name, "--seed", str(args.seed), "--run-id", run_id]
            if args.max_events is not None:
                command += ["--max-events", str(args.max_events)]
            if args.max_duration:
                from .timeparse import parse_duration
                command += ["--max-duration-ms", str(parse_duration(args.max_duration, field="--max-duration", allow_hours=True))]
            ownership.claim({"run_id": run_id, "pid": 0, "scenario": scenario.name, "scenario_hash": scenario.content_hash, "seed": args.seed, "status": "STARTING"})
            state = store.load(manifest.project_name)
            state.status = "running"; state.scenario = scenario.name; state.seed = args.seed; state.run_id = run_id; state.scenario_hash = scenario.content_hash; state.scenario_version = scenario.version; state.started_at = utc_now(); state.clock_speed = scenario.speed; state.last_operation = "scenario.start"; state.heartbeat = utc_now(); store.save(state)
            try:
                process = subprocess.Popen(command, cwd=project_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                ownership.clear()
                raise
            ownership.update(pid=process.pid)
            return {"ok": True, "operation": "scenario.start", "scenario": scenario.name, "run_id": run_id, "pid": process.pid, "state": state.to_dict()}
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
            if state.status in {"running", "paused"}:
                state.stop_requested = True
                state.last_operation = "scenario.stop"
                store.save(state)
            if ownership.status() and ownership.status().get("process_alive"):
                ownership.request("stop")
            return {"ok": True, "operation": "scenario.stop", "state": state.to_dict()}
        if args.scenario_command in {"pause", "resume"}:
            state = store.load(manifest.project_name)
            if not ownership.status() or not ownership.status().get("process_alive"):
                raise ScenarioError("no managed runtime is running")
            command = "pause" if args.scenario_command == "pause" else "run"
            ownership.request(command)
            state.status = "paused" if command == "pause" else "running"; state.last_operation = f"scenario.{args.scenario_command}"; store.save(state)
            return {"ok": True, "operation": f"scenario.{args.scenario_command}", "state": state.to_dict()}
        if args.scenario_command == "validate":
            return validate_scenarios(project_dir, manifest, args.name, args.all)
        state = store.reset_runtime(manifest.project_name)
        ownership.clear()
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


def status_result(project_dir: Path, manifest, store: StateStore, ownership: RuntimeOwnership) -> dict[str, Any]:
    state = store.load(manifest.project_name)
    runtime = ownership.status()
    if runtime and runtime.get("status") == "STALE" and state.status in {"running", "paused"}:
        state.status = "stale"
    result = state.to_dict()
    result["runtime"] = runtime
    result["process_alive"] = bool(runtime and runtime.get("process_alive"))
    result["heartbeat_age"] = _heartbeat_age(runtime.get("heartbeat")) if runtime else None
    result["environment"] = manifest.environment_mode
    result["next_event"] = state.next_event
    return {"ok": True, "state": result}


def _heartbeat_age(value: str | None) -> float | None:
    if not value:
        return None
    from datetime import datetime, timezone
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        return None


def doctor_result(project_dir: Path, manifest, store: StateStore, ownership: RuntimeOwnership) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})
    check("manifest", "PASS", "devsim.yaml is valid")
    scenario_dir = project_dir / manifest.scenarios_path
    check("scenario_root", "PASS" if scenario_dir.is_dir() and os.access(scenario_dir, os.R_OK) else "FAIL", str(scenario_dir))
    runtime_dir = project_dir / ".devsim" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        check("runtime_directory", "PASS" if os.access(runtime_dir, os.W_OK) else "FAIL", str(runtime_dir))
    except OSError as exc:
        check("runtime_directory", "FAIL", str(exc))
    parsed = urlparse(manifest.base_url)
    check("base_url", "PASS" if parsed.scheme in {"http", "https"} and parsed.netloc else "FAIL", manifest.base_url)
    missing = []
    for spec in manifest.lifecycle.values():
        command = spec.command.strip().split()[0] if spec.command.strip() else ""
        if command and shutil.which(command) is None and command not in {"bash", "sh", "python", "python3"}:
            missing.append(command)
    detail = "available" if not missing else f"not found: {', '.join(sorted(set(missing)))}"
    check("lifecycle_commands", "PASS" if not missing else "WARN", detail)
    runtime = ownership.status()
    check("stale_runtime", "WARN" if runtime and runtime.get("status") == "STALE" else "PASS", runtime.get("status", "none") if runtime else "no managed runtime")
    ok = not any(item["status"] == "FAIL" for item in checks)
    return {"ok": ok, "checks": checks, "status": "PASS" if ok else "FAIL"}


def validate_scenarios(project_dir: Path, manifest, name: str | None, all_scenarios: bool) -> dict[str, Any]:
    scenarios = discover_scenarios(project_dir, manifest)
    if name and not all_scenarios:
        scenarios = [scenario for scenario in scenarios if scenario.name == name]
        if not scenarios:
            raise ScenarioError(f"scenario {name!r} was not found")
    errors: list[dict[str, str]] = []
    for scenario in scenarios:
        try:
            runner = ScenarioRunner(project_dir, manifest.project_name, manifest.base_url, StateStore(project_dir), manifest.adapter_types)
            for item in scenario.timeline:
                if item.action not in runner.registry.actions():
                    raise ScenarioError(f"action adapter {item.action!r} is not registered")
        except Exception as exc:
            errors.append({"scenario": scenario.name, "message": str(exc)})
    return {"ok": not errors, "scenarios": [{"name": item.name, "hash": item.content_hash, "valid": not any(e["scenario"] == item.name for e in errors)} for item in scenarios], "errors": errors}


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
