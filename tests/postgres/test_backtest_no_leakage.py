"""PostgreSQL walk-forward persistence, idempotence, and leakage guards."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.backtest import run_walk_forward_backtest
from illinois_lottery_tracker.analytics_models import (
    AnalyticsBacktestPrediction,
    AnalyticsModelVersion,
)
from illinois_lottery_tracker.models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun


def test_walk_forward_freezes_cutoff_inputs_and_is_idempotent():
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
            game_number="backtest-no-lookahead",
            name="BACKTEST NO LOOKAHEAD",
            ticket_price=Decimal("5"),
            overall_odds_one_in=Decimal("4"),
        )
        session.add(game)
        session.flush()
        start = datetime(2025, 1, 1, 12, tzinfo=UTC)
        for day in range(48):
            observed = start + timedelta(days=day)
            run = ScrapeRun(
                started_at=observed,
                finished_at=observed,
                status="success",
                workflow="unpaid_prizes",
                source_observed_at=observed,
                source_date=observed.date(),
                source_sha256=f"{day + 5000:064x}",
                is_complete=True,
                parsed_game_count=1,
                parsed_prize_tier_count=4,
                pipeline_version="backtest-test",
            )
            session.add(run)
            session.flush()
            snapshot = GameSnapshot(
                game_id=game.id,
                scrape_run_id=run.id,
                captured_at=observed,
                structure_fingerprint="b" * 64,
            )
            session.add(snapshot)
            session.flush()
            low_remaining = 20_000 - day * 200
            for amount, original, remaining in (
                ("5", 20_000, low_remaining),
                ("500", 20_000, low_remaining - 100),
                ("600", 2_000, 2_000 - day * 20),
                ("1000", 500, 500 - max(day - 5, 0) * 5),
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
        session.flush()

        cutoff_start = start + timedelta(days=30)
        cutoff_end = start + timedelta(days=47)
        first = run_walk_forward_backtest(
            session, cutoff_start=cutoff_start, cutoff_end=cutoff_end
        )
        second = run_walk_forward_backtest(
            session, cutoff_start=cutoff_start, cutoff_end=cutoff_end
        )
        rows = list(
            session.scalars(
                select(AnalyticsBacktestPrediction).where(
                    AnalyticsBacktestPrediction.backtest_run_id
                    == first.backtest_run_id
                )
            ).all()
        )

        assert first.reused is False
        assert second.reused is True
        assert second.backtest_run_id == first.backtest_run_id
        assert first.promotion_status == "failed"
        model = session.scalar(select(AnalyticsModelVersion))
        assert model is not None
        assert model.approval_status == "rejected"
        assert model.approval_backtest_run_id == first.backtest_run_id
        assert first.prediction_count == len(rows) > 0
        assert first.eligible_prediction_count > 0
        assert any(row.eligibility_code == "TARGET_DATE_MISSING" for row in rows)
        for row in rows:
            cutoff_run = session.get(ScrapeRun, row.cutoff_scrape_run_id)
            assert cutoff_run is not None
            assert (
                datetime.fromisoformat(row.cutoff_inputs["cutoff_observed_at"])
                == cutoff_run.source_observed_at
            )
    transaction.rollback()
    connection.close()
    engine.dispose()
