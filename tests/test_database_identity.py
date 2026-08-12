"""Environment/database cross-wiring must fail before application work."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.database_identity import (
    DatabaseIdentityError,
    validate_identity_configuration,
    verify_engine_identity,
    verify_url_identity,
)


def test_production_requires_expected_database_name() -> None:
    settings = Settings(
        database_url="postgresql://example/prod",
        raw_data_dir="data/raw",
        app_env="production",
    )
    with pytest.raises(DatabaseIdentityError, match="EXPECTED_DATABASE_NAME"):
        validate_identity_configuration(settings)


def test_url_database_mismatch_fails_closed() -> None:
    with pytest.raises(DatabaseIdentityError, match="identity mismatch"):
        verify_url_identity(
            "postgresql://example/illinois_lottery_tracker_dev",
            "illinois_lottery_tracker_prod",
        )


def test_sqlite_connection_identity_is_checked() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        raw_data_dir="data/raw",
        app_env="test",
        expected_database_name=":memory:",
    )
    try:
        verify_engine_identity(engine, settings)
    finally:
        engine.dispose()


def test_sqlite_connection_mismatch_fails() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        raw_data_dir="data/raw",
        app_env="test",
        expected_database_name="wrong",
    )
    try:
        with pytest.raises(DatabaseIdentityError, match="identity mismatch"):
            verify_engine_identity(engine, settings)
    finally:
        engine.dispose()
