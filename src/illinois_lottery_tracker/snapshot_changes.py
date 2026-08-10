"""Read-only comparison of two unpaid-prizes snapshot sets.

Identifies structural changes between two scrape runs:
- New games: present in the newer snapshot set but not the older.
- Missing games: present in the older snapshot set but not the newer.
- Prize structure changes: same game in both runs, but original prize structure
  fields differ (total_original_prize_value, total_original_winning_tickets,
  top_prizes_original, or individual prize_tier_snapshots.original_count).

This module never writes to the database. All functions call only SELECT queries.

Wording note
------------
A game absent from the latest snapshot is described as "missing from latest
snapshot" — not as ended. One missing capture may reflect a transient source
issue rather than the game's permanent removal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .metrics import estimate_total_tickets
from .models import GameSnapshot, RawSourceSnapshot, ScrapeRun


class InsufficientDataError(Exception):
    """Raised when fewer than two comparable scrape runs exist."""


@dataclass(frozen=True)
class NewGameRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    has_detail_metadata: bool
    has_odds: bool
    has_metrics: bool


@dataclass(frozen=True)
class MissingGameRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    last_seen_scrape_run_id: int
    is_active: bool


@dataclass(frozen=True)
class PrizeTierChange:
    prize_amount: Decimal
    old_original_count: int | None
    new_original_count: int | None


@dataclass(frozen=True)
class StructureChangeRow:
    game_number: str
    game_name: str
    changed_fields: list[str]
    old_total_original_prize_value: Decimal | None
    new_total_original_prize_value: Decimal | None
    old_total_original_winning_tickets: int | None
    new_total_original_winning_tickets: int | None
    old_top_prizes_original: int | None
    new_top_prizes_original: int | None
    old_est_total_tickets: int | None
    new_est_total_tickets: int | None
    prize_tier_changes: list[PrizeTierChange]


@dataclass
class SnapshotChangeReport:
    older_scrape_run_id: int
    newer_scrape_run_id: int
    older_source_captured_at: datetime | None  # from RawSourceSnapshot.captured_at
    older_run_started_at: datetime | None       # from ScrapeRun.started_at
    newer_source_captured_at: datetime | None
    newer_run_started_at: datetime | None
    older_game_count: int
    newer_game_count: int
    new_games: list[NewGameRow] = field(default_factory=list)
    missing_games: list[MissingGameRow] = field(default_factory=list)
    structure_changes: list[StructureChangeRow] = field(default_factory=list)

    @property
    def new_game_count(self) -> int:
        return len(self.new_games)

    @property
    def missing_game_count(self) -> int:
        return len(self.missing_games)

    @property
    def structure_change_count(self) -> int:
        return len(self.structure_changes)


def find_comparable_run_ids(session: Session) -> list[int]:
    """Return IDs of scrape runs with at least one game_snapshot, ordered by source
    capture time (oldest first).

    Ordering key: the earliest RawSourceSnapshot.captured_at for each run, falling
    back to ScrapeRun.started_at for runs that have no RawSourceSnapshot (e.g. runs
    created by legacy import scripts). This ensures that a re-import of an older raw
    file with --force is not treated as a more-recent source capture than a nightly
    run that processed newer content.
    """
    complete_run_ids = list(
        session.scalars(
            select(ScrapeRun.id)
            .where(
                ScrapeRun.workflow == "unpaid_prizes",
                ScrapeRun.status == "success",
                ScrapeRun.is_complete.is_(True),
            )
            .order_by(ScrapeRun.source_observed_at, ScrapeRun.id)
        )
    )
    if complete_run_ids or (
        session.bind is not None and session.bind.dialect.name == "postgresql"
    ):
        return complete_run_ids

    # Legacy SQLite test fixtures only.
    run_ids_with_snaps: set[int] = set(
        session.scalars(select(GameSnapshot.scrape_run_id).distinct()).all()
    )
    if not run_ids_with_snaps:
        return []
    rows = session.execute(
        select(
            ScrapeRun.id,
            func.coalesce(
                func.min(RawSourceSnapshot.captured_at),
                ScrapeRun.started_at,
            ).label("capture_ts"),
        )
        .outerjoin(RawSourceSnapshot, RawSourceSnapshot.scrape_run_id == ScrapeRun.id)
        .where(ScrapeRun.id.in_(run_ids_with_snaps))
        .group_by(ScrapeRun.id, ScrapeRun.started_at)
        .order_by("capture_ts")
    ).all()
    return [row[0] for row in rows]


def find_latest_two_comparable_runs(session: Session) -> tuple[int, int]:
    """Return (older_run_id, newer_run_id) for the two most recent comparable runs.

    Raises InsufficientDataError when fewer than two comparable scrape runs
    (runs with at least one game_snapshot) exist.
    """
    run_ids = find_comparable_run_ids(session)
    if len(run_ids) < 2:
        raise InsufficientDataError(
            f"At least 2 scrape runs with game snapshots are required to compare; "
            f"found {len(run_ids)}."
        )
    return run_ids[-2], run_ids[-1]


def compare_scrape_runs(
    session: Session,
    *,
    older_run_id: int,
    newer_run_id: int,
) -> SnapshotChangeReport:
    """Compare two snapshot sets and return a structural change report.

    Read-only: calls only SELECT queries. Never writes to the database.

    Compares games by game_number. Reports new games (in newer only), missing
    games (in older only), and original prize structure changes for matched games.
    Does not report normal daily remaining-prize movement.
    """
    older_snaps: list[GameSnapshot] = list(
        session.scalars(
            select(GameSnapshot)
            .where(GameSnapshot.scrape_run_id == older_run_id)
            .options(selectinload(GameSnapshot.prize_tiers), selectinload(GameSnapshot.game))
        )
    )
    newer_snaps: list[GameSnapshot] = list(
        session.scalars(
            select(GameSnapshot)
            .where(GameSnapshot.scrape_run_id == newer_run_id)
            .options(selectinload(GameSnapshot.prize_tiers), selectinload(GameSnapshot.game))
        )
    )

    older_run = session.get(ScrapeRun, older_run_id)
    newer_run = session.get(ScrapeRun, newer_run_id)

    def _source_captured_at(run_id: int) -> datetime | None:
        run = session.get(ScrapeRun, run_id)
        if run is not None and run.source_observed_at is not None:
            return run.source_observed_at
        return session.scalar(
            select(func.min(RawSourceSnapshot.captured_at))
            .where(RawSourceSnapshot.scrape_run_id == run_id)
        )

    older_by_number: dict[str, GameSnapshot] = {
        snap.game.game_number: snap for snap in older_snaps
    }
    newer_by_number: dict[str, GameSnapshot] = {
        snap.game.game_number: snap for snap in newer_snaps
    }

    older_numbers = set(older_by_number)
    newer_numbers = set(newer_by_number)

    # --- New games (in newer, not in older) ---
    new_games: list[NewGameRow] = []
    for gnum in sorted(newer_numbers - older_numbers):
        snap = newer_by_number[gnum]
        game = snap.game
        new_games.append(
            NewGameRow(
                game_number=gnum,
                game_name=game.name,
                ticket_price=game.ticket_price,
                has_detail_metadata=game.source_url is not None,
                has_odds=game.overall_odds_one_in is not None,
                has_metrics=game.est_total_tickets is not None,
            )
        )

    # --- Missing games (in older, not in newer) ---
    missing_games: list[MissingGameRow] = []
    for gnum in sorted(older_numbers - newer_numbers):
        snap = older_by_number[gnum]
        game = snap.game
        missing_games.append(
            MissingGameRow(
                game_number=gnum,
                game_name=game.name,
                ticket_price=game.ticket_price,
                last_seen_scrape_run_id=older_run_id,
                is_active=game.is_active,
            )
        )

    # --- Prize structure changes (game in both, original fields differ) ---
    structure_changes: list[StructureChangeRow] = []
    for gnum in sorted(older_numbers & newer_numbers):
        old_snap = older_by_number[gnum]
        new_snap = newer_by_number[gnum]
        game = new_snap.game

        changed_fields: list[str] = []

        if old_snap.total_original_prize_value != new_snap.total_original_prize_value:
            changed_fields.append("total_original_prize_value")

        if old_snap.total_original_winning_tickets != new_snap.total_original_winning_tickets:
            changed_fields.append("total_original_winning_tickets")

        if old_snap.top_prizes_original != new_snap.top_prizes_original:
            changed_fields.append("top_prizes_original")

        old_est_total = estimate_total_tickets(
            old_snap.total_original_winning_tickets, game.overall_odds_one_in
        )
        new_est_total = estimate_total_tickets(
            new_snap.total_original_winning_tickets, game.overall_odds_one_in
        )
        if game.overall_odds_one_in is not None and old_est_total != new_est_total:
            changed_fields.append("est_total_tickets")

        old_tiers: dict[Decimal, int | None] = {
            tier.prize_amount: tier.original_count for tier in old_snap.prize_tiers
        }
        new_tiers: dict[Decimal, int | None] = {
            tier.prize_amount: tier.original_count for tier in new_snap.prize_tiers
        }

        tier_changes: list[PrizeTierChange] = []
        for amount in sorted(set(old_tiers) | set(new_tiers)):
            in_old = amount in old_tiers
            in_new = amount in new_tiers
            old_count = old_tiers.get(amount)
            new_count = new_tiers.get(amount)
            if not in_old or not in_new or old_count != new_count:
                tier_changes.append(
                    PrizeTierChange(
                        prize_amount=amount,
                        old_original_count=old_count,
                        new_original_count=new_count,
                    )
                )

        if tier_changes:
            changed_fields.append("prize_tier_original_counts")

        if changed_fields:
            structure_changes.append(
                StructureChangeRow(
                    game_number=gnum,
                    game_name=game.name,
                    changed_fields=changed_fields,
                    old_total_original_prize_value=old_snap.total_original_prize_value,
                    new_total_original_prize_value=new_snap.total_original_prize_value,
                    old_total_original_winning_tickets=old_snap.total_original_winning_tickets,
                    new_total_original_winning_tickets=new_snap.total_original_winning_tickets,
                    old_top_prizes_original=old_snap.top_prizes_original,
                    new_top_prizes_original=new_snap.top_prizes_original,
                    old_est_total_tickets=old_est_total,
                    new_est_total_tickets=new_est_total,
                    prize_tier_changes=tier_changes,
                )
            )

    return SnapshotChangeReport(
        older_scrape_run_id=older_run_id,
        newer_scrape_run_id=newer_run_id,
        older_source_captured_at=_source_captured_at(older_run_id),
        older_run_started_at=older_run.started_at if older_run else None,
        newer_source_captured_at=_source_captured_at(newer_run_id),
        newer_run_started_at=newer_run.started_at if newer_run else None,
        older_game_count=len(older_snaps),
        newer_game_count=len(newer_snaps),
        new_games=new_games,
        missing_games=missing_games,
        structure_changes=structure_changes,
    )
