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
