"""Read-only reconciliation between unpaid-prizes snapshot coverage and
instant-ticket detail metadata.

Reads from the database (never writes). Optionally accepts fresh-parsed detail
objects to enable price and name-mismatch checks that cannot be derived from
stored state alone.

has_unpaid_snapshot proxy
--------------------------
A game is considered to have unpaid-prizes snapshot data if it has at least one
row in ``game_snapshots``. The unpaid-prizes importer creates snapshots; the
detail-metadata importer does not.

has_detail_metadata proxy
--------------------------
A game is considered to have instant-ticket detail metadata if
``games.source_url`` is not NULL. The detail-metadata importer sets
``source_url`` from the detail page URL; the unpaid-prizes importer does not.

Schema limitations
------------------
Price and name mismatch checks require ``detail_inputs``. Once both importers
have run, the stored ``games.ticket_price`` and ``games.name`` reflect the
merged/resolved value, not the pre-import disagreement. Pass re-parsed
``ParsedInstantTicketDetail`` objects to enable these checks.

Hub-card duplicate note
-----------------------
Hub discovery finds 58 card entries but only 57 unique game numbers. The extra
card is a duplicate jurassic-park URL appearing on both hub page 2 and page 3.
This is a source-page issue, not a parser or DB issue. The report preserves this
known explanation in ``hub_note``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .instant_ticket_detail_parser import ParsedInstantTicketDetail
from .models import Game, GameSnapshot

HUB_NOTE = (
    "Hub discovery found 58 card entries but only 57 unique game numbers. "
    "The extra card is a duplicate jurassic-park URL appearing on both hub "
    "page 2 and page 3. This is a source-page issue, not a parser or DB issue."
)

_PRICE_MISMATCH_NOTE = (
    "Price and name mismatch checks require detail_inputs (re-parsed HTML). "
    "Once both importers have run, the stored games.ticket_price and games.name "
    "reflect the merged value. Pass ParsedInstantTicketDetail objects via "
    "detail_inputs to enable these checks."
)


@dataclass(frozen=True)
class GameReconciliationRow:
    game_number: str
    game_name: str | None
    has_unpaid_snapshot: bool
    has_detail_metadata: bool
    ticket_price: Decimal | None
    overall_odds_one_in: Decimal | None
    launch_date: date | None


@dataclass(frozen=True)
class PriceMismatchRow:
    game_number: str
    game_name: str | None
    db_price: Decimal | None
    detail_price: Decimal | None


@dataclass(frozen=True)
class NameMismatchRow:
    game_number: str
    db_name: str | None
    detail_name: str | None


@dataclass
class ReconciliationReport:
    # Summary counts
    total_games: int
    games_with_unpaid_snapshot: int
    games_with_detail_metadata: int
    games_matched: int
    unpaid_only_count: int
    detail_only_count: int
    price_mismatch_count: int
    name_mismatch_count: int
    missing_overall_odds_count: int
    missing_launch_date_count: int
    duplicate_game_numbers_in_details: int

    # Detailed rows by mismatch category
    all_rows: list[GameReconciliationRow] = field(default_factory=list)
    unpaid_only: list[GameReconciliationRow] = field(default_factory=list)
    detail_only: list[GameReconciliationRow] = field(default_factory=list)
    price_mismatches: list[PriceMismatchRow] = field(default_factory=list)
    name_mismatches: list[NameMismatchRow] = field(default_factory=list)
    missing_odds: list[GameReconciliationRow] = field(default_factory=list)
    missing_dates: list[GameReconciliationRow] = field(default_factory=list)
    duplicate_game_numbers: list[str] = field(default_factory=list)

    # Contextual notes
    schema_notes: list[str] = field(default_factory=list)
    hub_note: str = HUB_NOTE


def _detail_name(d: ParsedInstantTicketDetail) -> str | None:
    return d.game_name or d.display_name


def _to_decimal(value: int | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def reconcile(
    *,
    session: Session,
    detail_inputs: list[ParsedInstantTicketDetail] | None = None,
) -> ReconciliationReport:
    """Return a read-only reconciliation report comparing both data sources.

    Never writes to the database. Calls only SELECT queries.

    ``detail_inputs``: when provided, enables price and name mismatch checks
    (comparing fresh-parsed values against stored DB state) and detects
    duplicate game_numbers within the detail input list. Games present in
    ``detail_inputs`` but absent from the DB are included as detail-only rows.
    """
    # --- Fetch DB state (read-only: SELECT only) ----------------------------
    snapshot_game_ids: set[int] = set(
        session.scalars(select(GameSnapshot.game_id).distinct()).all()
    )
    games: list[Game] = list(
        session.scalars(select(Game).order_by(Game.game_number)).all()
    )

    # --- Build detail lookup ------------------------------------------------
    detail_by_number: dict[str, ParsedInstantTicketDetail] = {}
    duplicate_game_numbers: list[str] = []

    if detail_inputs is not None:
        for d in detail_inputs:
            if d.game_number is None:
                continue
            if d.game_number in detail_by_number:
                if d.game_number not in duplicate_game_numbers:
                    duplicate_game_numbers.append(d.game_number)
            else:
                detail_by_number[d.game_number] = d

    # --- Build per-game reconciliation rows ---------------------------------
    all_rows: list[GameReconciliationRow] = []
    unpaid_only: list[GameReconciliationRow] = []
    detail_only: list[GameReconciliationRow] = []
    price_mismatches: list[PriceMismatchRow] = []
    name_mismatches: list[NameMismatchRow] = []
    missing_odds: list[GameReconciliationRow] = []
    missing_dates: list[GameReconciliationRow] = []
    db_game_numbers: set[str] = set()

    for game in games:
        db_game_numbers.add(game.game_number)
        has_snapshot = game.id in snapshot_game_ids
        has_detail = game.source_url is not None

        row = GameReconciliationRow(
            game_number=game.game_number,
            game_name=game.name,
            has_unpaid_snapshot=has_snapshot,
            has_detail_metadata=has_detail,
            ticket_price=game.ticket_price,
            overall_odds_one_in=game.overall_odds_one_in,
            launch_date=game.launch_date,
        )
        all_rows.append(row)

        if has_snapshot and not has_detail:
            unpaid_only.append(row)
        elif has_detail and not has_snapshot:
            detail_only.append(row)

        if row.overall_odds_one_in is None:
            missing_odds.append(row)
        if row.launch_date is None:
            missing_dates.append(row)

        # Mismatch checks — only when fresh detail data is available
        if detail_inputs is not None and game.game_number in detail_by_number:
            d = detail_by_number[game.game_number]
            detail_price = _to_decimal(d.ticket_price)
            if (
                detail_price is not None
                and game.ticket_price is not None
                and detail_price != game.ticket_price
            ):
                price_mismatches.append(
                    PriceMismatchRow(
                        game_number=game.game_number,
                        game_name=game.name,
                        db_price=game.ticket_price,
                        detail_price=detail_price,
                    )
                )

            detail_name = _detail_name(d)
            if detail_name and game.name and detail_name != game.name:
                name_mismatches.append(
                    NameMismatchRow(
                        game_number=game.game_number,
                        db_name=game.name,
                        detail_name=detail_name,
                    )
                )

    # Detail-only: games in detail_inputs not yet in the DB
    if detail_inputs is not None:
        for gnum, d in detail_by_number.items():
            if gnum in db_game_numbers:
                continue
            row = GameReconciliationRow(
                game_number=gnum,
                game_name=_detail_name(d),
                has_unpaid_snapshot=False,
                has_detail_metadata=True,
                ticket_price=_to_decimal(d.ticket_price),
                overall_odds_one_in=d.overall_odds,
                launch_date=d.launch_date,
            )
            all_rows.append(row)
            detail_only.append(row)
            if row.overall_odds_one_in is None:
                missing_odds.append(row)
            if row.launch_date is None:
                missing_dates.append(row)

    # Schema limitation note when mismatch checks are unavailable
    schema_notes: list[str] = []
    if detail_inputs is None:
        schema_notes.append(_PRICE_MISMATCH_NOTE)

    # Summary counts
    games_with_unpaid = sum(1 for r in all_rows if r.has_unpaid_snapshot)
    games_with_detail = sum(1 for r in all_rows if r.has_detail_metadata)
    games_matched = sum(
        1 for r in all_rows if r.has_unpaid_snapshot and r.has_detail_metadata
    )

    return ReconciliationReport(
        total_games=len(all_rows),
        games_with_unpaid_snapshot=games_with_unpaid,
        games_with_detail_metadata=games_with_detail,
        games_matched=games_matched,
        unpaid_only_count=len(unpaid_only),
        detail_only_count=len(detail_only),
        price_mismatch_count=len(price_mismatches),
        name_mismatch_count=len(name_mismatches),
        missing_overall_odds_count=len(missing_odds),
        missing_launch_date_count=len(missing_dates),
        duplicate_game_numbers_in_details=len(duplicate_game_numbers),
        all_rows=sorted(all_rows, key=lambda r: r.game_number),
        unpaid_only=unpaid_only,
        detail_only=detail_only,
        price_mismatches=price_mismatches,
        name_mismatches=name_mismatches,
        missing_odds=missing_odds,
        missing_dates=missing_dates,
        duplicate_game_numbers=duplicate_game_numbers,
        schema_notes=schema_notes,
        hub_note=HUB_NOTE,
    )
