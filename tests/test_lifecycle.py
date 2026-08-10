"""Tests for complete-source decisions, lifecycle synchronization, and freshness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.lifecycle import (
    FreshnessState,
    source_freshness,
    synchronize_active_games,
)
from illinois_lottery_tracker.models import Base, Game, GameSnapshot, ScrapeRun
from illinois_lottery_tracker.source_quality import (
    SourceQualityReport,
    evaluate_source_completeness,
)


def test_completeness_accepts_exactly_eighty_percent_of_prior():
    report = SourceQualityReport(parsed_game_count=48, parsed_prize_tier_count=640)
    decision = evaluate_source_completeness(
        report,
        prior_game_count=60,
        prior_prize_tier_count=800,
    )
    assert decision.is_complete


def test_completeness_rejects_below_eighty_percent_of_prior():
    report = SourceQualityReport(parsed_game_count=47, parsed_prize_tier_count=639)
    decision = evaluate_source_completeness(
        report,
        prior_game_count=60,
        prior_prize_tier_count=800,
    )
    assert not decision.is_complete
    assert decision.reasons == ("RELATIVE_GAME_COUNT", "RELATIVE_PRIZE_TIER_COUNT")


def test_manual_approval_overrides_relative_but_not_absolute_gate():
    relative = SourceQualityReport(parsed_game_count=40, parsed_prize_tier_count=400)
    assert evaluate_source_completeness(
        relative,
        prior_game_count=60,
        prior_prize_tier_count=800,
        manually_approved=True,
    ).is_complete

    absolute = SourceQualityReport(parsed_game_count=39, parsed_prize_tier_count=400)
    decision = evaluate_source_completeness(
        absolute,
        prior_game_count=60,
        prior_prize_tier_count=800,
        manually_approved=True,
    )
    assert not decision.is_complete
    assert decision.reasons == ("ABSOLUTE_GAME_COUNT",)


def test_freshness_boundaries_are_inclusive():
    now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    assert source_freshness(now - timedelta(hours=36), now=now).state == FreshnessState.FRESH
    assert (
        source_freshness(now - timedelta(hours=36, seconds=1), now=now).state
        == FreshnessState.STALE_WARNING
    )
    assert (
        source_freshness(now - timedelta(hours=72), now=now).state
        == FreshnessState.STALE_WARNING
    )
    assert (
        source_freshness(now - timedelta(hours=72, seconds=1), now=now).state
        == FreshnessState.STALE_ERROR
    )


def test_active_compatibility_cache_tracks_one_complete_run():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = ScrapeRun(started_at=datetime.now(UTC), status="running")
        current = Game(game_number="1", name="CURRENT", is_active=False)
        absent = Game(game_number="2", name="ABSENT", is_active=True)
        session.add_all([run, current, absent])
        session.flush()
        session.add(
            GameSnapshot(
                game=current,
                scrape_run=run,
                captured_at=datetime.now(UTC),
            )
        )
        session.flush()

        synchronize_active_games(session, run.id)
        session.flush()

        states = dict(session.execute(select(Game.game_number, Game.is_active)).all())
        assert states == {"1": True, "2": False}
