from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from .adapters import AdapterRegistry, CommandAdapter, HTTPAdapter, LifecycleAdapter
from .assertions import assert_expectations, expectation_accepts_result
from .clock import VirtualClock, utc_now
from .context import collect_secret_values, normalize_result, resolve
from .errors import AdapterError
from .models import ActionContext, ActionResult, RuntimeState, Scenario
from .redaction import redact
from .rng import DeterministicRNG
from .scheduler import build_schedule
from .state import StateStore


class ScenarioRunner:
    def __init__(
        self,
        project_dir: Path,
        project: str,
        base_url: str,
        state_store: StateStore,
        adapter_types: tuple[str, ...] = ("http", "command"),
    ):
        self.project_dir = project_dir
        self.project = project
        self.state_store = state_store
        self.registry = AdapterRegistry()
        if "http" in adapter_types:
            self.registry.register("api.request", HTTPAdapter(base_url))
        if "command" in adapter_types:
            self.registry.register("command.run", CommandAdapter(project_dir, raise_on_failure=False))
        self.registry.register("lifecycle.start", LifecycleAdapter("lifecycle.start"))
        self.registry.register("lifecycle.complete", LifecycleAdapter("lifecycle.complete"))

    def run(self, scenario: Scenario, seed: int) -> RuntimeState:
        return asyncio.run(self._run(scenario, seed))

    async def _run(self, scenario: Scenario, seed: int) -> RuntimeState:
        run_id = str(uuid.uuid4())
        clock = VirtualClock.start(scenario.speed)
        state = RuntimeState(
            project=self.project,
            status="running",
            scenario=scenario.name,
            seed=seed,
            run_id=run_id,
            scenario_hash=scenario.content_hash,
            scenario_version=scenario.version,
            started_at=utc_now(),
            virtual_started_at=clock.virtual_started_at,
            clock_speed=scenario.speed,
            last_operation="scenario.run",
        )
        self.state_store.save(state)
        rng = DeterministicRNG(seed)
        steps: dict[str, dict[str, Any]] = {}
        context = ActionContext(
            project_dir=str(self.project_dir),
            run_id=run_id,
            scenario_name=scenario.name,
            seed=seed,
            virtual_ms=0,
            event_sequence=0,
            rng=rng,
            steps=steps,
        )
        schedule = build_schedule(scenario)
        try:
            for event in schedule:
                state = self.state_store.load(self.project)
                if state.stop_requested:
                    state.status = "stopped"
                    state.last_operation = "scenario.stop"
                    self.state_store.save(state)
                    break
                await clock.wait_until(event.virtual_ms)
                state = self.state_store.load(self.project)
                if state.stop_requested:
                    state.status = "stopped"
                    state.last_operation = "scenario.stop"
                    self.state_store.save(state)
                    break

                state.event_sequence += 1
                state.virtual_time_ms = event.virtual_ms
                self.state_store.save(state)
                context.virtual_ms = event.virtual_ms
                context.event_sequence = state.event_sequence
                adapter = self.registry.resolve(event.action)
                resolved_payload = resolve(event.payload, context)
                resolved_expect = resolve(event.expect, context)
                secret_values = (
                    collect_secret_values(event.payload)
                    | collect_secret_values(resolved_payload)
                    | collect_secret_values(context.steps)
                )
                record = {
                    **self._record_base(state, event, adapter.name),
                    "expect": resolved_expect,
                }
                self.state_store.save_run_event(
                    run_id,
                    {"type": "scheduled", "status": "scheduled", **record, "payload": resolved_payload},
                    secret_values=secret_values,
                )
                started = time.perf_counter()
                try:
                    result = await adapter.execute(context, resolved_payload)
                    if not isinstance(result, ActionResult):
                        raise AdapterError(f"adapter {event.action!r} returned an invalid result")
                    normalized = normalize_result(result.data)
                    secret_values |= collect_secret_values(normalized)
                    checked_result = ActionResult(result.ok, normalized)
                    assert_expectations(resolved_expect, checked_result, event.action)
                    if not expectation_accepts_result(resolved_expect, checked_result):
                        raise AdapterError(f"action {event.action!r} completed unsuccessfully")
                    steps[event.step_id] = normalized
                except Exception as exc:
                    self.state_store.save_run_event(
                        run_id,
                        {
                            "type": "failed",
                            "status": "failed",
                            **record,
                            "duration_ms": _duration_ms(started),
                            "error": {
                                "code": getattr(exc, "code", "scenario_error"),
                                "message": str(exc),
                            },
                        },
                        secret_values=secret_values,
                    )
                    raise
                self.state_store.save_run_event(
                    run_id,
                    {
                        "type": "completed",
                        "status": "completed",
                        **record,
                        "duration_ms": _duration_ms(started),
                        "result": normalized,
                        "result_summary": _result_summary(normalized),
                    },
                    secret_values=secret_values,
                )
            else:
                state = self.state_store.load(self.project)
                state.status = "completed"
                state.virtual_time_ms = max([event.virtual_ms for event in schedule] or [0])
                state.stop_requested = False
                state.error = None
                self.state_store.save(state)
        except Exception as exc:
            state = self.state_store.load(self.project)
            state.status = "failed"
            state.error = {"code": getattr(exc, "code", "scenario_error"), "message": str(exc)}
            self.state_store.save(state)
            raise
        return self.state_store.load(self.project)

    @staticmethod
    def _record_base(state: RuntimeState, event: Any, adapter: str) -> dict[str, Any]:
        return {
            "run_id": state.run_id,
            "sequence": state.event_sequence,
            "scenario": state.scenario,
            "scenario_hash": state.scenario_hash,
            "seed": state.seed,
            "virtual_time": event.virtual_ms,
            "virtual_time_ms": event.virtual_ms,
            "real_time": utc_now(),
            "action": event.action,
            "step_id": event.step_id,
            "duration_ms": 0,
            "adapter": adapter,
            "timeline_index": event.timeline_index,
            "occurrence": event.occurrence,
        }


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return redact(
        {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr", "body", "json", "headers"}
        }
    )
