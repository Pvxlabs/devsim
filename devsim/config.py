from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .models import CommandSpec, Manifest, Scenario, TimelineItem


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _command(value: Any, name: str) -> CommandSpec:
    if isinstance(value, str):
        return CommandSpec(value)
    if not isinstance(value, dict) or not isinstance(value.get("command"), str):
        raise ConfigError(f"{name} must contain a command string")
    env = value.get("env", {})
    if not isinstance(env, dict):
        raise ConfigError(f"{name}.env must be a mapping")
    return CommandSpec(
        command=value["command"],
        timeout=float(value.get("timeout", 120)),
        env={str(key): str(item) for key, item in env.items()},
        cwd=str(value["cwd"]) if value.get("cwd") is not None else None,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(content, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return content


def load_manifest(project_dir: Path) -> Manifest:
    path = project_dir / "devsim.yaml"
    data = load_yaml(path)
    if data.get("version") != 1:
        raise ConfigError("devsim.yaml version must be 1")
    project = _mapping(data.get("project"), "project")
    database = _mapping(data.get("database"), "database")
    if database.get("engine", "postgres") != "postgres":
        raise ConfigError("V1 supports only database.engine=postgres")
    lifecycle_data = _mapping(database.get("lifecycle"), "database.lifecycle")
    lifecycle = {name: _command(value, f"database.lifecycle.{name}") for name, value in lifecycle_data.items()}
    seed_data = data.get("seed")
    seed_command = _command(seed_data, "seed") if seed_data is not None else None
    scenarios = _mapping(data.get("scenarios"), "scenarios")
    runtime = _mapping(data.get("runtime"), "runtime")
    adapters = runtime.get("adapters", [{"type": "http"}, {"type": "command"}])
    if not isinstance(adapters, list):
        raise ConfigError("runtime.adapters must be a list")
    adapter_types = []
    for item in adapters:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise ConfigError("each runtime adapter must contain a type")
        adapter_types.append(item["type"])
    return Manifest(
        version=1,
        project_name=str(project.get("name", project_dir.name)),
        environment_mode=str(_mapping(data.get("environment"), "environment").get("mode", "development")),
        database_engine="postgres",
        lifecycle=lifecycle,
        seed_command=seed_command,
        scenarios_path=str(scenarios.get("path", "devsim/scenarios")),
        base_url=str(runtime.get("base_url", "http://127.0.0.1:8000")),
        adapter_types=tuple(adapter_types),
    )


def _canonical_hash(data: dict[str, Any]) -> str:
    normalized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_scenario(path: Path) -> Scenario:
    data = load_yaml(path)
    if data.get("version") != 1:
        raise ConfigError(f"{path}: scenario version must be 1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{path}: scenario name is required")
    clock = _mapping(data.get("clock"), "clock")
    try:
        speed = float(clock.get("speed", 1))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: clock.speed must be a number") from exc
    if speed <= 0:
        raise ConfigError(f"{path}: clock.speed must be positive")
    raw_timeline = data.get("timeline", [])
    if not isinstance(raw_timeline, list):
        raise ConfigError(f"{path}: timeline must be a list")
    timeline: list[TimelineItem] = []
    step_ids: set[str] = set()
    for index, raw in enumerate(raw_timeline):
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: timeline item {index} must be a mapping")
        has_at = "at" in raw
        has_every = "every" in raw
        if has_at == has_every:
            raise ConfigError(f"{path}: timeline item {index} must contain exactly one of at/every")
        if not isinstance(raw.get("action"), str) or not raw["action"]:
            raise ConfigError(f"{path}: timeline item {index} requires action")
        step_id = raw.get("id", f"step-{index}")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ConfigError(f"{path}: timeline item {index}.id must be a non-empty string")
        step_id = step_id.strip()
        if step_id in step_ids:
            raise ConfigError(f"{path}: duplicate timeline step id {step_id!r}")
        step_ids.add(step_id)
        payload = raw.get("with", {})
        if not isinstance(payload, dict):
            raise ConfigError(f"{path}: timeline item {index}.with must be a mapping")
        expect = raw.get("expect", {})
        if not isinstance(expect, dict):
            raise ConfigError(f"{path}: timeline item {index}.expect must be a mapping")
        at_ms = parse_optional_duration(raw.get("at"), f"timeline[{index}].at") if has_at else None
        every_ms = parse_optional_duration(raw.get("every"), f"timeline[{index}].every") if has_every else None
        until_ms = parse_optional_duration(raw.get("until"), f"timeline[{index}].until") if "until" in raw else None
        if has_every and until_ms is None:
            raise ConfigError(f"{path}: repeating timeline item {index} requires until")
        if has_every and every_ms == 0:
            raise ConfigError(f"{path}: timeline[{index}].every must be greater than zero")
        if has_at and "until" in raw:
            raise ConfigError(f"{path}: timeline item {index} cannot combine at and until")
        if has_every and until_ms is not None and until_ms < every_ms:
            raise ConfigError(f"{path}: timeline[{index}].until must be >= every")
        timeline.append(TimelineItem(at_ms, every_ms, until_ms, raw["action"], payload, index, step_id, expect))
    return Scenario(
        version=1,
        name=name,
        description=str(data.get("description", "")),
        speed=speed,
        timeline=tuple(timeline),
        source_path=str(path),
        content_hash=_canonical_hash(data),
    )


def parse_optional_duration(value: Any, field: str) -> int:
    from .timeparse import parse_duration

    return parse_duration(value, field=field)


def discover_scenarios(project_dir: Path, manifest: Manifest) -> list[Scenario]:
    directory = project_dir / manifest.scenarios_path
    if not directory.exists():
        return []
    scenarios = []
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        scenarios.append(load_scenario(path))
    return scenarios
