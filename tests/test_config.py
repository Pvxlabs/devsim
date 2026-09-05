from pathlib import Path

import pytest

from devsim.config import load_manifest
from devsim.errors import ConfigError


def write_manifest(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_manifest_loads_command_and_adapter_contract(tmp_path: Path) -> None:
    write_manifest(
        tmp_path / "devsim.yaml",
        """version: 1
project:
  name: sample
environment:
  mode: development
database:
  engine: postgres
  lifecycle:
    reset: {command: echo reset, timeout: 5}
seed:
  command: echo seed
runtime:
  base_url: http://127.0.0.1:8000
  adapters:
    - type: http
    - type: command
""",
    )
    manifest = load_manifest(tmp_path)
    assert manifest.project_name == "sample"
    assert manifest.lifecycle["reset"].timeout == 5
    assert manifest.adapter_types == ("http", "command")


def test_manifest_rejects_non_postgres(tmp_path: Path) -> None:
    write_manifest(
        tmp_path / "devsim.yaml",
        """version: 1
project: {name: sample}
database: {engine: sqlite}
""",
    )
    with pytest.raises(ConfigError, match="only database.engine=postgres"):
        load_manifest(tmp_path)
