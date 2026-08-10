from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_VERSION,
    model_parameters_sha256,
)
from illinois_lottery_tracker.analytics.service import (
    calibrate_claim_lag,
    compute_regular_analytics,
    finalize_high_tier_analytics,
)
from illinois_lottery_tracker.analytics_models import (
    AnalyticsModelVersion,
    AnalyticsStrategyMetric,
    AnalyticsTierMetric,
)
from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    PrizeTierSnapshot,
    ScrapeRun,
)


def test_high_service_scores_top_but_leaves_new_game_partial():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            AnalyticsModelVersion(
                model_name=MODEL_NAME,
                semantic_version=MODEL_VERSION,
                parameters=MODEL_PARAMETERS,
                parameters_sha256=model_parameters_sha256(),
                code_version="test",
                approval_status="approved",
                approval_backtest_run_id=1,
                approval_decided_at=datetime(2026, 1, 1, tzinfo=UTC),
                approval_reason="unit-test passed promotion fixture",
            )
        )
        games = [
            Game(
                game_number=f"lag-{index}",
                name=f"LAG {index}",
                ticket_price=Decimal("5"),
                overall_odds_one_in=Decimal("4"),
            )
            for index in range(9)
        ]
        new_game = Game(
            game_number="new-game",
            name="NEW GAME",
            ticket_price=Decimal("5"),
            overall_odds_one_in=Decimal("4"),
        )
        session.add_all([*games, new_game])
        session.flush()
        start = datetime(2026, 1, 1, 12, tzinfo=UTC)
        runs = []
        for day in range(40):
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
                parsed_game_count=10 if day == 39 else 9,
                parsed_prize_tier_count=40 if day == 39 else 36,
                pipeline_version="test",
            )
            session.add(run)
            session.flush()
            for game in games:
                _snapshot(
                    session,
                    run,
                    game,
                    day,
                    fingerprint_override=("f" * 64 if game is games[0] and day == 0 else None),
                )
            if day == 39:
                _snapshot(session, run, new_game, day)
            runs.append(run)
        session.flush()
        compute = compute_regular_analytics(session, scrape_run_id=runs[-1].id)
        calibration = calibrate_claim_lag(session, scrape_run_id=runs[-1].id)
        final = finalize_high_tier_analytics(session, scrape_run_id=runs[-1].id)

        assert calibration.status == "available"
        assert calibration.primary_qualified_game_count == 8
        assert abs(calibration.median_lag_days - Decimal("5")) < Decimal("0.000001")
        assert final.analytics_run_id == compute.analytics_run_id
        assert final.high_tier_count == 20
        assert final.high_scored_count == 16
        assert final.high_unavailable_count == 4
        assert final.strategy_count == 10
        assert final.publishable is True

        top = session.scalar(
            select(AnalyticsTierMetric)
            .where(
                AnalyticsTierMetric.analytics_run_id == final.analytics_run_id,
                AnalyticsTierMetric.game_id == games[0].id,
                AnalyticsTierMetric.is_top_prize.is_(True),
            )
        )
        assert top is not None
        assert top.status == "unavailable"
        assert top.exclusion_reason == "STRUCTURE_CHANGED"
        assert top.reference_method == "unavailable"

        new_high = session.scalars(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == final.analytics_run_id,
                AnalyticsTierMetric.game_id == new_game.id,
                AnalyticsTierMetric.process_group == "high",
            )
        ).all()
        assert all(metric.status == "unavailable" for metric in new_high)
        assert all(metric.exclusion_reason == "LAG_REFERENCE_NOT_AVAILABLE" for metric in new_high)
        new_strategy = session.scalar(
            select(AnalyticsStrategyMetric).where(
                AnalyticsStrategyMetric.analytics_run_id == final.analytics_run_id,
                AnalyticsStrategyMetric.game_id == new_game.id,
            )
        )
        assert new_strategy is not None
        assert new_strategy.metric_statuses["value_full"] == "partial"


def test_insufficient_lag_history_publishes_explicit_unavailable_high_tiers():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            AnalyticsModelVersion(
                model_name=MODEL_NAME,
                semantic_version=MODEL_VERSION,
                parameters=MODEL_PARAMETERS,
                parameters_sha256=model_parameters_sha256(),
                code_version="test",
                approval_status="approved",
                approval_backtest_run_id=1,
                approval_decided_at=datetime(2026, 1, 1, tzinfo=UTC),
                approval_reason="unit-test passed promotion fixture",
            )
        )
        game = Game(
            game_number="early-history",
            name="EARLY HISTORY",
            ticket_price=Decimal("5"),
            overall_odds_one_in=Decimal("4"),
        )
        observed = datetime(2026, 1, 1, 12, tzinfo=UTC)
        run = ScrapeRun(
            started_at=observed,
            finished_at=observed,
            status="success",
            workflow="unpaid_prizes",
            source_observed_at=observed,
            source_date=observed.date(),
            source_sha256="f" * 64,
            is_complete=True,
            parsed_game_count=1,
            parsed_prize_tier_count=4,
            pipeline_version="test",
        )
        session.add_all([game, run])
        session.flush()
        _snapshot(session, run, game, 0)
        session.flush()

        compute_regular_analytics(session, scrape_run_id=run.id)
        calibration = calibrate_claim_lag(session, scrape_run_id=run.id)
        final = finalize_high_tier_analytics(session, scrape_run_id=run.id)

        high = session.scalars(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == final.analytics_run_id,
                AnalyticsTierMetric.process_group == "high",
            )
        ).all()
        assert calibration.status == "insufficient"
        assert final.publishable is False
        assert final.high_scored_count == 0
        assert final.high_unavailable_count == 2
        assert all(metric.status == "unavailable" for metric in high)
        assert all(metric.exclusion_reason == "LAG_NOT_AVAILABLE" for metric in high)


def _snapshot(
    session: Session,
    run: ScrapeRun,
    game: Game,
    day: int,
    *,
    fingerprint_override: str | None = None,
) -> None:
    snapshot = GameSnapshot(
        game_id=game.id,
        scrape_run_id=run.id,
        captured_at=run.source_observed_at,
        structure_fingerprint=fingerprint_override or (f"{game.id:x}" * 64)[:64],
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
