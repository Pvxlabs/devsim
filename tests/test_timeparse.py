import pytest

from devsim.errors import ConfigError
from devsim.timeparse import parse_duration


def test_parse_supported_units() -> None:
    assert parse_duration("250ms") == 250
    assert parse_duration("2s") == 2000
    assert parse_duration("1.5m") == 90_000


def test_rejects_invalid_duration() -> None:
    with pytest.raises(ConfigError):
        parse_duration("2h")


def test_numeric_duration_is_seconds() -> None:
    assert parse_duration(2) == 2000
