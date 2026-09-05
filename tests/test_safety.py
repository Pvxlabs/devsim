from devsim.errors import SafetyError
from devsim.models import Manifest
from devsim.safety import assert_safe


def manifest(mode: str, base_url: str) -> Manifest:
    return Manifest(1, "sample", mode, "postgres", {}, None, "scenarios", base_url, ("http", "command"))


def test_public_endpoint_is_denied_for_reset() -> None:
    try:
        assert_safe(manifest("development", "https://api.example.com"), "reset")
    except SafetyError:
        return
    raise AssertionError("public endpoint should be denied")


def test_local_endpoint_is_allowed() -> None:
    assert_safe(manifest("development", "http://127.0.0.1:8000"), "reset")


def test_production_mode_is_denied() -> None:
    try:
        assert_safe(manifest("production", "http://127.0.0.1:8000"), "seed")
    except SafetyError:
        return
    raise AssertionError("production mode should be denied")
