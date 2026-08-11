"""Smoke checks for an Alembic-managed PostgreSQL test database."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from illinois_lottery_tracker import analytics_models, auth_models  # noqa: F401
from illinois_lottery_tracker.models import Base


@pytest.fixture(scope="module")
def postgres_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    yield engine
    engine.dispose()


def test_database_is_at_single_alembic_head(postgres_engine):
    configuration = Config("alembic.ini")
    script = ScriptDirectory.from_config(configuration)
    assert len(script.get_heads()) == 1
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            script.get_current_head()
        )


def test_baseline_tables_and_columns_match_metadata(postgres_engine):
    inspector = inspect(postgres_engine)
    expected_tables = set(Base.metadata.tables)
    assert expected_tables <= set(inspector.get_table_names())
    for table_name, table in Base.metadata.tables.items():
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert actual_columns == {column.name for column in table.columns}


def test_populated_0009_adaptive_state_upgrades_to_simplified_model(postgres_engine):
    """The cleanup removes only derived analytics and preserves source data."""

    source_url = postgres_engine.url
    target_database = f"illinois_lottery_test_migration_0009_{uuid4().hex[:12]}"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=target_database)
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    target_engine = None
    created = False
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{target_database}"')
            created = True

        configuration = Config("alembic.ini")
        configuration.set_main_option(
            "sqlalchemy.url",
            target_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        command.upgrade(configuration, "0009_authentication")

        target_engine = create_engine(target_url, future=True)
        with target_engine.begin() as connection:
            source_id = connection.execute(
                text(
                    """
                    INSERT INTO scrape_runs (
                      started_at, finished_at, status, workflow, source_observed_at,
                      source_date, source_sha256, is_complete, parsed_game_count,
                      parsed_prize_tier_count, pipeline_version
                    ) VALUES (
                      now(), now(), 'success', 'unpaid_prizes', now(),
                      (now() AT TIME ZONE 'America/Chicago')::date, repeat('f', 64),
                      true, 1, 1, 'test'
                    )
                    RETURNING id
                    """
                )
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO analytics_runs (
                      model_version_id, as_of_scrape_run_id, as_of_observed_at,
                      started_at, finished_at, status, publishable
                    ) SELECT id, :source, now(), now(), now(), 'success', false
                    FROM analytics_model_versions
                    """
                ),
                {"source": source_id},
            )

        command.upgrade(configuration, "head")

        with target_engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == ScriptDirectory.from_config(configuration).get_current_head()
            model = connection.execute(
                text(
                    """
                    SELECT semantic_version, parameters
                    FROM analytics_model_versions
                    WHERE model_name = 'core_ticket_model'
                    """
                )
            ).mappings().one()
            assert model["semantic_version"] == "2.0.0"
            assert model["parameters"]["mail_claim_reporting_lag_days"] == 24
            assert connection.execute(text("SELECT count(*) FROM scrape_runs")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM analytics_runs")).scalar_one() == 0
            tables = set(inspect(connection).get_table_names())
            assert "analytics_backtest_runs" not in tables
            assert "analytics_lag_calibrations" not in tables
    finally:
        if target_engine is not None:
            target_engine.dispose()
        if created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND backend_type='client backend' "
                        "AND usename=current_user AND pid <> pg_backend_pid()"
                    ),
                    {"name": target_database},
                )
                connection.exec_driver_sql(f'DROP DATABASE "{target_database}"')
        admin_engine.dispose()
