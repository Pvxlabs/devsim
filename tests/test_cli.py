import json
from pathlib import Path

import pytest

from devsim.cli import build_parser, dispatch, emit, main
from devsim.config import load_manifest
from devsim.errors import ScenarioChangedError


def test_init_creates_manifest_and_state_directory(tmp_path: Path) -> None:
    result = dispatch(type("Args", (), {"command": "init", "project_dir": tmp_path})())
    assert result["ok"] is True
    assert (tmp_path / "devsim.yaml").exists()
    assert (tmp_path / ".devsim").is_dir()
    assert ".devsim/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / "devsim" / "scenarios").is_dir()
    manifest = load_manifest(tmp_path)
    assert manifest.seed_config["profiles"] == {"normal": {}, "minimal": {}}


def test_status_json_shape_is_serializable(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        """version: 1
project: {name: sample}
database: {engine: postgres}
runtime: {base_url: http://127.0.0.1:8000}
""",
        encoding="utf-8",
    )
    result = dispatch(type("Args", (), {"command": "status", "project_dir": tmp_path})())
    assert json.loads(json.dumps(result))["state"]["project"] == "sample"


def write_replay_project(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        """version: 1
project: {name: sample}
database: {engine: postgres}
scenarios: {path: scenarios}
runtime: {base_url: http://127.0.0.1:8000}
""",
        encoding="utf-8",
    )
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "demo.yaml").write_text(
        """version: 1
name: demo
clock: {speed: 1000}
timeline:
  - at: 0ms
    action: command.run
    with:
      command: 'printf "%s" "$DEVSIM_SEED"'
    expect: {exit_code: 0}
""",
        encoding="utf-8",
    )


def args(tmp_path: Path, scenario_command: str, **values: object):
    defaults = {"command": "scenario", "scenario_command": scenario_command, "project_dir": tmp_path}
    defaults.update(values)
    return type("Args", (), defaults)()


def test_inspect_and_replay_preserve_seed_and_identity(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    run_result = dispatch(args(tmp_path, "run", name="demo", seed=42))
    run_id = run_result["state"]["run_id"]
    inspected = dispatch(args(tmp_path, "inspect", run_id=run_id))
    assert inspected["scenario"] == "demo"
    assert inspected["seed"] == 42
    assert inspected["event_count"] == 1
    assert inspected["completed"] is True

    replayed = dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=False))
    assert replayed["state"]["seed"] == 42
    assert replayed["state"]["run_id"] != run_id


def test_replay_fails_closed_when_scenario_changed(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    run_id = dispatch(args(tmp_path, "run", name="demo", seed=7))["state"]["run_id"]
    scenario_path = tmp_path / "scenarios" / "demo.yaml"
    scenario_path.write_text(scenario_path.read_text(encoding="utf-8") + "description: changed\n", encoding="utf-8")
    with pytest.raises(ScenarioChangedError, match="scenario .* changed"):
        dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=False))
    replayed = dispatch(args(tmp_path, "replay", run_id=run_id, allow_changed_scenario=True))
    assert replayed["allow_changed_scenario"] is True


def test_run_id_path_traversal_is_rejected(tmp_path: Path) -> None:
    write_replay_project(tmp_path)
    with pytest.raises(Exception, match="invalid run id"):
        dispatch(args(tmp_path, "inspect", run_id="../state"))


def test_detect_is_read_only_and_reports_json_shape(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\ndependencies = ['psycopg']\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    result = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "detect", "--json"]))
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert result["project_detected"] is True
    assert result["integration"] == "no"
    assert result["database"]["engine"] == "postgres"
    assert result["capabilities"] == {"seed": False, "scenario": False, "browser": False}


def test_detect_marks_bootstrap_skeleton_as_partial(tmp_path: Path) -> None:
    dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "init"]))
    result = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "detect", "--json"]))
    assert result["integration"] == "partial"


def test_detect_marks_existing_devsim_without_manifest_as_partial(tmp_path: Path) -> None:
    (tmp_path / "devsim" / "scenarios").mkdir(parents=True)
    result = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "detect", "--json"]))
    assert result["project_detected"] is True
    assert result["integration"] == "partial"

    status = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "project", "status", "--json"]))
    assert status["status"] == "PARTIAL"
    assert status["ready"] is False


def test_project_status_distinguishes_not_configured_partial_ready_and_invalid(tmp_path: Path) -> None:
    status = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "project", "status", "--json"]))
    assert status["status"] == "NOT_CONFIGURED"
    assert status["ready"] is False

    (tmp_path / "devsim.yaml").write_text("version: 1\nproject: {name: sample}\ndatabase: {engine: postgres}\n", encoding="utf-8")
    partial = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "project", "status", "--json"]))
    assert partial["status"] == "PARTIAL"
    assert partial["ready"] is False

    (tmp_path / "devsim.yaml").write_text(
        """version: 1
project: {name: sample}
environment: {mode: development}
database:
  engine: postgres
  lifecycle:
    up: {command: /bin/true}
    migrate: {command: /bin/true}
    reset: {command: /bin/true}
    down: {command: /bin/true}
seed: {command: /bin/true}
scenarios: {path: devsim/scenarios}
runtime: {base_url: http://127.0.0.1:8000}
presets: {normal: {scenario: normal, seed_profile: normal}}
""",
        encoding="utf-8",
    )
    (tmp_path / "devsim" / "scenarios").mkdir(parents=True)
    (tmp_path / "devsim" / "scenarios" / "normal.yaml").write_text(
        "version: 1\nname: normal\nruntime: {mode: persistent}\ntimeline: []\n", encoding="utf-8"
    )
    ready = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "project", "status", "--json"]))
    assert ready["status"] == "READY"
    assert ready["ready"] is True

    (tmp_path / "devsim.yaml").write_text("version: 99\n", encoding="utf-8")
    invalid = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "project", "status", "--json"]))
    assert invalid["status"] == "INVALID"
    assert invalid["ready"] is False
    assert invalid["integration"]["manifest_status"] == "invalid"


def test_init_dry_run_and_inspect_do_not_promote_heuristics_to_canonical(tmp_path: Path) -> None:
    dry = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "init", "--dry-run", "--json"]))
    assert dry["dry_run"] is True
    assert not (tmp_path / "devsim.yaml").exists()
    assert any(item["action"] == "CREATE" and item["path"] == "devsim.yaml" for item in dry["actions"])

    inspected = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "init", "--inspect", "--json"]))
    assert inspected["status"] == "GENERATED_DRAFT"
    assert inspected["review_required"] is True
    assert not (tmp_path / "devsim.yaml").exists()
    assert (tmp_path / "devsim.yaml.draft").exists()


def test_project_validate_failure_has_stable_error_and_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "devsim.yaml").write_text("version: 99\n", encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        main(["--project-dir", str(tmp_path), "project", "validate", "--json"])
    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_MANIFEST"
    assert {"code", "message", "recoverable", "hint"} <= payload["error"].keys()


def test_error_code_extraction_ignores_uppercase_traceback_tokens() -> None:
    from devsim.cli import _error_payload
    from devsim.errors import LifecycleError

    payload = _error_payload(LifecycleError("command failed\nTraceback: NOQA: connection refused"))

    assert payload["code"] == "lifecycle_error"


def test_preview_stop_does_not_destroy_database_files(tmp_path: Path) -> None:
    (tmp_path / "devsim.yaml").write_text(
        "version: 1\nproject: {name: sample}\nenvironment: {mode: development}\ndatabase: {engine: postgres}\n",
        encoding="utf-8",
    )
    marker = tmp_path / "application.db.marker"
    marker.write_text("preserve", encoding="utf-8")
    result = dispatch(build_parser().parse_args(["--project-dir", str(tmp_path), "preview", "stop", "--json"]))
    assert result["destroyed"] is False
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_preview_human_output_uses_canonical_summary(capsys: pytest.CaptureFixture[str]) -> None:
    emit(
        {
            "ok": True,
            "project": "sample",
            "profile": "normal",
            "seed": 42,
            "runtime": {"status": "running"},
            "application": {"url": "http://127.0.0.1:8000"},
            "control": {"url": "http://127.0.0.1:8001"},
            "run_id": "run-1",
        },
        False,
    )
    assert capsys.readouterr().out.splitlines() == [
        "Preview ready",
        "Project: sample",
        "Profile: normal",
        "Seed: 42",
        "Runtime: RUNNING",
        "Application: http://127.0.0.1:8000",
        "Control: http://127.0.0.1:8001",
        "Run: run-1",
    ]
