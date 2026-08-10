"""Smoke checks for an Alembic-managed PostgreSQL test database."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from illinois_lottery_tracker import analytics_models  # noqa: F401
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


def test_populated_0007_failed_promotion_upgrades_to_0008(postgres_engine):
    """Exercise the revision boundary that fresh zero-to-head tests cannot cover."""

    source_url = postgres_engine.url
    target_database = f"illinois_lottery_test_migration_0007_{uuid4().hex[:12]}"
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
        command.upgrade(configuration, "0007_legacy_metric_comments")

        target_engine = create_engine(target_url, future=True)
        with target_engine.begin() as connection:
            backtest_id = connection.execute(
                text(
                    """
                    INSERT INTO analytics_backtest_runs (
                      model_version_id, cutoff_start_at, cutoff_end_at,
                      horizons, parameters, parameters_sha256, started_at,
                      finished_at, status, aggregate_results, promotion_status,
                      promotion_report
                    )
                    SELECT id, now() - interval '30 days', now(),
                      '[7, 14, 30]'::jsonb, '{}'::jsonb, repeat('f', 64),
                      now() - interval '1 minute', now(), 'success', '{}'::jsonb,
                      'failed', '{"passed": false}'::jsonb
                    FROM analytics_model_versions
                    WHERE model_name = 'core_ticket_model'
                    RETURNING id
                    """
                )
            ).scalar_one()

        command.upgrade(configuration, "0008_review_remediations")

        with target_engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0008_review_remediations"
            model = connection.execute(
                text(
                    """
                    SELECT approval_status, approval_backtest_run_id,
                           approval_decided_at, approval_reason
                    FROM analytics_model_versions
                    WHERE model_name = 'core_ticket_model'
                    """
                )
            ).mappings().one()
            assert model["approval_status"] == "rejected"
            assert model["approval_backtest_run_id"] == backtest_id
            assert model["approval_decided_at"] is not None
            assert model["approval_reason"]
    finally:
        if target_engine is not None:
            target_engine.dispose()
        if created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name"
                    ),
                    {"name": target_database},
                )
                connection.exec_driver_sql(f'DROP DATABASE "{target_database}"')
        admin_engine.dispose()
