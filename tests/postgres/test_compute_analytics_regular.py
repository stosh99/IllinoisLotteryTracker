"""PostgreSQL integration check for cutoff-scoped regular analytics."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.service import compute_analytics
from illinois_lottery_tracker.analytics_models import AnalyticsTierMetric
from illinois_lottery_tracker.models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun


def test_compute_regular_cutoff_persists_every_tier_with_exact_references():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection, expire_on_commit=False) as session:
        observed = datetime(2026, 8, 9, 12, tzinfo=UTC)
        source = ScrapeRun(
            started_at=observed,
            finished_at=observed,
            status="success",
            workflow="unpaid_prizes",
            source_observed_at=observed,
            source_date=observed.date(),
            source_sha256="9" * 64,
            is_complete=True,
            parsed_game_count=1,
            parsed_prize_tier_count=4,
            pipeline_version="test",
        )
        game = Game(
            game_number="analytics-pg-regular",
            name="ANALYTICS PG REGULAR",
            ticket_price=Decimal("5"),
            overall_odds_one_in=Decimal("4"),
        )
        session.add_all([source, game])
        session.flush()
        snapshot = GameSnapshot(
            game_id=game.id,
            scrape_run_id=source.id,
            captured_at=observed,
            structure_fingerprint="8" * 64,
        )
        session.add(snapshot)
        session.flush()
        for amount, original, remaining in (
            ("5", 20_000, 10_000),
            ("500", 20_000, 8_000),
            ("600", 1_000, 500),
            ("1000", 100, 50),
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

        result = compute_analytics(session, scrape_run_id=source.id)
        metrics = session.scalars(
            select(AnalyticsTierMetric)
            .where(AnalyticsTierMetric.analytics_run_id == result.analytics_run_id)
            .order_by(AnalyticsTierMetric.prize_tier_snapshot_id)
        ).all()

        assert result.game_count == 1
        assert result.tier_count == 4
        assert [metric.reference_method for metric in metrics] == [
            "leave_one_tier_out",
            "leave_one_tier_out",
            "leave_one_tier_out",
            "current_baseline",
        ]
        assert metrics[-1].adjustment_status == "reported_only"
        assert metrics[-1].status == "available"
        assert metrics[0].availability_index == Decimal("1.235294117647")
    transaction.rollback()
    connection.close()
    engine.dispose()
