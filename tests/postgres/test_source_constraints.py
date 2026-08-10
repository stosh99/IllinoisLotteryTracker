"""PostgreSQL-only checks for revision 0002 source constraints."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from scripts.audit_source_data import run_audit
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from illinois_lottery_tracker.source_quality import (
    canonical_structure_serialization,
    structure_fingerprint,
)


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


def test_invalid_tier_counts_are_rejected(connection):
    run_id = connection.execute(
        text(
            "INSERT INTO scrape_runs (started_at, status) "
            "VALUES (:now, 'running') RETURNING id"
        ),
        {"now": datetime.now(UTC)},
    ).scalar_one()
    game_id = connection.execute(
        text(
            "INSERT INTO games (game_number, name, is_active) "
            "VALUES ('x1', 'X', true) RETURNING id"
        )
    ).scalar_one()
    snapshot_id = connection.execute(
        text(
            "INSERT INTO game_snapshots (game_id, scrape_run_id, captured_at) "
            "VALUES (:game, :run, :now) RETURNING id"
        ),
        {"game": game_id, "run": run_id, "now": datetime.now(UTC)},
    ).scalar_one()
    nested = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO prize_tier_snapshots "
                "(game_snapshot_id, prize_amount, original_count, remaining_count, claimed_count) "
                "VALUES (:snapshot, 10, 5, 6, -1)"
            ),
            {"snapshot": snapshot_id},
        )
    nested.rollback()


def test_complete_duplicate_hash_is_rejected(connection):
    observed_at = datetime.now(UTC)
    parameters = {
        "now": observed_at,
        "source_date": observed_at.astimezone(ZoneInfo("America/Chicago")).date(),
        "sha": "a" * 64,
    }
    statement = text(
        """
        INSERT INTO scrape_runs (
            started_at, finished_at, status, workflow, source_observed_at,
            source_date, source_sha256, is_complete, parsed_game_count,
            parsed_prize_tier_count
        ) VALUES (
            :now, :now, 'success', 'unpaid_prizes', :now,
            :source_date, :sha, true, 1, 1
        )
        """
    )
    connection.execute(statement, parameters)
    nested = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(statement, parameters)
    nested.rollback()


def test_unchanged_daily_catalog_hash_is_allowed_and_not_an_audit_failure(connection):
    observed = datetime.now(UTC)
    statement = text(
        """
        INSERT INTO scrape_runs (
          started_at, finished_at, status, workflow, source_observed_at,
          source_date, source_sha256, is_complete, parsed_game_count,
          parsed_prize_tier_count, pipeline_version
        ) VALUES (
          :at, :at, 'success', 'instant_ticket_catalog', :at,
          (:at AT TIME ZONE 'America/Chicago')::date,
          :sha, true, 53, 0, 'catalog-test'
        )
        """
    )
    connection.execute(statement, {"at": observed, "sha": "b" * 64})
    connection.execute(
        statement,
        {"at": observed - timedelta(days=1), "sha": "b" * 64},
    )
    assert run_audit(connection)["failures"]["duplicate_complete_hashes"] == 0


def test_source_date_must_match_chicago_observation_date(connection):
    nested = connection.begin_nested()
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                """
                INSERT INTO scrape_runs (
                    started_at, status, source_observed_at, source_date
                ) VALUES (:now, 'running', :now, DATE '2026-08-09')
                """
            ),
            {"now": datetime(2026, 8, 8, 12, tzinfo=UTC)},
        )
    nested.rollback()


def test_python_and_postgresql_structure_fingerprints_match(connection):
    tiers = [(10, 100), (20, 25), (1000, 2)]
    serialization = canonical_structure_serialization(tiers)
    database_hash = connection.execute(
        text("SELECT encode(sha256(convert_to(:value, 'UTF8')), 'hex')"),
        {"value": serialization},
    ).scalar_one()
    assert database_hash == structure_fingerprint(tiers)
