"""Canonical complete-run, current-game, and freshness lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Select, select, text, update
from sqlalchemy.orm import Session

from .models import Game, GameSnapshot, ScrapeRun


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE_WARNING = "stale_warning"
    STALE_ERROR = "stale_error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SourceFreshness:
    state: FreshnessState
    age_hours: float | None
    observed_at: datetime | None


def complete_unpaid_runs_query() -> Select[tuple[ScrapeRun]]:
    return (
        select(ScrapeRun)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
        )
        .order_by(ScrapeRun.source_observed_at, ScrapeRun.id)
    )


def current_complete_run_id(session: Session) -> int | None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        return session.execute(
            text("SELECT id FROM current_complete_scrape_run_v")
        ).scalar_one_or_none()
    return session.scalar(
        select(ScrapeRun.id)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
        )
        .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )


def current_or_legacy_fixture_run_id(session: Session) -> int | None:
    current = current_complete_run_id(session)
    if current is not None or session.bind is None or session.bind.dialect.name != "sqlite":
        return current
    # Unit-test compatibility only. PostgreSQL never falls back to mixed runs.
    return session.scalar(
        select(ScrapeRun.id)
        .join(GameSnapshot, GameSnapshot.scrape_run_id == ScrapeRun.id)
        .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )


def synchronize_active_games(session: Session, scrape_run_id: int) -> None:
    current_game_ids = select(GameSnapshot.game_id).where(
        GameSnapshot.scrape_run_id == scrape_run_id
    )
    session.execute(update(Game).values(is_active=False))
    session.execute(
        update(Game).where(Game.id.in_(current_game_ids)).values(is_active=True)
    )


def source_freshness(
    observed_at: datetime | None,
    *,
    now: datetime | None = None,
    fresh_hours: float = 36,
    stale_error_hours: float = 72,
) -> SourceFreshness:
    if observed_at is None:
        return SourceFreshness(FreshnessState.UNAVAILABLE, None, None)
    now = now or datetime.now(UTC)
    if now.tzinfo is None or observed_at.tzinfo is None:
        raise ValueError("freshness timestamps must be timezone-aware")
    age_hours = max(0.0, (now - observed_at).total_seconds() / 3600)
    if age_hours <= fresh_hours:
        state = FreshnessState.FRESH
    elif age_hours <= stale_error_hours:
        state = FreshnessState.STALE_WARNING
    else:
        state = FreshnessState.STALE_ERROR
    return SourceFreshness(state, age_hours, observed_at)
