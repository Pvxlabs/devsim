from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    command: str
    timeout: float = 120.0
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


@dataclass(frozen=True)
class Manifest:
    version: int
    project_name: str
    environment_mode: str
    database_engine: str
    lifecycle: dict[str, CommandSpec]
    seed_command: CommandSpec | None
    scenarios_path: str
    base_url: str
    adapter_types: tuple[str, ...]


@dataclass(frozen=True)
class TimelineItem:
    at_ms: int | None
    every_ms: int | None
    until_ms: int | None
    action: str
    payload: dict[str, Any]
    index: int
    step_id: str
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    version: int
    name: str
    description: str
    speed: float
    timeline: tuple[TimelineItem, ...]
    source_path: str
    content_hash: str
    runtime_mode: str = "finite"
    max_events: int | None = None
    max_virtual_duration_ms: int | None = None


@dataclass(frozen=True)
class ScheduledEvent:
    virtual_ms: int
    timeline_index: int
    occurrence: int
    action: str
    payload: dict[str, Any]
    step_id: str = ""
    expect: dict[str, Any] = field(default_factory=dict)
    recurring: bool = False
    every_ms: int | None = None
    until_ms: int | None = None


@dataclass
class ActionContext:
    project_dir: str
    run_id: str
    scenario_name: str
    seed: int
    virtual_ms: int
    event_sequence: int
    rng: Any
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def run(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario_name,
            "seed": self.seed,
            "virtual_time_ms": self.virtual_ms,
            "event_sequence": self.event_sequence,
        }

    @property
    def context(self) -> dict[str, Any]:
        return self.values


@dataclass
class ActionResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeState:
    project: str
    status: str = "idle"
    scenario: str | None = None
    seed: int | None = None
    run_id: str | None = None
    scenario_hash: str | None = None
    scenario_version: int | None = None
    started_at: str | None = None
    virtual_started_at: str | None = None
    event_sequence: int = 0
    virtual_time_ms: int = 0
    clock_speed: float = 1.0
    stop_requested: bool = False
    last_operation: str | None = None
    error: dict[str, Any] | None = None
    events_executed: int = 0
    events_failed: int = 0
    next_event: dict[str, Any] | None = None
    heartbeat: str | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "status": self.status,
            "scenario": self.scenario,
            "seed": self.seed,
            "run_id": self.run_id,
            "scenario_hash": self.scenario_hash,
            "scenario_version": self.scenario_version,
            "started_at": self.started_at,
            "virtual_started_at": self.virtual_started_at,
            "event_sequence": self.event_sequence,
            "virtual_time_ms": self.virtual_time_ms,
            "clock_speed": self.clock_speed,
            "stop_requested": self.stop_requested,
            "last_operation": self.last_operation,
            "error": self.error,
            "events_executed": self.events_executed,
            "events_failed": self.events_failed,
            "next_event": self.next_event,
            "heartbeat": self.heartbeat,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], project: str) -> "RuntimeState":
        values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        values["project"] = data.get("project", project)
        return cls(**values)
