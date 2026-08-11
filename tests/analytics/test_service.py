from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_VERSION,
    model_parameters_sha256,
)
from illinois_lottery_tracker.analytics.service import compute_analytics
from illinois_lottery_tracker.analytics_models import (
    AnalyticsGameMetric,
    AnalyticsModelVersion,
    AnalyticsRun,
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


def test_service_applies_fixed_adjustment_and_keeps_raw_fallbacks_available():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        _seed_model(session)
        first_at = datetime(2026, 7, 11, 12, tzinfo=UTC)
        current_at = first_at + timedelta(days=30)
        historical_run = _seed_run(session, first_at, "a", games=1)
        current_run = _seed_run(session, current_at, "b", games=2)
        history_game = _seed_game(session, "history", Decimal("4"))
        missing_odds_game = _seed_game(session, "missing-odds", None)
        _snapshot(session, historical_run, history_game, ordinary_remaining=10_000)
        _snapshot(session, current_run, history_game, ordinary_remaining=8_000)
        _snapshot(session, current_run, missing_odds_game, ordinary_remaining=8_000)

        first = compute_analytics(session, scrape_run_id=current_run.id)
        second = compute_analytics(session, scrape_run_id=current_run.id)

        assert first.game_count == 2
        assert first.tier_count == 8
        assert first.regular_scored_count == 2
        assert first.high_tier_count == 4
        assert first.high_adjusted_count == 1
        assert first.high_reported_only_count == 3
        assert second.reused_successful_run
        assert second.analytics_run_id == first.analytics_run_id
        assert session.scalar(select(func.count()).select_from(AnalyticsRun)) == 1
        assert session.scalar(select(func.count()).select_from(AnalyticsGameMetric)) == 2
        assert session.scalar(select(func.count()).select_from(AnalyticsTierMetric)) == 8
        assert session.scalar(select(func.count()).select_from(AnalyticsStrategyMetric)) == 2

        adjusted = session.scalar(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == first.analytics_run_id,
                AnalyticsTierMetric.game_id == history_game.id,
                AnalyticsTierMetric.adjustment_status == "applied",
            )
        )
        assert adjusted is not None
        assert adjusted.reported_remaining_count == 100
        assert adjusted.estimated_pending_count == Decimal("24.000000")
        assert adjusted.adjusted_remaining_count == Decimal("76.000000")
        assert adjusted.lag_days_used == 24
        assert adjusted.status == "available"

        small_top = session.scalar(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == first.analytics_run_id,
                AnalyticsTierMetric.game_id == history_game.id,
                AnalyticsTierMetric.is_top_prize.is_(True),
            )
        )
        assert small_top is not None
        assert small_top.adjustment_status == "reported_only"
        assert small_top.adjusted_remaining_count == 4
        assert small_top.status == "available"

        missing_reference = session.scalars(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == first.analytics_run_id,
                AnalyticsTierMetric.game_id == missing_odds_game.id,
                AnalyticsTierMetric.process_group == "high",
            )
        ).all()
        eligible = next(metric for metric in missing_reference if metric.adjustment_eligible)
        assert eligible.adjustment_status == "reference_unavailable"
        assert eligible.adjusted_remaining_count == eligible.reported_remaining_count
        assert eligible.availability_index is not None
        assert eligible.current_probability is None


def _seed_model(session: Session) -> None:
    session.add(
        AnalyticsModelVersion(
            model_name=MODEL_NAME,
            semantic_version=MODEL_VERSION,
            parameters=MODEL_PARAMETERS,
            parameters_sha256=model_parameters_sha256(),
            code_version="test",
        )
    )
    session.flush()


def _seed_run(
    session: Session, observed: datetime, sha_char: str, *, games: int
) -> ScrapeRun:
    run = ScrapeRun(
        started_at=observed,
        finished_at=observed,
        status="success",
        workflow="unpaid_prizes",
        source_observed_at=observed,
        source_date=observed.date(),
        source_sha256=sha_char * 64,
        is_complete=True,
        parsed_game_count=games,
        parsed_prize_tier_count=games * 4,
        pipeline_version="test",
    )
    session.add(run)
    session.flush()
    return run


def _seed_game(session: Session, number: str, odds: Decimal | None) -> Game:
    game = Game(
        game_number=number,
        name=number.upper(),
        ticket_price=Decimal("5"),
        overall_odds_one_in=odds,
    )
    session.add(game)
    session.flush()
    return game


def _snapshot(
    session: Session,
    run: ScrapeRun,
    game: Game,
    *,
    ordinary_remaining: int,
) -> None:
    snapshot = GameSnapshot(
        game_id=game.id,
        scrape_run_id=run.id,
        captured_at=run.source_observed_at,
        structure_fingerprint=(f"{game.id:x}" * 64)[:64],
    )
    session.add(snapshot)
    session.flush()
    for amount, original, remaining in (
        ("5", 20_000, ordinary_remaining),
        ("600", 20_000, ordinary_remaining),
        ("1000", 300, 100),
        ("100000", 5, 4),
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
