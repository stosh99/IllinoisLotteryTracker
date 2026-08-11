"""Strict local return-path allowlist."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

ALLOWED_RETURN_PATHS = frozenset({"/", "/account"})


def validate_return_path(value: str | None) -> str:
    if value is None:
        return "/"
    if not value or len(value) > 512 or any(ord(character) < 0x20 for character in value):
        raise ValueError("invalid return path")
    decoded = unquote(value, errors="strict")
    parsed = urlsplit(decoded)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "\\" in decoded
        or decoded.startswith("//")
        or decoded not in ALLOWED_RETURN_PATHS
    ):
        raise ValueError("invalid return path")
    return decoded
