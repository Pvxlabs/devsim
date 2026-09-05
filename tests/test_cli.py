import json
from pathlib import Path

from devsim.cli import dispatch


def test_init_creates_manifest_and_state_directory(tmp_path: Path) -> None:
    result = dispatch(type("Args", (), {"command": "init", "project_dir": tmp_path})())
    assert result["ok"] is True
    assert (tmp_path / "devsim.yaml").exists()
    assert (tmp_path / ".devsim").is_dir()
    assert ".devsim/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / "devsim" / "scenarios").is_dir()


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
