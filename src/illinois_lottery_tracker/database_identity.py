"""Fail-closed checks that bind a process to its intended database."""

from __future__ import annotations

from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from .config import Settings


class DatabaseIdentityError(RuntimeError):
    """Raised before work can run against an unexpected database."""


def validate_identity_configuration(settings: Settings) -> None:
    """Reject unsafe production configuration before opening a connection."""
    if settings.app_env == "production" and not settings.expected_database_name:
        raise DatabaseIdentityError(
            "APP_ENV=production requires EXPECTED_DATABASE_NAME"
        )
    if settings.expected_database_name and not settings.database_url:
        raise DatabaseIdentityError(
            "EXPECTED_DATABASE_NAME requires DATABASE_URL"
        )


def configured_database_name(database_url: str) -> str | None:
    return make_url(database_url).database


def verify_url_identity(database_url: str, expected_database_name: str | None) -> None:
    """Guard offline operations that cannot query the connected database."""
    if expected_database_name is None:
        return
    configured = configured_database_name(database_url)
    if configured != expected_database_name:
        raise DatabaseIdentityError(
            "database identity mismatch: "
            f"expected {expected_database_name!r}, URL names {configured!r}"
        )


def verify_connection_identity(
    connection: Connection, expected_database_name: str | None
) -> None:
    if expected_database_name is None:
        return
    if connection.dialect.name == "postgresql":
        actual = connection.scalar(text("SELECT current_database()"))
    else:
        actual = configured_database_name(str(connection.engine.url))
    if actual != expected_database_name:
        raise DatabaseIdentityError(
            "database identity mismatch: "
            f"expected {expected_database_name!r}, connected to {actual!r}"
        )


def verify_engine_identity(engine: Engine, settings: Settings) -> None:
    validate_identity_configuration(settings)
    verify_url_identity(settings.require_database_url(), settings.expected_database_name)
    if settings.expected_database_name is None:
        return
    with engine.connect() as connection:
        verify_connection_identity(connection, settings.expected_database_name)
