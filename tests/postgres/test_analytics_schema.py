"""PostgreSQL schema, seed, immutability, and ownership checks for analytics."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from illinois_lottery_tracker.analytics.persistence import MODEL_PARAMETERS


@pytest.fixture
def connection():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    with engine.connect() as database_connection:
        transaction = database_connection.begin()
        yield database_connection
        transaction.rollback()
    engine.dispose()


def test_all_core_tables_and_seeded_model_exist(connection):
    expected = {
        "analytics_model_versions",
        "analytics_runs",
        "analytics_lag_calibrations",
        "analytics_lag_game_estimates",
        "analytics_game_metrics",
        "analytics_tier_metrics",
        "analytics_strategy_metrics",
        "analytics_quality_issues",
    }
    assert expected <= set(inspect(connection).get_table_names())
    row = connection.execute(
        text(
            "SELECT model_name, semantic_version, parameters, parameters_sha256 "
            "FROM analytics_model_versions"
        )
    ).mappings().one()
    canonical = json.dumps(MODEL_PARAMETERS, sort_keys=True, separators=(",", ":"))
    assert row["model_name"] == "core_ticket_model"
    assert row["semantic_version"] == "1.0.0"
    assert row["parameters"] == MODEL_PARAMETERS
    assert row["parameters_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_model_version_is_database_immutable(connection):
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError, match="immutable"):
        connection.execute(
            text("UPDATE analytics_model_versions SET code_version = 'changed'")
        )
    nested.rollback()


def test_model_cannot_be_approved_without_a_passed_backtest(connection):
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError, match="successful passed promotion backtest"):
        connection.execute(
            text(
                """
                UPDATE analytics_model_versions
                SET approval_status='approved', approval_decided_at=now(),
                    approval_reason='invalid approval without evidence'
                """
            )
        )
    nested.rollback()


def test_run_child_cascades_but_source_and_model_ownership_restrict(connection):
    source = _source_run(connection, "a", hour=10)
    model = connection.execute(
        text("SELECT id FROM analytics_model_versions")
    ).scalar_one()
    analytics_run = connection.execute(
        text(
            """
            INSERT INTO analytics_runs (
              model_version_id, as_of_scrape_run_id, as_of_observed_at, started_at
            )
            SELECT :model, id, source_observed_at, source_observed_at
            FROM scrape_runs WHERE id=:source RETURNING id
            """
        ),
        {"model": model, "source": source},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO analytics_quality_issues "
            "(analytics_run_id, code, severity, entity_type, message, details) "
            "VALUES (:run, 'TEST', 'info', 'run', 'test', '{}'::jsonb)"
        ),
        {"run": analytics_run},
    )
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError):
        connection.execute(text("DELETE FROM scrape_runs WHERE id=:id"), {"id": source})
    nested.rollback()
    connection.execute(
        text("DELETE FROM analytics_runs WHERE id=:id"), {"id": analytics_run}
    )
    assert connection.execute(
        text("SELECT count(*) FROM analytics_quality_issues WHERE analytics_run_id=:id"),
        {"id": analytics_run},
    ).scalar_one() == 0
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError, match="immutable"):
        connection.execute(
            text("DELETE FROM analytics_model_versions WHERE id=:id"), {"id": model}
        )
    nested.rollback()


def _source_run(connection, sha_character: str, *, hour: int) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO scrape_runs (
              started_at, finished_at, status, workflow, source_observed_at,
              source_date, source_sha256, is_complete, parsed_game_count,
              parsed_prize_tier_count, pipeline_version
            ) VALUES (
              make_timestamptz(2026,8,8,:hour,0,0,'UTC'),
              make_timestamptz(2026,8,8,:hour,0,0,'UTC'), 'success',
              'unpaid_prizes', make_timestamptz(2026,8,8,:hour,0,0,'UTC'),
              '2026-08-08', :sha, true, 1, 1, 'test'
            ) RETURNING id
            """
        ),
        {"hour": hour, "sha": sha_character * 64},
    ).scalar_one()
