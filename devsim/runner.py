from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from .adapters import AdapterRegistry, CommandAdapter, HTTPAdapter
from .clock import VirtualClock, utc_now
from .errors import ScenarioError
from .models import ActionContext, RuntimeState, Scenario
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
        adapters = []
        if "http" in adapter_types:
            adapters.append(HTTPAdapter(base_url))
        if "command" in adapter_types:
            adapters.append(CommandAdapter(project_dir))
        self.registry = AdapterRegistry(adapters)

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
                context = ActionContext(
                    project_dir=str(self.project_dir),
                    run_id=run_id,
                    scenario_name=scenario.name,
                    seed=seed,
                    virtual_ms=event.virtual_ms,
                    event_sequence=state.event_sequence,
                    rng=rng,
                )
                record = {
                    "sequence": state.event_sequence,
                    "virtual_time_ms": event.virtual_ms,
                    "timeline_index": event.timeline_index,
                    "occurrence": event.occurrence,
                    "action": event.action,
                    "payload": event.payload,
                }
                self.state_store.save_run_event(run_id, {"type": "scheduled", **record})
                try:
                    result = await self._execute_action(context, event.action, event.payload)
                except Exception as exc:
                    self.state_store.save_run_event(
                        run_id,
                        {"type": "failed", **record, "error": {"code": getattr(exc, "code", "scenario_error"), "message": str(exc)}},
                    )
                    raise
                self.state_store.save_run_event(run_id, {"type": "completed", **record, "result": result.data})
            else:
                state = self.state_store.load(self.project)
                state.status = "completed"
                state.virtual_time_ms = max([event.virtual_ms for event in schedule] or [0])
                state.stop_requested = False
                self.state_store.save(state)
        except Exception as exc:
            state = self.state_store.load(self.project)
            state.status = "failed"
            state.error = {"code": getattr(exc, "code", "scenario_error"), "message": str(exc)}
            self.state_store.save(state)
            raise
        return self.state_store.load(self.project)

    async def _execute_action(self, context: ActionContext, action: str, payload: dict[str, Any]):
        if action in {"lifecycle.start", "lifecycle.complete"}:
            return _lifecycle_result(action)
        if "." not in action:
            raise ScenarioError(f"action {action!r} must use adapter.action form")
        adapter_name, operation = action.split(".", 1)
        if operation not in {"request", "run"}:
            raise ScenarioError(f"unsupported action {action!r}")
        adapter = self.registry.get(adapter_name)
        return await adapter.execute(context, payload)


def _lifecycle_result(action: str):
    from .models import ActionResult

    return ActionResult(ok=True, data={"action": action})
