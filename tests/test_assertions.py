import pytest

from devsim.assertions import assert_expectations, expectation_accepts_result
from devsim.errors import ExpectationError
from devsim.models import ActionResult


def test_http_expectations_check_status_and_nested_json_subset() -> None:
    assert_expectations(
        {"status": 200, "json": {"status": "active", "nested": {"id": 3}}},
        ActionResult(True, {"status": 200, "json": {"status": "active", "nested": {"id": 3, "extra": True}}}),
        "api.request",
    )


def test_command_expectation_checks_exit_code() -> None:
    assert_expectations({"exit_code": 0}, ActionResult(True, {"exit_code": 0}), "command.run")


def test_expectation_failure_is_structured() -> None:
    with pytest.raises(ExpectationError, match="expected status"):
        assert_expectations({"status": 201}, ActionResult(True, {"status": 200}), "api.request")


def test_expected_non_2xx_status_is_an_accepted_result() -> None:
    result = ActionResult(False, {"status": 404, "json": {"error": "missing"}})
    assert_expectations({"status": 404, "json": {"error": "missing"}}, result, "api.request")
    assert expectation_accepts_result({"status": 404}, result) is True
