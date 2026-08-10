from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_VERSION,
    model_parameters_sha256,
)
from illinois_lottery_tracker.analytics.service import compute_regular_analytics
from illinois_lottery_tracker.analytics_models import (
    AnalyticsGameMetric,
    AnalyticsModelVersion,
    AnalyticsRun,
    AnalyticsTierMetric,
)
from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    PrizeTierSnapshot,
    ScrapeRun,
)


def test_regular_service_persists_every_tier_and_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        _seed_model(session)
        source = _seed_cutoff(session)
        _seed_game(session, source, "regular", odds=Decimal("4"))
        _seed_game(session, source, "missing-odds", odds=None)

        first = compute_regular_analytics(session, scrape_run_id=source.id)
        second = compute_regular_analytics(session, scrape_run_id=source.id)

        assert first.game_count == 2
        assert first.tier_count == 8
        assert first.regular_scored_count == 6
        assert first.high_pending_count == 2
        assert first.publishable is False
        assert second.reused_successful_run is True
        assert second.analytics_run_id == first.analytics_run_id
        assert session.scalar(select(func.count()).select_from(AnalyticsRun)) == 1
        assert session.scalar(select(func.count()).select_from(AnalyticsGameMetric)) == 2
        assert session.scalar(select(func.count()).select_from(AnalyticsTierMetric)) == 8

        methods = session.execute(
            select(AnalyticsTierMetric.process_group, AnalyticsTierMetric.reference_method)
            .where(AnalyticsTierMetric.analytics_run_id == first.analytics_run_id)
            .distinct()
        ).all()
        assert ("baseline", "leave_one_tier_out") in methods
        assert ("retail_gap", "current_baseline") in methods
        assert ("high", "unavailable") in methods

        missing = session.scalar(
            select(AnalyticsGameMetric)
            .join(Game, Game.id == AnalyticsGameMetric.game_id)
            .where(Game.game_number == "missing-odds")
        )
        assert missing is not None
        assert missing.data_status == "partial"
        missing_tiers = session.scalars(
            select(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == first.analytics_run_id,
                AnalyticsTierMetric.game_id == missing.game_id,
                AnalyticsTierMetric.process_group != "high",
            )
        ).all()
        assert all(tier.availability_index is not None for tier in missing_tiers)
        assert all(tier.current_probability is None for tier in missing_tiers)
        assert all(tier.exclusion_reason == "MISSING_OVERALL_ODDS" for tier in missing_tiers)


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


def _seed_cutoff(session: Session) -> ScrapeRun:
    observed = datetime(2026, 8, 8, 12, tzinfo=UTC)
    run = ScrapeRun(
        started_at=observed,
        finished_at=observed,
        status="success",
        workflow="unpaid_prizes",
        source_observed_at=observed,
        source_date=observed.date(),
        source_sha256="a" * 64,
        is_complete=True,
        parsed_game_count=2,
        parsed_prize_tier_count=8,
        pipeline_version="test",
    )
    session.add(run)
    session.flush()
    return run


def _seed_game(
    session: Session,
    source: ScrapeRun,
    number: str,
    *,
    odds: Decimal | None,
) -> None:
    game = Game(
        game_number=number,
        name=number.upper(),
        ticket_price=Decimal("5"),
        overall_odds_one_in=odds,
    )
    session.add(game)
    session.flush()
    snapshot = GameSnapshot(
        game_id=game.id,
        scrape_run_id=source.id,
        captured_at=source.source_observed_at,
        structure_fingerprint=("b" if odds else "c") * 64,
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
