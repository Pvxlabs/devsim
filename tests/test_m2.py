import asyncio
import json
import os
from pathlib import Path

import pytest

from devsim.adapters.websocket import WebSocketAdapter
from devsim.assertions import assert_expectations
from devsim.cli import doctor_result, validate_scenarios
from devsim.config import load_manifest, load_scenario
from devsim.errors import AdapterError, ConfigError, ScenarioError
from devsim.models import ActionContext
from devsim.rng import DeterministicRNG
from devsim.runtime import RuntimeOwnership
from devsim.runner import ScenarioRunner
from devsim.state import StateStore


def write_project(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\n"
        "database:\n  engine: postgres\n  lifecycle:\n    up: {command: echo up}\n"
        "scenarios: {path: scenarios}\nruntime: {base_url: http://127.0.0.1:8000}\n",
        encoding="utf-8",
    )
    (tmp_path / "scenarios").mkdir()


def load_written(path: Path, content: str):
    path.write_text(content, encoding="utf-8")
    return load_scenario(path, path.parent)


def test_persistent_runtime_repeats_and_stops_at_event_limit(tmp_path: Path) -> None:
    loaded = load_written(
        tmp_path / "active.yaml",
        """version: 1
name: active
clock: {speed: 1000}
runtime:
  mode: persistent
  limits: {max_events: 3}
timeline:
  - every: 100ms
    id: tick
    action: context.increment
    with: {key: count}
""",
    )
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(loaded, 42)
    assert (state.status, state.result, state.event_sequence) == ("completed", "COMPLETED_LIMIT", 3)
    events = StateStore(tmp_path).read_run_events(state.run_id)
    assert [e["virtual_time_ms"] for e in events if e["status"] == "completed"] == [100, 200, 300]


def test_max_virtual_duration_does_not_execute_later_event(tmp_path: Path) -> None:
    loaded = load_written(
        tmp_path / "duration.yaml",
        """version: 1
name: duration
clock: {speed: 1000}
runtime:
  mode: persistent
  limits: {max_virtual_duration: 250ms}
timeline:
  - every: 100ms
    action: context.increment
    with: {key: count}
""",
    )
    state = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path)).run(loaded, 1)
    events = [e for e in StateStore(tmp_path).read_run_events(state.run_id) if e["status"] == "completed"]
    assert state.result == "COMPLETED_LIMIT"
    assert len(events) == 2
    assert state.virtual_time_ms == 200


def test_runtime_ownership_rejects_duplicate_and_marks_stale(tmp_path: Path) -> None:
    ownership = RuntimeOwnership(tmp_path)
    ownership.claim({"run_id": "first", "pid": os.getpid(), "scenario": "active", "status": "RUNNING"})
    with pytest.raises(ScenarioError, match="already owned"):
        ownership.claim({"run_id": "second", "pid": os.getpid(), "scenario": "active", "status": "STARTING"})
    ownership.clear()
    ownership._write({"run_id": "dead", "pid": 99999999, "scenario": "active", "status": "RUNNING"})
    assert ownership.status()["status"] == "STALE"


def test_virtual_clock_freezes_during_pause() -> None:
    from devsim.clock import VirtualClock

    async def exercise() -> int:
        paused = True

        def is_paused() -> bool:
            return paused

        clock = VirtualClock.start(10)
        task = asyncio.create_task(clock.wait_until(500, paused=is_paused))
        await asyncio.sleep(0.15)
        frozen = clock.now_ms()
        await asyncio.sleep(0.15)
        assert clock.now_ms() == frozen
        paused = False
        await task
        return clock.now_ms()

    assert 500 <= asyncio.run(exercise()) <= 550


def test_composition_is_ordered_nested_and_safe(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "base.yaml").write_text("timeline:\n  - at: 1ms\n    id: base\n    action: lifecycle.start\n", encoding="utf-8")
    (root / "nested.yaml").write_text(
        "include: [base.yaml]\ntimeline:\n  - at: 2ms\n    id: nested\n    action: lifecycle.complete\n",
        encoding="utf-8",
    )
    main = root / "main.yaml"
    main.write_text("version: 1\nname: composed\ninclude: [nested.yaml]\n", encoding="utf-8")
    assert [item.step_id for item in load_scenario(main, root).timeline] == ["base", "nested"]

    (root / "cycle-a.yaml").write_text("include: [cycle-b.yaml]\n", encoding="utf-8")
    (root / "cycle-b.yaml").write_text("include: [cycle-a.yaml]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="include cycle"):
        load_scenario(root / "cycle-a.yaml", root)

    escaped = root / "escaped.yaml"
    escaped.write_text("version: 1\nname: escaped\ninclude: [../../etc/passwd]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="escapes scenario root"):
        load_scenario(escaped, root)


def test_composition_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "fragment.yaml").write_text("timeline:\n  - at: 1ms\n    id: same\n    action: lifecycle.start\n", encoding="utf-8")
    main = root / "main.yaml"
    main.write_text(
        "version: 1\nname: duplicate\ninclude: [fragment.yaml]\n"
        "timeline:\n  - at: 2ms\n    id: same\n    action: lifecycle.complete\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate timeline step id"):
        load_scenario(main, root)


def test_context_and_generated_values_are_replay_deterministic(tmp_path: Path) -> None:
    loaded = load_written(
        tmp_path / "values.yaml",
        """version: 1
name: values
clock: {speed: 1000}
timeline:
  - at: 0ms
    id: set
    action: context.set
    with: {key: workload, value: normal}
  - at: 1ms
    id: increment
    action: context.increment
    with: {key: count, amount: 2}
  - at: 2ms
    id: generated
    action: value.generate
    with: {type: choice, choices: [a, b, c]}
  - at: 3ms
    id: uuid
    action: value.generate
    with: {type: uuid}
  - at: 4ms
    id: read
    action: context.set
    with: {key: copied, value: "${context.count}"}
""",
    )
    runner = ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path))
    first = runner.run(loaded, 7)
    first_events = [e for e in StateStore(tmp_path).read_run_events(first.run_id) if e["status"] == "completed"]
    second = runner.run(loaded, 7)
    second_events = [e for e in StateStore(tmp_path).read_run_events(second.run_id) if e["status"] == "completed"]
    assert first_events[-2]["result"] == second_events[-2]["result"]
    assert first_events[-1]["context"] == second_events[-1]["context"]
    assert first_events[-1]["context"]["copied"] == 2


def test_websocket_expect_supports_json_and_invalid_json() -> None:
    async def exercise():
        from websockets.asyncio.server import serve

        async def handler(socket):
            await socket.send(json.dumps({"id": "abc", "status": "active"}))

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            context = ActionContext(".", "run", "scenario", 1, 0, 1, DeterministicRNG(1))
            result = await WebSocketAdapter().execute(context, {"url": f"ws://127.0.0.1:{port}"})
            assert result.data["json"]["status"] == "active"
            assert_expectations({"json": {"status": "active"}}, result, "websocket.expect")
            with pytest.raises(Exception, match="did not contain expected subset"):
                assert_expectations({"json": {"status": "closed"}}, result, "websocket.expect")

        with pytest.raises(AdapterError, match="timed out|connection failed"):
            await WebSocketAdapter().execute(context, {"url": "ws://127.0.0.1:1", "timeout": 0.05})

    asyncio.run(exercise())


def test_doctor_and_validate_report_health_and_unknown_action(tmp_path: Path) -> None:
    write_project(tmp_path)
    (tmp_path / "scenarios" / "valid.yaml").write_text("version: 1\nname: valid\ntimeline: [{at: 0ms, action: lifecycle.start}]\n", encoding="utf-8")
    (tmp_path / "scenarios" / "invalid.yaml").write_text("version: 1\nname: invalid\ntimeline: [{at: 0ms, action: missing.action}]\n", encoding="utf-8")
    manifest = load_manifest(tmp_path)
    checked = validate_scenarios(tmp_path, manifest, None, True)
    assert checked["ok"] is False
    assert any(item["scenario"] == "invalid" for item in checked["errors"])
    health = doctor_result(tmp_path, manifest, StateStore(tmp_path), RuntimeOwnership(tmp_path))
    assert health["status"] == "PASS"


def test_artifact_is_redacted_bounded_and_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "super-secret")
    store = StateStore(tmp_path)
    store.save_run_event("run-1", {"type": "completed", "status": "completed", "result": {"body": "x" * 100000, "token": "super-secret"}})
    line = (tmp_path / ".devsim" / "runs" / "run-1.jsonl").read_text(encoding="utf-8")
    assert len(line.encode()) <= store.max_event_bytes + 1
    assert "super-secret" not in line
    assert json.loads(line)["result_summary_truncated"] is True
    assert store.read_run_events("run-1")[0]["status"] == "completed"
