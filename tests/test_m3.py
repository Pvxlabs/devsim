from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from devsim.cli import build_parser, dispatch, init_project, preview_status
from devsim.config import load_manifest
from devsim.control import _make_server
from devsim.errors import AdapterError, SafetyError
from devsim.models import Manifest, RuntimeState
from devsim.runner import ScenarioRunner
from devsim.runtime import RuntimeOwnership
from devsim.schema import ColumnModel, ForeignKeyModel, SchemaError, SchemaModel, TableModel, _model_from_rows
from devsim.seed import (
    GeneratorRegistry,
    SeedSchemaDriftError,
    SeedTransactionError,
    _build_row,
    build_seed_plan,
    _execute_connection,
)
from devsim.state import StateStore


def schema_fixture() -> SchemaModel:
    return SchemaModel(
        (
            TableModel(
                "accounts",
                columns=(
                    ColumnModel("id", "int4", False, primary_key=True),
                    ColumnModel("email", "text", False, unique=True),
                ),
            ),
            TableModel(
                "sessions",
                columns=(
                    ColumnModel("id", "int4", False, primary_key=True),
                    ColumnModel("account_id", "int4", False),
                    ColumnModel("status", "text", False),
                ),
                foreign_keys=(ForeignKeyModel("account_id", "accounts", "id"),),
            ),
        )
    )


def seed_config() -> dict:
    return {
        "mode": "schema",
        "plan": {
            "tables": {
                "accounts": {"count": 2, "columns": {"email": {"generator": "internet.email"}}},
                "sessions": {
                    "count": 4,
                    "columns": {"status": {"choice": ["active", "completed"]}},
                },
            }
        },
        "profiles": {"minimal": {"accounts": 1, "sessions": 1}},
    }


def test_schema_model_builds_graph_and_detects_cycles() -> None:
    schema = schema_fixture()
    assert schema.dependency_graph() == {"accounts": (), "sessions": ("accounts",)}
    assert schema.dependency_order() == ("accounts", "sessions")
    cyclic = SchemaModel(
        (
            TableModel("a", columns=(ColumnModel("b_id", "int4", False),), foreign_keys=(ForeignKeyModel("b_id", "b", "id"),)),
            TableModel("b", columns=(ColumnModel("a_id", "int4", False),), foreign_keys=(ForeignKeyModel("a_id", "a", "id"),)),
        )
    )
    with pytest.raises(SchemaError, match="CYCLIC_SEED_DEPENDENCY"):
        cyclic.dependency_order()


def test_schema_introspection_rows_are_generic_and_serializable() -> None:
    model = _model_from_rows(
        [("public", "accounts")],
        [("public", "accounts", "id", "integer", "NO", "nextval('accounts_id_seq'::regclass)", "int4")],
        [("public", "accounts", "id", "PRIMARY KEY")],
        [],
        [],
    )
    assert model.to_dict()["tables"][0]["primary_keys"] == ["id"]
    assert json.loads(json.dumps(model.to_dict()))["tables"][0]["name"] == "accounts"


def test_seed_plan_profiles_and_drift() -> None:
    plan = build_seed_plan(schema_fixture(), seed_config(), "minimal")
    assert plan.dependency_order == ("accounts", "sessions")
    assert plan.estimated_rows == 2
    with pytest.raises(SeedSchemaDriftError, match=r"column\(s\) no longer exist"):
        build_seed_plan(schema_fixture(), {"mode": "schema", "plan": {"tables": {"accounts": {"columns": {"missing": "string"}}}}})
    with pytest.raises(Exception, match="profile .* was not found"):
        build_seed_plan(schema_fixture(), seed_config(), "unknown")


def test_generators_and_foreign_keys_are_deterministic() -> None:
    plan = build_seed_plan(schema_fixture(), seed_config(), "default")
    registry = GeneratorRegistry()
    assert "internet.email" in registry.names()
    from devsim.rng import DeterministicRNG

    def generate(seed: int):
        rng = DeterministicRNG(seed)
        generated = {"accounts": [], "sessions": []}
        account_plan, session_plan = plan.tables
        for index in range(account_plan.count):
            generated["accounts"].append(_build_row(schema_fixture().table_map["accounts"], account_plan, generated, rng, index, registry))
        for index in range(session_plan.count):
            generated["sessions"].append(_build_row(schema_fixture().table_map["sessions"], session_plan, generated, rng, index, registry))
        return generated

    first = generate(42)
    second = generate(42)
    assert first == second
    assert {row["account_id"] for row in first["sessions"]} <= {1, 2}


class FakeCursor:
    def __init__(self, fail=False):
        self.fail = fail
        self.sql: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.sql.append(sql)
        if self.fail:
            raise RuntimeError("insert failed")

    def fetchone(self):
        return (1,)


class FakeConnection:
    def __init__(self, fail=False):
        self.cursor_obj = FakeCursor(fail)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_seed_transaction_rolls_back_and_quotes_sql() -> None:
    plan = build_seed_plan(schema_fixture(), seed_config())
    connection = FakeConnection()
    result = _execute_connection(connection, schema_fixture(), plan, 42)
    assert result["inserted_rows"] == 6
    assert connection.commits == 1
    assert 'INSERT INTO "public"."accounts"' in connection.cursor_obj.sql[0]

    failed = FakeConnection(fail=True)
    with pytest.raises(SeedTransactionError, match="SEED_TRANSACTION_ROLLBACK"):
        _execute_connection(failed, schema_fixture(), plan, 42)
    assert failed.rollbacks == 1


def test_safety_rejects_production_database_and_browser_url() -> None:
    from devsim.safety import assert_database_url_safe, assert_observation_url_safe

    with pytest.raises(SafetyError, match="SEED_TARGET_UNSAFE"):
        assert_database_url_safe("postgresql://u:p@db.production.example.com/app")
    with pytest.raises(SafetyError, match="BROWSER_TARGET_UNSAFE"):
        assert_observation_url_safe("https://app.example.com")


def test_runner_requires_observation_config_for_browser_actions(tmp_path: Path) -> None:
    with pytest.raises(AdapterError, match="BROWSER_OBSERVATION_CONFIG_REQUIRED"):
        ScenarioRunner(tmp_path, "sample", "http://127.0.0.1:8000", StateStore(tmp_path), ("browser",), {})


def test_control_api_health_and_token_boundary(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\n"
        "database: {engine: postgres}\nruntime: {base_url: http://127.0.0.1:8000}\n",
        encoding="utf-8",
    )
    manifest = load_manifest(tmp_path)
    server = _make_server(tmp_path, manifest, "127.0.0.1", 0, None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/health") as response:
            assert json.loads(response.read())["status"] == "healthy"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    protected = _make_server(tmp_path, manifest, "127.0.0.1", 0, "secret")
    protected_thread = threading.Thread(target=protected.serve_forever, daemon=True)
    protected_thread.start()
    try:
        request = Request(f"http://127.0.0.1:{protected.server_port}/health")
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 401
        request.add_header("Authorization", "Bearer secret")
        with urlopen(request) as response:
            assert response.status == 200
    finally:
        protected.shutdown()
        protected.server_close()
        protected_thread.join(timeout=2)


def test_control_api_profiles_are_unique_and_include_default(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\n"
        "database: {engine: postgres}\nseed: {mode: schema, profiles: {default: {}, minimal: {}}}\n"
        "runtime: {base_url: http://127.0.0.1:8000}\n",
        encoding="utf-8",
    )
    manifest = load_manifest(tmp_path)
    server = _make_server(tmp_path, manifest, "127.0.0.1", 0, None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/scenarios") as response:
            profiles = json.loads(response.read())["profiles"]
        assert profiles == ["default", "minimal"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_preview_preset_resets_before_starting_persistent_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\n"
        "database: {engine: postgres}\n"
        "seed: {mode: schema, profiles: {busy: {accounts: 10}}}\n"
        "presets: {normal: {seed_profile: busy, scenario: active-runtime}}\n"
        "runtime: {base_url: http://127.0.0.1:8000}\n",
        encoding="utf-8",
    )
    scenario_dir = tmp_path / "devsim" / "scenarios"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "active.yaml").write_text(
        "version: 1\nname: active-runtime\nruntime: {mode: persistent}\ntimeline: []\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, int, str]] = []

    class FakeLifecycle:
        def __init__(self, *_args):
            pass

        def run(self, operation: str, *, seed: int, profile: str) -> RuntimeState:
            calls.append((operation, seed, profile))
            return RuntimeState(project="sample")

    def fake_start(*args, **_kwargs):
        seed = args[5]
        calls.append(("start", seed, ""))
        return {"status": "running", "run_id": "run-1", "scenario": "active-runtime", "seed": seed}

    monkeypatch.setattr("devsim.cli.Lifecycle", FakeLifecycle)
    monkeypatch.setattr("devsim.cli._start_managed_scenario", fake_start)
    args = build_parser().parse_args(["--project-dir", str(tmp_path), "preview", "normal", "--seed", "42"])

    result = dispatch(args)

    assert calls == [("reset", 42, "busy"), ("start", 42, "")]
    assert result["profile"] == "normal"
    assert result["seed_profile"] == "busy"
    assert result["scenario"] == "active-runtime"
    assert result["project"] == "sample"
    assert result["application"]["url"] == "http://127.0.0.1:8000"
    assert result["control"]["url"] == "http://127.0.0.1:8001"
    assert result["run_id"] == "run-1"


def test_preview_status_reads_profile_from_runtime_ownership(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\n"
        "database: {engine: postgres}\nruntime: {base_url: http://127.0.0.1:8000}\n",
        encoding="utf-8",
    )
    manifest = load_manifest(tmp_path)
    store = StateStore(tmp_path)
    ownership = RuntimeOwnership(tmp_path)
    state = store.load(manifest.project_name)
    state.status = "running"
    state.scenario = "normal"
    state.seed = 42
    state.run_id = "run-1"
    state.last_operation = "scenario.run"
    store.save(state)
    ownership.claim({"run_id": "run-1", "pid": 0, "scenario": "normal", "seed": 42, "profile": "normal", "status": "STARTING"})

    result = preview_status(tmp_path, manifest, store, ownership)

    assert result["profile"] == "normal"
    assert result["runtime"]["process_alive"] is False
    ownership.clear()


def test_init_generates_non_destructive_seed_draft(tmp_path: Path) -> None:
    result = init_project(tmp_path)
    assert result["ok"] is True
    draft = tmp_path / "devsim" / "seed.yaml"
    assert draft.exists()
    original = (tmp_path / "devsim.yaml").read_text(encoding="utf-8")
    second = init_project(tmp_path)
    assert second["ok"] is True
    assert "devsim.yaml" in second["kept"]
    assert (tmp_path / "devsim.yaml").read_text(encoding="utf-8") == original
