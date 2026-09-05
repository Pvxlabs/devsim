from pathlib import Path

import pytest

from devsim.adapters import AdapterRegistry, CommandAdapter, HTTPAdapter
from devsim.errors import AdapterError


def test_api_is_an_explicit_http_alias() -> None:
    http = HTTPAdapter("http://127.0.0.1:8000")
    assert AdapterRegistry([http]).get("api") is http


def test_unconfigured_adapter_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AdapterError):
        AdapterRegistry([CommandAdapter(tmp_path)]).get("api")


def test_registry_resolves_complete_action_name() -> None:
    adapter = HTTPAdapter("http://127.0.0.1:8000")
    registry = AdapterRegistry()
    registry.register("api.request", adapter)
    assert registry.resolve("api.request") is adapter


def test_registry_rejects_unknown_action_clearly() -> None:
    with pytest.raises(AdapterError, match="action adapter 'api.request' is not registered"):
        AdapterRegistry().resolve("api.request")


def test_registry_duplicate_registration_is_deterministic() -> None:
    registry = AdapterRegistry()
    registry.register("command.run", CommandAdapter(Path.cwd()))
    with pytest.raises(AdapterError, match="already registered"):
        registry.register("command.run", CommandAdapter(Path.cwd()))
