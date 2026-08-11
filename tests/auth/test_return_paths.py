from __future__ import annotations

import pytest

from illinois_lottery_tracker.auth.return_paths import validate_return_path


@pytest.mark.parametrize("value", [None, "/", "/account"])
def test_allowlisted_return_paths(value: str | None) -> None:
    assert validate_return_path(value) == (value or "/")


@pytest.mark.parametrize(
    "value",
    [
        "https://attacker.example/",
        "//attacker.example/",
        "///attacker.example/",
        "\\\\attacker.example",
        "/%5c%5cattacker.example",
        "/%2f%2fattacker.example",
        "https:%2f%2fattacker.example",
        "/account#fragment",
        "/account?next=https://attacker.example",
        "/%00account",
        "/ACCOUNT",
        "/my-tickets/../admin",
        "/%252f%252fattacker.example",
    ],
)
def test_rejects_open_redirect_and_nonallowlisted_paths(value: str) -> None:
    with pytest.raises((ValueError, UnicodeError)):
        validate_return_path(value)
