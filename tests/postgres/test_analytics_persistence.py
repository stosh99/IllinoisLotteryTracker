"""Idempotence, exact numerics, and current-cutoff tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    acquire_analytics_run,
    add_quality_issue_once,
    mark_analytics_run_failed,
    mark_analytics_run_success,
)
from illinois_lottery_tracker.analytics_models import AnalyticsRun, AnalyticsTierMetric
from illinois_lottery_tracker.models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun


@pytest.fixture
def session():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection, expire_on_commit=False) as database_session:
        yield database_session
    transaction.rollback()
    connection.close()
    engine.dispose()


def test_run_and_issue_persistence_are_idempotent(session: Session):
    source = _source_run(session, "b", hour=11)
    first = acquire_analytics_run(session, as_of_scrape_run_id=source.id)
    second = acquire_analytics_run(session, as_of_scrape_run_id=source.id)
    issue1, created1 = add_quality_issue_once(
        session,
        analytics_run_id=first.run.id,
        code="TEST_ISSUE",
        severity="info",
        entity_type="run",
        message="test",
    )
    issue2, created2 = add_quality_issue_once(
        session,
        analytics_run_id=first.run.id,
        code="TEST_ISSUE",
        severity="info",
        entity_type="run",
        message="duplicate",
    )
    assert first.created and not second.created
    assert issue1.id == issue2.id and created1 and not created2
    assert session.scalar(select(func.count()).select_from(AnalyticsRun)) >= 1


def test_exact_adjustment_round_trip_and_successful_run_immutability(session: Session):
    source = _source_run(session, "c", hour=12)
    game = Game(game_number="analytics-decimal", name="DECIMAL", ticket_price=5)
    session.add(game)
    session.flush()
    snapshot = GameSnapshot(
        game_id=game.id,
        scrape_run_id=source.id,
        captured_at=source.source_observed_at,
        structure_fingerprint="d" * 64,
    )
    session.add(snapshot)
    session.flush()
    tier = PrizeTierSnapshot(
        game_snapshot_id=snapshot.id,
        prize_amount=Decimal("1000"),
        original_count=300,
        remaining_count=100,
        claimed_count=200,
    )
    session.add(tier)
    session.flush()
    run = acquire_analytics_run(session, as_of_scrape_run_id=source.id).run
    metric = AnalyticsTierMetric(
        analytics_run_id=run.id,
        game_id=game.id,
        game_snapshot_id=snapshot.id,
        prize_tier_snapshot_id=tier.id,
        is_top_prize=True,
        process_group="high",
        reference_method="current_baseline",
        adjustment_eligible=True,
        adjustment_status="applied",
        lag_days_used=24,
        reported_remaining_count=100,
        estimated_pending_count=Decimal("24.123456"),
        adjusted_remaining_count=Decimal("75.876544"),
        availability_index=Decimal("1.234567890123"),
        status="available",
    )
    session.add(metric)
    session.flush()
    metric_id = metric.id
    mark_analytics_run_success(session, run)
    session.expire_all()
    stored = session.get(AnalyticsTierMetric, metric_id)
    assert stored is not None
    assert stored.estimated_pending_count == Decimal("24.123456")
    assert stored.adjusted_remaining_count == Decimal("75.876544")
    nested = session.begin_nested()
    with pytest.raises(DBAPIError, match="immutable"):
        session.execute(
            text("UPDATE analytics_runs SET error_message='changed' WHERE id=:id"),
            {"id": run.id},
        )
    nested.rollback()


def test_current_view_requires_current_source_success(session: Session):
    old_source = _source_run(session, "e", hour=13)
    old_run = acquire_analytics_run(session, as_of_scrape_run_id=old_source.id).run
    mark_analytics_run_success(session, old_run)
    current_source = _source_run(session, "f", hour=14)
    assert session.execute(text("SELECT count(*) FROM current_analytics_run_v")).scalar_one() == 0
    current_run = acquire_analytics_run(session, as_of_scrape_run_id=current_source.id).run
    mark_analytics_run_failed(session, current_run, error_message="synthetic failure")
    assert session.execute(text("SELECT count(*) FROM current_analytics_run_v")).scalar_one() == 0
    retry = acquire_analytics_run(session, as_of_scrape_run_id=current_source.id)
    assert retry.retrying_failed
    mark_analytics_run_success(session, retry.run)
    assert session.execute(
        text("SELECT id FROM current_analytics_run_v")
    ).scalar_one() == retry.run.id


def _source_run(session: Session, sha_character: str, *, hour: int) -> ScrapeRun:
    observed = datetime.now(UTC) + timedelta(days=1, minutes=hour)
    run = ScrapeRun(
        started_at=observed,
        finished_at=observed,
        status="success",
        workflow="unpaid_prizes",
        source_observed_at=observed,
        source_date=observed.astimezone(ZoneInfo("America/Chicago")).date(),
        source_sha256=sha_character * 64,
        is_complete=True,
        parsed_game_count=1,
        parsed_prize_tier_count=1,
        pipeline_version="test",
    )
    session.add(run)
    session.flush()
    return run
