"""Cutoff-strict database reads for analytics jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ..models import GameSnapshot, ScrapeRun
from .high_prize_adjustment import ORDINARY_PRIZE_MAX, ProgressPoint


@dataclass(frozen=True)
class GameMembership:
    prize_source_current: bool
    catalog_current: bool
    recommendation_current: bool


def resolve_source_cutoff(
    session: Session,
    *,
    scrape_run_id: int | None = None,
    source_date: date | None = None,
) -> ScrapeRun:
    if scrape_run_id is not None:
        run = session.get(ScrapeRun, scrape_run_id)
    elif source_date is not None:
        run = session.scalar(
            select(ScrapeRun)
            .where(
                ScrapeRun.workflow == "unpaid_prizes",
                ScrapeRun.status == "success",
                ScrapeRun.is_complete.is_(True),
                ScrapeRun.source_date == source_date,
            )
            .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        )
    elif session.bind is not None and session.bind.dialect.name == "postgresql":
        current_id = session.execute(
            text("SELECT id FROM current_complete_scrape_run_v")
        ).scalar_one_or_none()
        run = session.get(ScrapeRun, current_id) if current_id is not None else None
    else:
        run = session.scalar(
            select(ScrapeRun)
            .where(
                ScrapeRun.workflow == "unpaid_prizes",
                ScrapeRun.status == "success",
                ScrapeRun.is_complete.is_(True),
            )
            .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        )
    if (
        run is None
        or run.workflow != "unpaid_prizes"
        or run.status != "success"
        or not run.is_complete
        or run.source_observed_at is None
    ):
        raise LookupError("no matching complete successful unpaid-prizes cutoff")
    return run


def load_cutoff_game_snapshots(
    session: Session, cutoff: ScrapeRun
) -> list[GameSnapshot]:
    return list(
        session.scalars(
            select(GameSnapshot)
            .where(GameSnapshot.scrape_run_id == cutoff.id)
            .options(
                selectinload(GameSnapshot.game),
                selectinload(GameSnapshot.prize_tiers),
            )
            .order_by(GameSnapshot.game_id)
        ).all()
    )


def load_current_memberships(session: Session) -> dict[int, GameMembership]:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return {}
    rows = session.execute(
        text(
            "SELECT game_id, prize_source_current, catalog_current, "
            "recommendation_current FROM current_game_source_reconciliation_v"
        )
    ).mappings()
    return {
        row["game_id"]: GameMembership(
            prize_source_current=row["prize_source_current"],
            catalog_current=row["catalog_current"],
            recommendation_current=row["recommendation_current"],
        )
        for row in rows
    }


def current_catalog_observed_at(session: Session):
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return None
    return session.execute(
        text("SELECT source_observed_at FROM current_complete_catalog_run_v")
    ).scalar_one_or_none()


def load_game_progress_curve(
    session: Session, *, game_id: int, cutoff: ScrapeRun
) -> list[ProgressPoint]:
    """Load the ordinary-tier progress curve without observations after cutoff."""
    snapshots = session.scalars(
        select(GameSnapshot)
        .join(ScrapeRun, ScrapeRun.id == GameSnapshot.scrape_run_id)
        .where(
            GameSnapshot.game_id == game_id,
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_observed_at <= cutoff.source_observed_at,
        )
        .options(
            selectinload(GameSnapshot.prize_tiers),
            selectinload(GameSnapshot.scrape_run),
        )
        .order_by(ScrapeRun.source_observed_at, ScrapeRun.id)
    ).all()
    curve: list[ProgressPoint] = []
    for snapshot in snapshots:
        baseline = [
            tier
            for tier in snapshot.prize_tiers
            if tier.prize_amount <= ORDINARY_PRIZE_MAX
        ]
        original = sum(tier.original_count for tier in baseline)
        remaining = sum(tier.remaining_count for tier in baseline)
        if original > 0:
            curve.append(
                ProgressPoint(
                    observed_at=snapshot.scrape_run.source_observed_at,
                    progress_fraction=Decimal(1)
                    - Decimal(remaining) / Decimal(original),
                )
            )
    return curve
