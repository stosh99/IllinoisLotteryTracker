"""PostgreSQL tests for canonical latest-complete source views."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text


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


def _game(connection, number: str) -> int:
    return connection.execute(
        text(
            "INSERT INTO games (game_number, name, is_active) "
            "VALUES (:number, :name, true) RETURNING id"
        ),
        {"number": number, "name": f"GAME {number}"},
    ).scalar_one()


def _run(connection, observed_at: datetime, suffix: str, *, complete: bool = True) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO scrape_runs (
                started_at, finished_at, status, workflow, source_observed_at,
                source_date, source_sha256, is_complete, parsed_game_count,
                parsed_prize_tier_count, pipeline_version
            ) VALUES (
                :observed, :observed, :status, 'unpaid_prizes', :observed,
                (:observed AT TIME ZONE 'America/Chicago')::date,
                :sha, :complete, :games, :tiers, 'test'
            ) RETURNING id
            """
        ),
        {
            "observed": observed_at,
            "status": "success" if complete else "quarantined",
            "sha": suffix * 64,
            "complete": complete,
            "games": 1,
            "tiers": 1,
        },
    ).scalar_one()


def _snapshot(connection, run_id: int, game_id: int, observed_at: datetime) -> int:
    snapshot_id = connection.execute(
        text(
            "INSERT INTO game_snapshots (game_id, scrape_run_id, captured_at) "
            "VALUES (:game, :run, :observed) RETURNING id"
        ),
        {"game": game_id, "run": run_id, "observed": observed_at},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO prize_tier_snapshots "
            "(game_snapshot_id, prize_amount, original_count, remaining_count, claimed_count) "
            "VALUES (:snapshot, 10, 100, 90, 10)"
        ),
        {"snapshot": snapshot_id},
    )
    return snapshot_id


def test_quarantined_newer_run_never_replaces_complete_current(connection):
    observed = datetime.now(UTC) + timedelta(days=1)
    game_id = _game(connection, "current-view-1")
    complete_run = _run(connection, observed, "a")
    _snapshot(connection, complete_run, game_id, observed)
    _run(connection, observed + timedelta(hours=1), "b", complete=False)

    assert connection.execute(
        text("SELECT id FROM current_complete_scrape_run_v")
    ).scalar_one() == complete_run
    assert connection.execute(
        text("SELECT count(*) FROM current_game_snapshots_v")
    ).scalar_one() == 1


def test_legitimate_complete_run_changes_current_membership(connection):
    observed = datetime.now(UTC) + timedelta(days=1)
    old_game = _game(connection, "current-view-old")
    new_game = _game(connection, "current-view-new")
    old_run = _run(connection, observed, "c")
    _snapshot(connection, old_run, old_game, observed)
    new_run = _run(connection, observed + timedelta(hours=1), "d")
    _snapshot(connection, new_run, new_game, observed + timedelta(hours=1))

    assert connection.execute(
        text("SELECT scrape_run_id FROM current_game_snapshots_v")
    ).scalar_one() == new_run
    assert connection.execute(
        text("SELECT game_id FROM current_game_snapshots_v")
    ).scalar_one() == new_game


def test_catalog_and_source_reconciliation_views_expose_each_membership(connection):
    observed = datetime.now(UTC) + timedelta(days=1)
    both = _game(connection, "reconcile-both")
    source_only = _game(connection, "reconcile-source")
    catalog_only = _game(connection, "reconcile-catalog")
    source_run = _run(connection, observed, "e")
    _snapshot(connection, source_run, both, observed)
    _snapshot(connection, source_run, source_only, observed)
    catalog_run = connection.execute(
        text(
            """
            INSERT INTO scrape_runs (
                started_at, finished_at, status, workflow, source_observed_at,
                source_date, source_sha256, is_complete, parsed_game_count,
                parsed_prize_tier_count, pipeline_version
            ) VALUES (
                :observed, :observed, 'success', 'instant_ticket_catalog', :observed,
                (:observed AT TIME ZONE 'America/Chicago')::date,
                :sha, true, 2, 0, 'catalog-test'
            ) RETURNING id
            """
        ),
        {"observed": observed, "sha": "f" * 64},
    ).scalar_one()
    for position, game_id in enumerate((both, catalog_only)):
        connection.execute(
            text(
                """
                INSERT INTO game_catalog_snapshots (
                    scrape_run_id, game_id, detail_url, display_name,
                    ticket_price, page_number, card_position
                ) VALUES (:run, :game, :url, :name, 5, 1, :position)
                """
            ),
            {
                "run": catalog_run,
                "game": game_id,
                "url": f"https://example.test/{game_id}",
                "name": f"GAME {game_id}",
                "position": position,
            },
        )

    rows = {
        row.game_id: (row.prize_source_current, row.catalog_current, row.recommendation_current)
        for row in connection.execute(
            text(
                "SELECT game_id, prize_source_current, catalog_current, "
                "recommendation_current FROM current_game_source_reconciliation_v "
                "WHERE game_id IN (:both, :source, :catalog)"
            ),
            {"both": both, "source": source_only, "catalog": catalog_only},
        )
    }
    assert rows[both] == (True, True, True)
    assert rows[source_only] == (True, False, False)
    assert rows[catalog_only] == (False, True, False)
    assert connection.execute(
        text("SELECT id FROM recommendation_current_games_v")
    ).scalar_one() == both
