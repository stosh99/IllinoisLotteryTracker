"""Authentication dependencies shared by the existing FastAPI application."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .auth.types import AuthPrincipal


@dataclass(frozen=True)
class RequestAuth:
    principal: AuthPrincipal | None
    raw_session_token: str | None


def raw_cookie_values(request: Request, name: str) -> list[str]:
    """Read all configured-name values without first/last duplicate collapse."""

    values: list[str] = []
    for header_name, header_value in request.scope.get("headers", []):
        if header_name.lower() != b"cookie":
            continue
        for part in header_value.decode("latin-1").split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == name:
                values.append(value)
    return values
