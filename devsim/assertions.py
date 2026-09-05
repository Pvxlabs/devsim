from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ExpectationError
from .models import ActionResult


def assert_expectations(expect: Mapping[str, Any], result: ActionResult, action: str) -> None:
    if not isinstance(expect, Mapping):
        raise ExpectationError(f"{action}: expect must be a mapping")
    unknown = sorted(set(expect) - {"status", "json", "exit_code"})
    if unknown:
        raise ExpectationError(f"{action}: unsupported expectation(s): {', '.join(unknown)}")

    if "status" in expect:
        actual = result.data.get("status")
        expected = expect["status"]
        allowed = _allowed_ints(expected, f"{action}: expect.status")
        if actual not in allowed:
            raise ExpectationError(f"{action}: expected status {sorted(allowed)}, got {actual!r}")

    if "json" in expect:
        expected_json = expect["json"]
        if not isinstance(expected_json, Mapping):
            raise ExpectationError(f"{action}: expect.json must be a mapping")
        actual_json = result.data.get("json", result.data.get("body"))
        if not isinstance(actual_json, Mapping) or not _mapping_subset(expected_json, actual_json):
            raise ExpectationError(
                f"{action}: JSON body did not contain expected subset {dict(expected_json)!r}; got {actual_json!r}"
            )

    if "exit_code" in expect:
        expected = expect["exit_code"]
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ExpectationError(f"{action}: expect.exit_code must be an integer")
        actual = result.data.get("exit_code", result.data.get("returncode"))
        if actual != expected:
            raise ExpectationError(f"{action}: expected exit_code {expected}, got {actual!r}")


def expectation_accepts_result(expect: Mapping[str, Any], result: ActionResult) -> bool:
    """Allow an intentionally expected HTTP status or exit code to be non-2xx/zero."""
    if result.ok:
        return True
    if "status" in expect and result.data.get("status") in _allowed_ints(expect["status"], "expect.status"):
        return True
    if "exit_code" in expect and result.data.get("exit_code", result.data.get("returncode")) == expect["exit_code"]:
        return True
    return False


def _allowed_ints(value: Any, field: str) -> set[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {value}
    if isinstance(value, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return set(value)
    raise ExpectationError(f"{field} must be an integer or list of integers")


def _mapping_subset(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    for key, value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(value, Mapping):
            if not isinstance(actual_value, Mapping) or not _mapping_subset(value, actual_value):
                return False
        elif actual_value != value:
            return False
    return True
