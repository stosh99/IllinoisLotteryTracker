"""Idempotence, exact numerics, and publication-cutoff tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    acquire_analytics_run,
    add_quality_issue_once,
    approve_model_version,
    get_model_version,
    mark_analytics_run_failed,
    mark_analytics_run_success,
)
from illinois_lottery_tracker.analytics_models import (
    AnalyticsBacktestRun,
    AnalyticsRun,
    AnalyticsTierMetric,
)
from illinois_lottery_tracker.models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun


@pytest.fixture
def session():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection, expire_on_commit=False) as database_session:
        yield database_session
        database_session.close()
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
        message="ignored duplicate text",
    )

    assert first.created is True
    assert second.created is False
    assert first.run.id == second.run.id
    assert created1 is True and created2 is False
    assert issue1.id == issue2.id
    assert (
        session.scalar(
            select(func.count())
            .select_from(AnalyticsRun)
            .where(AnalyticsRun.as_of_scrape_run_id == source.id)
        )
        == 1
    )


def test_exact_decimal_round_trip_and_successful_run_immutability(session: Session):
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
        original_count=200,
        remaining_count=100,
        claimed_count=100,
    )
    session.add(tier)
    session.flush()
    acquisition = acquire_analytics_run(
        session,
        as_of_scrape_run_id=source.id,
        started_at=source.source_observed_at,
    )
    metric = AnalyticsTierMetric(
        analytics_run_id=acquisition.run.id,
        game_id=game.id,
        game_snapshot_id=snapshot.id,
        prize_tier_snapshot_id=tier.id,
        is_top_prize=False,
        process_group="high",
        reference_method="lagged_baseline",
        availability_index=Decimal("1.234567890123"),
        current_probability=Decimal("0.000062500000"),
        current_one_in=Decimal("16000.123456"),
        status="available",
    )
    session.add(metric)
    session.flush()
    metric_id = metric.id
    mark_analytics_run_success(
        session,
        acquisition.run,
        publishable=True,
        finished_at=datetime(2026, 8, 8, 12, 1, tzinfo=UTC),
    )
    session.expire_all()
    stored = session.get(AnalyticsTierMetric, metric_id)
    assert stored is not None
    assert stored.availability_index == Decimal("1.234567890123")
    assert stored.current_probability == Decimal("0.000062500000")
    assert stored.current_one_in == Decimal("16000.123456")
    assert acquire_analytics_run(session, as_of_scrape_run_id=source.id).run.id == (
        acquisition.run.id
    )
    nested = session.begin_nested()
    with pytest.raises(DBAPIError, match="immutable"):
        session.execute(
            text("UPDATE analytics_runs SET publishable=false WHERE id=:id"),
            {"id": acquisition.run.id},
        )
    nested.rollback()


def test_current_view_requires_current_source_publishable_success(session: Session):
    model = get_model_version(session)
    passed_backtest = AnalyticsBacktestRun(
        model_version_id=model.id,
        cutoff_start_at=None,
        cutoff_end_at=None,
        horizons=[7, 14, 30],
        parameters={"fixture": "current-view"},
        parameters_sha256="1" * 64,
        started_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        finished_at=datetime(2026, 8, 8, 12, 1, tzinfo=UTC),
        status="success",
        error_message=None,
        aggregate_results={},
        promotion_status="passed",
        promotion_report={"passed": True},
    )
    session.add(passed_backtest)
    session.flush()
    approve_model_version(
        session,
        reason="current-view integration fixture",
        backtest_run_id=passed_backtest.id,
        decided_at=datetime(2026, 8, 8, 12, 2, tzinfo=UTC),
    )
    old_source = _source_run(session, "e", hour=13)
    old_analytics = acquire_analytics_run(
        session,
        as_of_scrape_run_id=old_source.id,
        started_at=old_source.source_observed_at,
    )
    mark_analytics_run_success(
        session,
        old_analytics.run,
        publishable=True,
        finished_at=datetime(2026, 8, 8, 13, 1, tzinfo=UTC),
    )
    current_source = _source_run(session, "f", hour=14)
    assert session.execute(text("SELECT count(*) FROM current_analytics_run_v")).scalar_one() == 0

    current_analytics = acquire_analytics_run(
        session,
        as_of_scrape_run_id=current_source.id,
        started_at=current_source.source_observed_at,
    )
    assert session.execute(text("SELECT count(*) FROM current_analytics_run_v")).scalar_one() == 0
    mark_analytics_run_failed(
        session,
        current_analytics.run,
        error_message="synthetic failure",
        finished_at=datetime(2026, 8, 8, 14, 0, 30, tzinfo=UTC),
    )
    assert session.execute(text("SELECT count(*) FROM current_analytics_run_v")).scalar_one() == 0
    retry = acquire_analytics_run(
        session,
        as_of_scrape_run_id=current_source.id,
        started_at=datetime(2026, 8, 8, 14, 0, 31, tzinfo=UTC),
    )
    assert retry.retrying_failed is True
    mark_analytics_run_success(
        session,
        retry.run,
        publishable=True,
        finished_at=datetime(2026, 8, 8, 14, 1, tzinfo=UTC),
    )
    assert session.execute(text("SELECT id FROM current_analytics_run_v")).scalar_one() == (
        retry.run.id
    )


def _source_run(session: Session, sha_character: str, *, hour: int) -> ScrapeRun:
    observed = datetime(2026, 8, 8, hour, tzinfo=UTC)
    run = ScrapeRun(
        started_at=observed,
        finished_at=observed,
        status="success",
        workflow="unpaid_prizes",
        source_observed_at=observed,
        source_date=observed.date(),
        source_sha256=sha_character * 64,
        is_complete=True,
        parsed_game_count=1,
        parsed_prize_tier_count=1,
        pipeline_version="test",
    )
    session.add(run)
    session.flush()
    return run
