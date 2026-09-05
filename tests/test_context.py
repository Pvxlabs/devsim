from pathlib import Path

import pytest

from devsim.context import normalize_result, resolve
from devsim.errors import ContextError
from devsim.models import ActionContext
from devsim.rng import DeterministicRNG


def make_context(tmp_path: Path) -> ActionContext:
    return ActionContext(
        str(tmp_path),
        "run-123",
        "sample",
        42,
        1000,
        2,
        DeterministicRNG(42),
        {"create-session": normalize_result({"status": 201, "body": {"id": 7}})},
    )


def test_context_resolves_env_run_and_previous_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("API_TOKEN", "secret-token")
    value = resolve(
        {
            "token": "${env.API_TOKEN}",
            "seed": "${run.seed}",
            "path": "/sessions/${steps.create-session.json.id}/events",
        },
        make_context(tmp_path),
    )
    assert value == {"token": "secret-token", "seed": 42, "path": "/sessions/7/events"}


def test_context_preserves_native_full_placeholder_type(tmp_path: Path) -> None:
    assert resolve("${run.seed}", make_context(tmp_path)) == 42


def test_context_missing_reference_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ContextError, match="not set"):
        resolve("${env.MISSING_TOKEN}", make_context(tmp_path))
    with pytest.raises(ContextError, match="no completed result"):
        resolve("${steps.missing.json.id}", make_context(tmp_path))


def test_context_does_not_execute_python(tmp_path: Path) -> None:
    with pytest.raises(ContextError, match="unsupported variable reference"):
        resolve("${__import__('os').getcwd()}", make_context(tmp_path))
