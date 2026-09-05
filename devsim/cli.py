from __future__ import annotations

import argparse
import json
import sys
import os
import re
import shutil
import subprocess
import sysconfig
import uuid
import webbrowser
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from . import __version__
from .config import discover_scenarios, load_manifest
from .errors import ConfigError, DevSimError, ScenarioChangedError, ScenarioError
from .lifecycle import Lifecycle
from .state import StateStore
from .clock import utc_now
from .runner import ScenarioRunner
from .runtime import RuntimeOwnership
from .product import capabilities as capabilities_result
from .product import detect_project, init_plan, inspect_draft, project_status, validate_project


_STABLE_ERROR_CODES = {
    "SCENARIO_CHANGED",
    "SEED_TARGET_UNSAFE",
    "SEED_SCHEMA_DRIFT",
    "CYCLIC_SEED_DEPENDENCY",
    "BROWSER_ADAPTER_UNAVAILABLE",
    "BROWSER_OBSERVATION_CONFIG_REQUIRED",
    "BROWSER_TARGET_UNSAFE",
    "RUNTIME_ALREADY_RUNNING",
    "RUNTIME_STALE",
    "INVALID_MANIFEST",
    "UNKNOWN_ACTION",
    "PROJECT_VALIDATION_FAILED",
    "ENVIRONMENT_UNHEALTHY",
    "OPERATION_FAILED",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devsim",
        description="DevSim\nDeterministic preview runtime for stateful applications.\n\nCommon workflow:\n  devsim detect\n  devsim doctor\n  devsim preview normal --seed 42\n  devsim preview status\n  devsim preview stop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit stable machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    _add_json_flag(init)
    init.add_argument("--inspect-postgres", action="store_true", help="inspect a configured local PostgreSQL database after initialization")
    init.add_argument("--dry-run", action="store_true", help="show files without changing the project")
    init.add_argument("--inspect", action="store_true", help="generate a heuristic integration draft for review")
    detect = subparsers.add_parser("detect", help="read-only project and DevSim integration discovery")
    _add_json_flag(detect)
    capabilities = subparsers.add_parser("capabilities", help="show the machine-readable DevSim capability contract")
    _add_json_flag(capabilities)
    quickstart = subparsers.add_parser("quickstart", help="show the canonical project integration workflow")
    _add_json_flag(quickstart)
    skill = subparsers.add_parser("skill", help="install the DevSim agent skill into Codex's standard skill directory")
    _add_json_flag(skill)
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    skill_install = skill_sub.add_parser("install", help="install or update skills/devsim under CODEX_HOME")
    _add_json_flag(skill_install)
    project = subparsers.add_parser("project", help="inspect project integration")
    _add_json_flag(project)
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_status_parser = project_sub.add_parser("status", help="show integration completeness")
    _add_json_flag(project_status_parser)
    project_validate_parser = project_sub.add_parser("validate", help="validate integration without starting runtime")
    _add_json_flag(project_validate_parser)
    for name in ("up", "down", "reset", "seed", "status"):
        command = subparsers.add_parser(name)
        _add_json_flag(command)
        if name in {"reset", "seed"}:
            command.add_argument("--seed", type=int, default=0)
            command.add_argument("--profile", default="default")
        if name == "seed":
            command.add_argument("seed_command", nargs="?", choices=("plan", "validate"))
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
    schema = subparsers.add_parser("schema")
    _add_json_flag(schema)
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_inspect = schema_sub.add_parser("inspect")
    _add_json_flag(schema_inspect)
    serve = subparsers.add_parser("serve")
    _add_json_flag(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)
    serve.add_argument("--token")
    preview = subparsers.add_parser("preview")
    _add_json_flag(preview)
    preview.add_argument("profile", nargs="?", help="profile name, or status/stop")
    preview.add_argument("--seed", type=int, default=0)
    preview.add_argument("--open", action="store_true")
    return parser


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS preserves a top-level --json value when the flag appears before the command.
    parser.add_argument("--json", action="store_true", dest="json_output", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
        if result.get("ok") is False:
            result = _normalize_result_failure(result, args)
        emit(result, args.json_output)
        if result.get("ok") is False:
            raise SystemExit(_result_exit_code(result))
    except (DevSimError, OSError) as exc:
        error = {"ok": False, "error": _error_payload(exc)}
        emit(error, args.json_output)
        raise SystemExit(_exit_code(exc)) from exc


def _error_payload(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    known = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", message)
    code = next((candidate for candidate in known if candidate in _STABLE_ERROR_CODES), getattr(exc, "code", "runtime_error"))
    if isinstance(exc, ConfigError):
        code = "INVALID_MANIFEST"
    elif "already" in message.lower() and "runtime" in message.lower():
        code = "RUNTIME_ALREADY_RUNNING"
    elif "unknown command" in message.lower() or "unknown action" in message.lower():
        code = "UNKNOWN_ACTION"
    safety = code in {"SEED_TARGET_UNSAFE", "BROWSER_TARGET_UNSAFE"} or exc.__class__.__name__ == "SafetyError"
    configuration = code in {"INVALID_MANIFEST", "SEED_SCHEMA_DRIFT", "CYCLIC_SEED_DEPENDENCY", "SCENARIO_CHANGED", "RUNTIME_ALREADY_RUNNING"} or isinstance(exc, ScenarioError) and code in {"SCENARIO_CHANGED"}
    hint = None
    if code == "BROWSER_ADAPTER_UNAVAILABLE":
        hint = "Install the browser extra and Chromium, or treat browser observation as blocked."
    elif code == "SCENARIO_CHANGED":
        hint = "Review the scenario change, or explicitly pass --allow-changed-scenario for replay."
    elif code == "RUNTIME_ALREADY_RUNNING":
        hint = "Inspect the active preview with devsim preview status, or stop it before starting another one."
    elif code == "INVALID_MANIFEST":
        hint = "Run devsim project validate --json and fix devsim.yaml before continuing."
    elif safety:
        hint = "Use a development or preview target; production and public endpoints are rejected."
    return {"code": code, "message": message, "recoverable": not safety and not configuration, "hint": hint}


def _exit_code(exc: Exception) -> int:
    payload = _error_payload(exc)
    code = payload["code"]
    if code in {"SEED_TARGET_UNSAFE", "BROWSER_TARGET_UNSAFE"} or exc.__class__.__name__ == "SafetyError":
        return 4
    if code in {"INVALID_MANIFEST", "SEED_SCHEMA_DRIFT", "CYCLIC_SEED_DEPENDENCY", "SCENARIO_CHANGED", "RUNTIME_ALREADY_RUNNING"} or isinstance(exc, ScenarioError):
        return 2
    if code in {"BROWSER_ADAPTER_UNAVAILABLE", "CONTROL_AUTH_REQUIRED"} or isinstance(exc, OSError):
        return 3
    return 1


def _normalize_result_failure(result: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Give read-only validation/health commands the same error envelope as exceptions."""
    if result.get("error"):
        return result
    errors = result.get("errors") or []
    first = errors[0] if isinstance(errors, list) and errors else {}
    code = first.get("code") if isinstance(first, dict) else None
    if not code:
        if args.command == "project" and getattr(args, "project_command", None) == "validate":
            code = "INVALID_MANIFEST" if result.get("status") == "INVALID" else "PROJECT_VALIDATION_FAILED"
        elif args.command == "doctor":
            code = "ENVIRONMENT_UNHEALTHY"
        else:
            code = "OPERATION_FAILED"
    message = first.get("detail") or first.get("message") if isinstance(first, dict) else None
    if not message:
        message = f"{args.command} failed"
    normalized = dict(result)
    normalized["error"] = {
        "code": code,
        "message": message,
        "recoverable": code not in {"SEED_TARGET_UNSAFE", "BROWSER_TARGET_UNSAFE"},
        "hint": "Fix the reported checks and retry." if code != "ENVIRONMENT_UNHEALTHY" else "Run devsim doctor --json for the failing environment check.",
    }
    return normalized


def _result_exit_code(result: dict[str, Any]) -> int:
    code = ((result.get("error") or {}).get("code"))
    if code in {"SEED_TARGET_UNSAFE", "BROWSER_TARGET_UNSAFE"}:
        return 4
    if code in {"INVALID_MANIFEST", "SEED_SCHEMA_DRIFT", "CYCLIC_SEED_DEPENDENCY", "SCENARIO_CHANGED", "RUNTIME_ALREADY_RUNNING", "PROJECT_VALIDATION_FAILED"}:
        return 2
    if code in {"BROWSER_ADAPTER_UNAVAILABLE", "CONTROL_AUTH_REQUIRED"}:
        return 3
    return 1


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    project_dir = args.project_dir.resolve()
    if args.command == "init":
        if getattr(args, "inspect", False):
            draft = inspect_draft(project_dir)
            if not getattr(args, "dry_run", False):
                draft_path = project_dir / "devsim.yaml.draft"
                if draft_path.exists():
                    raise DevSimError(f"refusing to overwrite existing {draft_path}")
                project_dir.mkdir(parents=True, exist_ok=True)
                draft_path.write_text(draft["draft"], encoding="utf-8")
                draft["written"] = True
            else:
                draft["written"] = False
            return draft
        if getattr(args, "dry_run", False):
            return {"ok": True, "operation": "init", "dry_run": True, **init_plan(project_dir)}
        return init_project(project_dir, inspect_postgres=getattr(args, "inspect_postgres", False))
    if args.command == "detect":
        return detect_project(project_dir)
    if args.command == "capabilities":
        return capabilities_result()
    if args.command == "quickstart":
        return {
            "ok": True,
            "steps": [
                "devsim detect --json",
                "devsim init",
                "devsim doctor --json",
                "devsim preview normal --seed 42 --json",
            ],
            "note": "quickstart is informational and does not modify files or start a runtime",
        }
    if args.command == "skill":
        if args.skill_command == "install":
            return install_skill()
        raise DevSimError("UNKNOWN_ACTION: unknown skill command")
    if args.command == "project":
        if args.project_command == "status":
            return project_status(project_dir)
        if args.project_command == "validate":
            return validate_project(project_dir)
        raise DevSimError("UNKNOWN_ACTION: unknown project command")
    manifest = load_manifest(project_dir)
    store = StateStore(project_dir)
    ownership = RuntimeOwnership(project_dir)
    if args.command in {"up", "down", "reset", "seed"}:
        if args.command == "seed" and getattr(args, "seed_command", None) in {"plan", "validate"}:
            from .seed import database_url_for, build_seed_plan, schema_seed_config
            from .schema import inspect_postgres

            schema = inspect_postgres(database_url_for(manifest))
            plan = build_seed_plan(schema, schema_seed_config(manifest), getattr(args, "profile", "default"))
            return {"ok": True, "operation": f"seed.{args.seed_command}", "plan": plan.to_dict()}
        state = Lifecycle(project_dir, manifest, store).run(
            args.command, seed=getattr(args, "seed", 0), profile=getattr(args, "profile", "default")
        )
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
                manifest.observation,
            ).run(scenarios[args.name], args.seed)
            return {"ok": True, "scenario": args.name, "state": state.to_dict()}
        if args.scenario_command == "start":
            scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
            if args.name not in scenarios:
                raise DevSimError(f"scenario {args.name!r} was not found")
            scenario = scenarios[args.name]
            if scenario.runtime_mode != "persistent":
                raise ScenarioError(f"scenario {args.name!r} is finite; use scenario run")
            started = _start_managed_scenario(
                project_dir, manifest, store, ownership, scenario, args.seed,
                max_events=args.max_events, max_duration=args.max_duration,
            )
            return {"ok": True, "operation": "scenario.start", **started}
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
                manifest.observation,
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
    if args.command == "schema" and args.schema_command == "inspect":
        from .seed import database_url_for
        from .schema import inspect_postgres

        return {"ok": True, "schema": inspect_postgres(database_url_for(manifest)).to_dict()}
    if args.command == "serve":
        from .control import serve

        return serve(project_dir, manifest, host=args.host, port=args.port, token=args.token)
    if args.command == "preview":
        if args.profile == "status":
            return preview_status(project_dir, manifest, store, ownership)
        if args.profile == "stop":
            return preview_stop(manifest, store, ownership)
        if not args.profile:
            raise DevSimError("preview requires a profile, status, or stop")
        preset = manifest.presets.get(args.profile)
        if not isinstance(preset, dict):
            raise DevSimError(f"preview preset {args.profile!r} was not found")
        seed_profile = str(preset.get("seed_profile", args.profile))
        scenario_name = preset.get("scenario")
        if not isinstance(scenario_name, str) or not scenario_name:
            raise DevSimError(f"preview preset {args.profile!r} requires scenario")
        Lifecycle(project_dir, manifest, store).run("reset", seed=args.seed, profile=seed_profile)
        scenarios = {item.name: item for item in discover_scenarios(project_dir, manifest)}
        scenario = scenarios.get(scenario_name)
        if scenario is None:
            raise DevSimError(f"scenario {scenario_name!r} was not found")
        if scenario.runtime_mode != "persistent":
            raise ScenarioError(f"preview scenario {scenario_name!r} must be persistent")
        started = _start_managed_scenario(project_dir, manifest, store, ownership, scenario, args.seed, profile=args.profile)
        result = {
            "ok": True,
            "operation": "preview",
            "project": manifest.project_name,
            "profile": args.profile,
            "seed_profile": seed_profile,
            "scenario": scenario_name,
            "seed": args.seed,
            "runtime": started,
            "control_url": f"http://127.0.0.1:8001",
            "application_url": manifest.base_url,
            "application": {"url": manifest.base_url},
            "control": {"url": "http://127.0.0.1:8001"},
            "browser": {"configured": "browser" in manifest.adapter_types or bool(manifest.observation.get("browser"))},
            "run_id": started.get("run_id"),
            "events": {"count": 0, "completed": None, "failed": None},
            "open_requested": args.open,
        }
        if args.open:
            webbrowser.open(manifest.base_url)
        return result
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


def _start_managed_scenario(project_dir: Path, manifest, store: StateStore, ownership: RuntimeOwnership, scenario, seed: int, *, max_events: int | None = None, max_duration: str | None = None, profile: str | None = None) -> dict[str, Any]:
    current = ownership.status()
    if current and current.get("status") in {"RUNNING", "PAUSED", "STARTING"} and current.get("process_alive"):
        raise ScenarioError(f"RUNTIME_ALREADY_RUNNING: runtime is already running (run {current.get('run_id')})")
    run_id = str(uuid.uuid4())
    command = [sys.executable, "-m", "devsim.runtime_process", "--project-dir", str(project_dir), "--scenario", scenario.name, "--seed", str(seed), "--run-id", run_id]
    if max_events is not None:
        command += ["--max-events", str(max_events)]
    if max_duration:
        from .timeparse import parse_duration
        command += ["--max-duration-ms", str(parse_duration(max_duration, field="--max-duration", allow_hours=True))]
    ownership.claim({"run_id": run_id, "pid": 0, "scenario": scenario.name, "scenario_hash": scenario.content_hash, "seed": seed, "profile": profile, "status": "STARTING"})
    state = store.load(manifest.project_name)
    state.status = "running"; state.scenario = scenario.name; state.seed = seed; state.run_id = run_id; state.scenario_hash = scenario.content_hash; state.scenario_version = scenario.version; state.started_at = utc_now(); state.clock_speed = scenario.speed; state.last_operation = "preview"; state.heartbeat = utc_now(); store.save(state)
    try:
        process = subprocess.Popen(command, cwd=project_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        ownership.clear()
        raise
    ownership.update(pid=process.pid)
    return {"status": state.status, "run_id": run_id, "pid": process.pid, "scenario": scenario.name, "seed": seed, "state": state.to_dict()}


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


def preview_status(project_dir: Path, manifest, store: StateStore, ownership: RuntimeOwnership) -> dict[str, Any]:
    """Return the canonical agent readback for the active preview."""
    state_result = status_result(project_dir, manifest, store, ownership)
    state = state_result["state"]
    runtime = state.get("runtime") or {}
    run_id = state.get("run_id")
    events: dict[str, Any] = {"count": 0, "completed": None, "failed": None}
    if run_id:
        try:
            inspected = inspect_run(store, run_id)
            events = {key: inspected.get(key) for key in ("event_count", "completed", "failed", "completed_at", "failed_at")}
            events["count"] = events.pop("event_count")
        except Exception:
            pass
    browser_configured = "browser" in manifest.adapter_types or bool(manifest.observation.get("browser"))
    browser = {"configured": browser_configured, "available": None}
    if browser_configured:
        try:
            import playwright  # type: ignore[import-not-found]
        except ImportError:
            browser["available"] = False
        else:
            browser["available"] = True
    return {
        "ok": True,
        "project": manifest.project_name,
        "profile": runtime.get("profile") or None,
        "seed": state.get("seed"),
        "runtime": {"status": state.get("status"), "process_alive": state.get("process_alive"), "ownership": runtime},
        "scenario": state.get("scenario"),
        "clock": {"speed": state.get("clock_speed"), "virtual_time_ms": state.get("virtual_time_ms"), "status": state.get("status")},
        "application": {"url": manifest.base_url},
        "control": {"url": "http://127.0.0.1:8001"},
        "browser": browser,
        "run_id": run_id,
        "events": events,
        "state": state,
    }


def preview_stop(manifest, store: StateStore, ownership: RuntimeOwnership) -> dict[str, Any]:
    """Request graceful runtime shutdown without destroying application data."""
    state = store.load(manifest.project_name)
    state.stop_requested = True
    state.last_operation = "preview.stop"
    store.save(state)
    active = ownership.status()
    if active and active.get("process_alive"):
        ownership.request("stop")
    return {"ok": True, "operation": "preview.stop", "destroyed": False, "runtime": active or {"status": "idle", "process_alive": False}, "state": state.to_dict()}


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
            runner = ScenarioRunner(
                project_dir,
                manifest.project_name,
                manifest.base_url,
                StateStore(project_dir),
                manifest.adapter_types,
                manifest.observation,
            )
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


def init_project(project_dir: Path, *, inspect_postgres: bool = False) -> dict[str, Any]:
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project_dir / "devsim.yaml"
    created: list[str] = []
    kept: list[str] = []
    if not manifest_path.exists():
        manifest_path.write_text(
            """version: 1\nproject:\n  name: example-app\nenvironment:\n  mode: development\ndatabase:\n  engine: postgres\n  lifecycle: {}\nseed:\n  mode: schema\n  spec: devsim/seed.yaml\nscenarios:\n  path: devsim/scenarios\nruntime:\n  base_url: http://127.0.0.1:8000\n  adapters:\n    - type: http\n    - type: command\npresets:\n  normal:\n    seed_profile: normal\n    scenario: normal\n""",
            encoding="utf-8",
        )
        created.append("devsim.yaml")
    else:
        kept.append("devsim.yaml")
    StateStore(project_dir).directory.mkdir(parents=True, exist_ok=True)
    scenarios_dir = project_dir / "devsim" / "scenarios"
    scenarios_existed = scenarios_dir.exists()
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    (kept if scenarios_existed else created).append("devsim/scenarios/")
    seed_draft = project_dir / "devsim" / "seed.yaml"
    if not seed_draft.exists():
        seed_draft.write_text(
            """# Generated seed specification. Refer to it with `seed.spec: devsim/seed.yaml`.
# The database schema determines structure; this file documents semantic intent.
mode: schema
schema:
  database_url: ${env.DEVSIM_DATABASE_URL}
plan:
  tables: {}
profiles:
  normal: {}
  minimal: {}
""",
            encoding="utf-8",
        )
        created.append("devsim/seed.yaml")
    else:
        kept.append("devsim/seed.yaml")
    scenario_draft = scenarios_dir / "normal.yaml"
    if not scenario_draft.exists():
        scenario_draft.write_text(
            """# Generated skeleton. REVIEW_REQUIRED: add project-owned actions.
version: 1
name: normal
description: Representative normal preview state.
clock: {speed: 10}
runtime:
  mode: persistent
timeline: []
""",
            encoding="utf-8",
        )
        created.append("devsim/scenarios/normal.yaml")
    else:
        kept.append("devsim/scenarios/normal.yaml")
    gitignore_path = project_dir / ".gitignore"
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    if ".devsim/" not in {line.strip() for line in existing.splitlines()}:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitignore_path.write_text(f"{existing}{separator}.devsim/\n", encoding="utf-8")
        created.append(".gitignore (.devsim/)")
    else:
        kept.append(".gitignore (.devsim/)")
    result: dict[str, Any] = {
        "ok": True,
        "initialized": str(manifest_path),
        "seed_draft": str(seed_draft),
        "scenario_draft": str(scenario_draft),
        "next_steps": [
            "review devsim.yaml and fill lifecycle commands",
            "define baseline seed behavior in devsim/seed.yaml or seed.command",
            "add real application actions to devsim/scenarios/normal.yaml",
            "run devsim project validate --json",
            "run devsim doctor --json before preview",
        ],
        "review_required": True,
        "created": created,
        "kept": kept,
    }
    if inspect_postgres:
        manifest = load_manifest(project_dir)
        from .seed import database_url_for
        from .schema import inspect_postgres as inspect_schema

        result["schema"] = inspect_schema(database_url_for(manifest)).to_dict()
    return result


def install_skill() -> dict[str, Any]:
    """Install the repository-owned skill using Codex's normal skill layout."""
    candidates = [
        Path(__file__).resolve().parents[1] / "skills" / "devsim",
        Path(sysconfig.get_path("data")) / "share" / "devsim" / "skills" / "devsim",
    ]
    source = next((candidate for candidate in candidates if (candidate / "SKILL.md").is_file()), candidates[0])
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    destination = codex_home / "skills" / "devsim"
    if not (source / "SKILL.md").is_file():
        raise DevSimError(f"skill source is missing: {source / 'SKILL.md'}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return {"ok": True, "operation": "skill.install", "source": str(source), "destination": str(destination)}


def emit(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True))
        return
    if not value.get("ok"):
        print(f"error: {value['error']['message']}", file=sys.stderr)
        return
    if "dry_run" in value:
        for item in value.get("actions", []):
            print(f"{item['action']} {item['path']}")
        return
    if value.get("status") == "GENERATED_DRAFT":
        print("GENERATED_DRAFT")
        print("REVIEW_REQUIRED")
        print(f"Draft: {value['draft_path']}")
        return
    if "steps" in value and value.get("operation") != "init":
        for index, step in enumerate(value["steps"], start=1):
            print(f"{index}. {step}")
        print(value.get("note", ""))
        return
    if "project_detected" in value:
        print(f"PROJECT_DETECTED={'YES' if value['project_detected'] else 'NO'}")
        print(f"DEVSIM_INTEGRATED={value['integration'].upper()}")
        print(f"MANIFEST={value['manifest'] or 'NONE'}")
        print(f"DATABASE={value['database'].get('engine') or 'UNKNOWN'}")
        print(f"MIGRATIONS={'YES' if value['migrations']['detected'] else 'NO'}")
        print(f"SCENARIOS={value['scenarios']['count']}")
        print(f"SEED={'YES' if value['seed']['configured'] else 'NO'}")
        print(f"BROWSER={'YES' if value['browser']['configured'] else 'NO'}")
        print(f"PRESETS={','.join(value['presets']['names']) or 'NONE'}")
        return
    if "integration" in value and "checks" in value and "project" in value and "state" not in value:
        print(f"PROJECT={value['project']}")
        print(f"INTEGRATION_STATUS={value['status']}")
        for check in value["checks"]:
            print(f"{check['name'].upper()}={check['status']}")
        return
    if "runtime" in value and "application" in value and "run_id" in value:
        print("Preview ready" if value["runtime"]["status"] in {"running", "paused"} else f"Preview {value['runtime']['status']}")
        print(f"Project: {value['project']}")
        print(f"Profile: {value.get('profile') or 'unknown'}")
        print(f"Seed: {value['seed']}")
        print(f"Runtime: {value['runtime']['status'].upper()}")
        print(f"Application: {value['application']['url']}")
        print(f"Control: {value['control']['url']}")
        print(f"Run: {value['run_id'] or 'none'}")
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
