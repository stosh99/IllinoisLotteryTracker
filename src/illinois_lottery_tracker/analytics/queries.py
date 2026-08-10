"""Cutoff-strict database reads for analytics jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ..models import GameSnapshot, ScrapeRun
from .lag import (
    EXPLORATORY_ORIGINAL_TARGET,
    PRIMARY_ORIGINAL_TARGET,
    AdaptiveBand,
    ProgressObservation,
    select_adaptive_band,
)
from .types import TierInput


@dataclass(frozen=True)
class GameMembership:
    prize_source_current: bool
    catalog_current: bool
    recommendation_current: bool


@dataclass(frozen=True)
class LagGameHistory:
    game_id: int
    game_number: str
    top_prize_amount: Decimal
    primary_band: AdaptiveBand
    exploratory_band: AdaptiveBand
    primary_observations: tuple[ProgressObservation, ...]
    exploratory_observations: tuple[ProgressObservation, ...]
    prefit_exclusion_code: str | None


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


def load_lag_game_histories(
    session: Session, cutoff: ScrapeRun
) -> list[LagGameHistory]:
    """Load only observations available at the cutoff; never look ahead."""
    histories: list[LagGameHistory] = []
    for as_of in load_cutoff_game_snapshots(session, cutoff):
        tiers = [
            TierInput(
                prize_amount=tier.prize_amount,
                original_count=tier.original_count,
                remaining_count=tier.remaining_count,
                is_top_prize=tier.prize_amount
                == max(item.prize_amount for item in as_of.prize_tiers),
            )
            for tier in as_of.prize_tiers
        ]
        primary = select_adaptive_band(
            tiers, target_original_count=PRIMARY_ORIGINAL_TARGET
        )
        exploratory = select_adaptive_band(
            tiers, target_original_count=EXPLORATORY_ORIGINAL_TARGET
        )
        if not primary.eligible and not exploratory.eligible:
            histories.append(
                LagGameHistory(
                    game_id=as_of.game_id,
                    game_number=as_of.game.game_number,
                    top_prize_amount=primary.top_prize_amount,
                    primary_band=primary,
                    exploratory_band=exploratory,
                    primary_observations=(),
                    exploratory_observations=(),
                    prefit_exclusion_code=primary.exclusion_reason,
                )
            )
            continue
        snapshots = list(
            session.scalars(
                select(GameSnapshot)
                .join(ScrapeRun, ScrapeRun.id == GameSnapshot.scrape_run_id)
                .where(
                    GameSnapshot.game_id == as_of.game_id,
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
        )
        if any(
            snapshot.structure_fingerprint != as_of.structure_fingerprint
            for snapshot in snapshots
        ):
            histories.append(
                LagGameHistory(
                    game_id=as_of.game_id,
                    game_number=as_of.game.game_number,
                    top_prize_amount=primary.top_prize_amount,
                    primary_band=primary,
                    exploratory_band=exploratory,
                    primary_observations=(),
                    exploratory_observations=(),
                    prefit_exclusion_code="STRUCTURE_CHANGED",
                )
            )
            continue
        expected = {tier.prize_amount: tier.original_count for tier in tiers}
        primary_observations: list[ProgressObservation] = []
        exploratory_observations: list[ProgressObservation] = []
        invalid_structure = False
        for snapshot in snapshots:
            observed = {tier.prize_amount: tier for tier in snapshot.prize_tiers}
            if set(observed) != set(expected) or any(
                observed[amount].original_count != original
                for amount, original in expected.items()
            ):
                invalid_structure = True
                break
            low_original = sum(
                tier.original_count
                for amount, tier in observed.items()
                if amount <= 500
            )
            low_remaining = sum(
                tier.remaining_count for amount, tier in observed.items() if amount <= 500
            )
            low_progress = Decimal(1) - Decimal(low_remaining) / Decimal(low_original)
            for band, target in (
                (primary, primary_observations),
                (exploratory, exploratory_observations),
            ):
                if not band.eligible:
                    continue
                high_original = sum(
                    observed[amount].original_count for amount in band.prize_amounts
                )
                high_remaining = sum(
                    observed[amount].remaining_count for amount in band.prize_amounts
                )
                target.append(
                    ProgressObservation(
                        observed_at=snapshot.scrape_run.source_observed_at,
                        low_progress=low_progress,
                        high_progress=Decimal(1)
                        - Decimal(high_remaining) / Decimal(high_original),
                    )
                )
        histories.append(
            LagGameHistory(
                game_id=as_of.game_id,
                game_number=as_of.game.game_number,
                top_prize_amount=primary.top_prize_amount,
                primary_band=primary,
                exploratory_band=exploratory,
                primary_observations=(
                    tuple(primary_observations) if not invalid_structure else ()
                ),
                exploratory_observations=(
                    tuple(exploratory_observations) if not invalid_structure else ()
                ),
                prefit_exclusion_code=(
                    "STRUCTURE_CHANGED" if invalid_structure else None
                ),
            )
        )
    return histories


def load_game_baseline_curve(
    session: Session, *, game_id: int, cutoff: ScrapeRun
) -> list[tuple[datetime, Decimal]]:
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
    curve = []
    for snapshot in snapshots:
        baseline = [tier for tier in snapshot.prize_tiers if tier.prize_amount <= 500]
        original = sum(tier.original_count for tier in baseline)
        remaining = sum(tier.remaining_count for tier in baseline)
        if original > 0:
            curve.append(
                (
                    snapshot.scrape_run.source_observed_at,
                    Decimal(remaining) / Decimal(original),
                )
            )
    return curve
