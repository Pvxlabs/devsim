from __future__ import annotations

import asyncio
import time
import uuid
import heapq
from pathlib import Path
from typing import Any

from .adapters import AdapterRegistry, BrowserAdapter, CommandAdapter, HTTPAdapter, LifecycleAdapter, ContextAdapter, ValueAdapter, WebSocketAdapter
from .assertions import assert_expectations, expectation_accepts_result
from .clock import VirtualClock, utc_now
from .context import collect_secret_values, normalize_result, resolve
from .errors import AdapterError
from .models import ActionContext, ActionResult, RuntimeState, Scenario, ScheduledEvent
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
        observation: dict[str, Any] | None = None,
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
        self.registry.register("context.set", ContextAdapter("context.set"))
        self.registry.register("context.increment", ContextAdapter("context.increment"))
        self.registry.register("context.unset", ContextAdapter("context.unset"))
        self.registry.register("value.generate", ValueAdapter())
        self.registry.register("websocket.expect", WebSocketAdapter())
        if "browser" in adapter_types or observation:
            browser_config = observation or {}
            if not isinstance(browser_config.get("browser"), dict):
                raise AdapterError("BROWSER_OBSERVATION_CONFIG_REQUIRED: observation.browser must be configured")
            browser = BrowserAdapter(project_dir, base_url, browser_config)
            for action in ("browser.open", "browser.expect", "browser.screenshot", "browser.click"):
                self.registry.register(action, browser)

    def run(self, scenario: Scenario, seed: int, **kwargs: Any) -> RuntimeState:
        return asyncio.run(self._run(scenario, seed, **kwargs))

    async def _run(self, scenario: Scenario, seed: int, *, run_id: str | None = None, ownership=None, max_events: int | None = None, max_duration_ms: int | None = None) -> RuntimeState:
        run_id = run_id or str(uuid.uuid4())
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
            heartbeat=utc_now(),
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
        max_events = max_events or scenario.max_events
        max_duration_ms = max_duration_ms or scenario.max_virtual_duration_ms
        schedule = build_schedule(scenario) if scenario.runtime_mode == "finite" else []
        queue = [(event.virtual_ms, event.timeline_index, event.occurrence, event) for event in schedule]
        heapq.heapify(queue)
        if scenario.runtime_mode == "persistent":
            for item in scenario.timeline:
                if item.at_ms is not None:
                    event = ScheduledEvent(item.at_ms, item.index, 0, item.action, item.payload, item.step_id, item.expect)
                    heapq.heappush(queue, (event.virtual_ms, event.timeline_index, event.occurrence, event))
                else:
                    event = ScheduledEvent(
                        item.every_ms, item.index, 0, item.action, item.payload,
                        item.step_id, item.expect, True, item.every_ms, item.until_ms,
                    )
                    heapq.heappush(queue, (event.virtual_ms, event.timeline_index, event.occurrence, event))
        last_heartbeat = [0.0]
        def paused() -> bool:
            if ownership is None:
                return False
            now = time.monotonic()
            if now - last_heartbeat[0] >= 0.5:
                ownership.update(status="PAUSED" if ownership.control() == "pause" else "RUNNING")
                last_heartbeat[0] = now
            return ownership.control() == "pause"
        def stopped() -> bool:
            return ownership is not None and ownership.control() == "stop"
        try:
            while queue:
                _, _, _, event = heapq.heappop(queue)
                if event.recurring:
                    next_occurrence = event.occurrence + 1
                    next_ms = event.virtual_ms + event.every_ms
                    if event.until_ms is None or next_ms <= event.until_ms:
                        following = ScheduledEvent(
                            next_ms, event.timeline_index, next_occurrence, event.action,
                            event.payload, event.step_id, event.expect, True,
                            event.every_ms, event.until_ms,
                        )
                        heapq.heappush(queue, (next_ms, event.timeline_index, next_occurrence, following))
                state = self.state_store.load(self.project)
                if (ownership is not None and ownership.control() == "stop") or state.stop_requested:
                    state.status = "stopped"
                    state.last_operation = "scenario.stop"
                    self.state_store.save(state)
                    break
                if max_duration_ms is not None and event.virtual_ms > max_duration_ms:
                    state.status = "completed"
                    state.result = "COMPLETED_LIMIT"
                    state.stop_requested = False
                    self.state_store.save(state)
                    if ownership is not None:
                        ownership.update(status="STOPPED", result="COMPLETED_LIMIT")
                        if ownership.lock_path.is_dir():
                            ownership.lock_path.rmdir()
                    return state
                reached_event = await clock.wait_until(event.virtual_ms, paused=paused, stopped=stopped)
                if not reached_event:
                    state = self.state_store.load(self.project)
                    state.status = "stopped"
                    state.stop_requested = False
                    state.last_operation = "scenario.stop"
                    self.state_store.save(state)
                    break
                if ownership is not None and ownership.control() == "pause":
                    ownership.update(status="PAUSED")
                elif ownership is not None:
                    ownership.update(status="RUNNING")
                state = self.state_store.load(self.project)
                if state.stop_requested:
                    state.status = "stopped"
                    state.last_operation = "scenario.stop"
                    self.state_store.save(state)
                    break

                state.event_sequence += 1
                state.virtual_time_ms = event.virtual_ms
                state.events_executed = state.event_sequence
                state.heartbeat = utc_now()
                state.next_event = {"action": event.action, "virtual_time_ms": event.virtual_ms, "step_id": event.step_id}
                self.state_store.save(state)
                context.virtual_ms = event.virtual_ms
                context.event_sequence = state.event_sequence
                adapter = self.registry.resolve(event.action)
                context.values["_devsim_browser_action"] = event.action
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
                    state.events_failed += 1
                    self.state_store.save(state)
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
                        "context": dict(context.values),
                    },
                    secret_values=secret_values,
                )
                if max_events is not None and state.event_sequence >= max_events:
                    state.status = "completed"
                    state.result = "COMPLETED_LIMIT"
                    state.stop_requested = False
                    self.state_store.save(state)
                    if ownership is not None:
                        ownership.update(status="STOPPED", result="COMPLETED_LIMIT")
                        ownership.lock_path.rmdir() if ownership.lock_path.is_dir() else None
                    return state
                if max_duration_ms is not None and event.virtual_ms >= max_duration_ms:
                    state.status = "completed"
                    state.result = "COMPLETED_LIMIT"
                    self.state_store.save(state)
                    if ownership is not None:
                        ownership.update(status="STOPPED", result="COMPLETED_LIMIT")
                        ownership.lock_path.rmdir() if ownership.lock_path.is_dir() else None
                    return state
            state = self.state_store.load(self.project)
            if state.status == "running":
                state.status = "completed"
                state.virtual_time_ms = max([event.virtual_ms for event in schedule] or [0])
                state.stop_requested = False
                state.error = None
                self.state_store.save(state)
                if ownership is not None:
                    ownership.update(status="STOPPED", result="COMPLETED")
            elif ownership is not None and state.status == "stopped":
                ownership.update(status="STOPPED", result="STOPPED")
            if ownership is not None and ownership.lock_path.is_dir():
                ownership.lock_path.rmdir()
        except Exception as exc:
            state = self.state_store.load(self.project)
            state.status = "failed"
            state.error = {"code": getattr(exc, "code", "scenario_error"), "message": str(exc)}
            self.state_store.save(state)
            if ownership is not None:
                ownership.update(status="FAILED", error=state.error)
                if ownership.lock_path.is_dir():
                    ownership.lock_path.rmdir()
            raise
        finally:
            await self.registry.close()
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
