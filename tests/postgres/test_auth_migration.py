from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def test_populated_0008_upgrades_and_empty_auth_downgrades() -> None:
    source = os.getenv("TEST_DATABASE_URL")
    if not source:
        pytest.skip("TEST_DATABASE_URL is not configured")
    source_url = make_url(source)
    database = f"illinois_lottery_test_auth_migration_{uuid4().hex[:10]}"
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = source_url.set(database=database)
    target = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
        configuration = Config("alembic.ini")
        configuration.set_main_option(
            "sqlalchemy.url", target_url.render_as_string(hide_password=False).replace("%", "%%")
        )
        command.upgrade(configuration, "0008_review_remediations")
        target = create_engine(target_url, future=True)
        with target.begin() as connection:
            before = connection.execute(
                text("SELECT count(*) FROM analytics_model_versions")
            ).scalar_one()
        command.upgrade(configuration, "0009_authentication")
        assert {
            "app_users",
            "user_identities",
            "user_sessions",
            "oidc_login_attempts",
            "auth_events",
        } <= set(inspect(target).get_table_names())
        with target.begin() as connection:
            after = connection.execute(
                text("SELECT count(*) FROM analytics_model_versions")
            ).scalar_one()
        assert after == before
        command.downgrade(configuration, "0008_review_remediations")
        assert "app_users" not in inspect(target).get_table_names()
        command.upgrade(configuration, "head")
    finally:
        if target is not None:
            target.dispose()
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND backend_type='client backend' "
                        "AND usename=current_user AND pid <> pg_backend_pid()"
                    ),
                    {"name": database},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
        admin.dispose()
