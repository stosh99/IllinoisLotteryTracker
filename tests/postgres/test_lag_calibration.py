"""PostgreSQL no-look-ahead and calibration-audit integration test."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.queries import (
    load_lag_game_histories,
    resolve_source_cutoff,
)
from illinois_lottery_tracker.analytics.service import calibrate_claim_lag
from illinois_lottery_tracker.analytics_models import AnalyticsLagGameEstimate
from illinois_lottery_tracker.models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun


def test_lag_query_excludes_future_observation_and_persists_candidate_audit():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection, expire_on_commit=False) as session:
        game = Game(
            game_number="lag-no-lookahead",
            name="LAG NO LOOKAHEAD",
            ticket_price=Decimal("5"),
            overall_odds_one_in=Decimal("4"),
        )
        session.add(game)
        session.flush()
        start = datetime(2026, 1, 1, 12, tzinfo=UTC)
        runs: list[ScrapeRun] = []
        for day in range(32):
            observed = start + timedelta(days=day)
            run = ScrapeRun(
                started_at=observed,
                finished_at=observed,
                status="success",
                workflow="unpaid_prizes",
                source_observed_at=observed,
                source_date=observed.date(),
                source_sha256=f"{day + 1000:064x}",
                is_complete=True,
                parsed_game_count=1,
                parsed_prize_tier_count=4,
                pipeline_version="test",
            )
            session.add(run)
            session.flush()
            snapshot = GameSnapshot(
                game_id=game.id,
                scrape_run_id=run.id,
                captured_at=observed,
                structure_fingerprint="7" * 64,
            )
            session.add(snapshot)
            session.flush()
            low_remaining = 10_000 - day * 100
            high_remaining = 500 - max(day - 5, 0) * 5
            for amount, original, remaining in (
                ("5", 10_000, low_remaining),
                ("500", 10_000, low_remaining),
                ("700", 500, high_remaining),
                ("100000", 5, 5),
            ):
                session.add(
                    PrizeTierSnapshot(
                        game_snapshot_id=snapshot.id,
                        prize_amount=Decimal(amount),
                        original_count=original,
                        remaining_count=remaining,
                        claimed_count=original - remaining,
                    )
                )
            runs.append(run)
        session.flush()
        cutoff = resolve_source_cutoff(session, scrape_run_id=runs[30].id)
        histories = load_lag_game_histories(session, cutoff)

        assert len(histories) == 1
        assert len(histories[0].primary_observations) == 31
        assert histories[0].primary_observations[-1].observed_at == runs[30].source_observed_at
        assert all(
            observation.observed_at <= cutoff.source_observed_at
            for observation in histories[0].primary_observations
        )

        result = calibrate_claim_lag(session, scrape_run_id=cutoff.id)
        estimate = session.scalar(
            select(AnalyticsLagGameEstimate).where(
                AnalyticsLagGameEstimate.analytics_run_id == result.analytics_run_id,
                AnalyticsLagGameEstimate.game_id == game.id,
            )
        )
        assert result.primary_qualified_game_count == 1
        assert result.status == "insufficient"
        assert estimate is not None
        assert estimate.eligible_primary is True
        assert abs(estimate.median_lag_days - Decimal("5")) < Decimal("0.000001")
    transaction.rollback()
    connection.close()
    engine.dispose()
