"""Import parsed unpaid-prizes data into the database.

This module bridges the rendered-HTML parser and the snapshot tables. It does
not fetch the network, parse instant-ticket detail pages, or calculate EV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .instant_ticket_detail_parser import ParsedInstantTicketDetail
from .models import Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun
from .parser import ParsedGame, ParsedPrizeTier, ParseResult, ParseWarning

_TOP_PRIZE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")


@dataclass(frozen=True)
class ImportIssue:
    message: str
    game_number: str | None = None
    game_name: str | None = None


@dataclass(frozen=True)
class UnpaidPrizesImportResult:
    games_seen: int = 0
    games_upserted: int = 0
    games_skipped: int = 0
    snapshots_inserted: int = 0
    snapshots_skipped_existing: int = 0
    prize_tiers_inserted: int = 0
    parser_warnings: list[ParseWarning] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)


@dataclass(frozen=True)
class DetailMetadataImportResult:
    details_seen: int = 0
    games_created: int = 0
    games_updated: int = 0
    details_skipped: int = 0
    parser_warnings: list[str] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)


def _money(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _sum_counts(tiers: list[ParsedPrizeTier], attr: str) -> int | None:
    values = [getattr(tier, attr) for tier in tiers]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _sum_prize_value(tiers: list[ParsedPrizeTier], count_attr: str) -> Decimal | None:
    total = Decimal("0")
    saw_value = False
    for tier in tiers:
        count = getattr(tier, count_attr)
        if tier.prize_amount is None or count is None:
            continue
        total += Decimal(tier.prize_amount) * Decimal(count)
        saw_value = True
    return total if saw_value else None


def _top_tier(tiers: list[ParsedPrizeTier]) -> ParsedPrizeTier | None:
    comparable = [tier for tier in tiers if tier.prize_amount is not None]
    if not comparable:
        return None
    return max(comparable, key=lambda tier: tier.prize_amount or 0)


def _claimed_count(tier: ParsedPrizeTier) -> int | None:
    if tier.total_prizes is None or tier.unclaimed_prizes is None:
        return None
    return tier.total_prizes - tier.unclaimed_prizes


def _game_name(parsed: ParsedGame) -> str | None:
    return parsed.game_name or parsed.display_name


def _detail_name(parsed: ParsedInstantTicketDetail) -> str | None:
    return parsed.game_name or parsed.display_name


def _top_prize_amount(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = _TOP_PRIZE_RE.search(text)
    if match is None:
        return None
    return Decimal(match.group(1).replace(",", ""))


def _get_or_create_game(session: Session, parsed: ParsedGame) -> tuple[Game, bool]:
    assert parsed.game_number is not None
    game = session.scalar(select(Game).where(Game.game_number == parsed.game_number))
    created = game is None
    if game is None:
        game = Game(game_number=parsed.game_number, name=_game_name(parsed) or "Unknown")
        session.add(game)

    name = _game_name(parsed)
    if name:
        game.name = name
    if parsed.ticket_price is not None:
        game.ticket_price = _money(parsed.ticket_price)
    game.is_active = True
    return game, created


def _build_game_snapshot(
    parsed: ParsedGame,
    *,
    game: Game,
    scrape_run: ScrapeRun,
    captured_at: datetime | None,
) -> GameSnapshot:
    top = _top_tier(parsed.prize_tiers)
    return GameSnapshot(
        game=game,
        scrape_run=scrape_run,
        captured_at=captured_at or scrape_run.finished_at or scrape_run.started_at,
        total_original_prize_value=_sum_prize_value(parsed.prize_tiers, "total_prizes"),
        total_remaining_prize_value=_sum_prize_value(
            parsed.prize_tiers, "unclaimed_prizes"
        ),
        total_original_winning_tickets=_sum_counts(parsed.prize_tiers, "total_prizes"),
        total_remaining_winning_tickets=_sum_counts(
            parsed.prize_tiers, "unclaimed_prizes"
        ),
        top_prizes_original=top.total_prizes if top else None,
        top_prizes_remaining=top.unclaimed_prizes if top else None,
        weeks_in_market=parsed.weeks_in_market,
    )


def import_unpaid_prizes_parse_result(
    session: Session,
    parse_result: ParseResult,
    *,
    scrape_run: ScrapeRun,
    captured_at: datetime | None = None,
) -> UnpaidPrizesImportResult:
    """Persist parsed unpaid-prizes games and prize tiers for one scrape run.

    Idempotency is scoped to ``(game_id, scrape_run_id)``. If a snapshot already
    exists for that pair, it is left untouched and counted as skipped.
    """
    session.flush()
    result = UnpaidPrizesImportResult(
        games_seen=len(parse_result.games),
        parser_warnings=list(parse_result.warnings),
    )
    issues = list(result.issues)
    games_upserted = 0
    games_skipped = 0
    snapshots_inserted = 0
    snapshots_skipped_existing = 0
    prize_tiers_inserted = 0

    for parsed in parse_result.games:
        if not parsed.game_number:
            games_skipped += 1
            issues.append(
                ImportIssue(
                    message="skipped parsed game without game_number",
                    game_name=_game_name(parsed),
                )
            )
            continue

        game, _created = _get_or_create_game(session, parsed)
        games_upserted += 1
        session.flush()

        existing_snapshot = session.scalar(
            select(GameSnapshot).where(
                GameSnapshot.game_id == game.id,
                GameSnapshot.scrape_run_id == scrape_run.id,
            )
        )
        if existing_snapshot is not None:
            snapshots_skipped_existing += 1
            continue

        snapshot = _build_game_snapshot(
            parsed, game=game, scrape_run=scrape_run, captured_at=captured_at
        )
        session.add(snapshot)
        session.flush()
        snapshots_inserted += 1

        for tier in parsed.prize_tiers:
            if tier.prize_amount is None:
                issues.append(
                    ImportIssue(
                        message="skipped prize tier without prize_amount",
                        game_number=parsed.game_number,
                        game_name=_game_name(parsed),
                    )
                )
                continue
            session.add(
                PrizeTierSnapshot(
                    game_snapshot=snapshot,
                    prize_amount=_money(tier.prize_amount),
                    original_count=tier.total_prizes,
                    remaining_count=tier.unclaimed_prizes,
                    claimed_count=_claimed_count(tier),
                )
            )
            prize_tiers_inserted += 1

    return UnpaidPrizesImportResult(
        games_seen=result.games_seen,
        games_upserted=games_upserted,
        games_skipped=games_skipped,
        snapshots_inserted=snapshots_inserted,
        snapshots_skipped_existing=snapshots_skipped_existing,
        prize_tiers_inserted=prize_tiers_inserted,
        parser_warnings=result.parser_warnings,
        issues=issues,
    )


def import_instant_ticket_detail_metadata(
    session: Session,
    details: list[ParsedInstantTicketDetail],
    *,
    create_missing_games: bool = True,
) -> DetailMetadataImportResult:
    """Upsert stable instant-ticket detail metadata onto ``games``.

    This writes only the ``games`` table. It does not create prize snapshots,
    update prize tiers, or calculate EV.
    """
    details_seen = len(details)
    games_created = 0
    games_updated = 0
    details_skipped = 0
    issues: list[ImportIssue] = []
    parser_warnings: list[str] = []
    seen_numbers: set[str] = set()

    for detail in details:
        parser_warnings.extend(detail.warnings)
        name = _detail_name(detail)

        if detail.game_number is None:
            details_skipped += 1
            issues.append(
                ImportIssue(
                    message="skipped detail metadata without game_number",
                    game_name=name,
                )
            )
            continue

        if detail.game_number in seen_numbers:
            details_skipped += 1
            issues.append(
                ImportIssue(
                    message="duplicate game_number in detail metadata inputs",
                    game_number=detail.game_number,
                    game_name=name,
                )
            )
            continue
        seen_numbers.add(detail.game_number)

        game = session.scalar(select(Game).where(Game.game_number == detail.game_number))
        created = False
        if game is None:
            if not create_missing_games:
                details_skipped += 1
                issues.append(
                    ImportIssue(
                        message="skipped detail metadata with no existing game",
                        game_number=detail.game_number,
                        game_name=name,
                    )
                )
                continue
            game = Game(game_number=detail.game_number, name=name or "Unknown")
            session.add(game)
            created = True

        changed = created

        if name:
            if game.name and game.name != name:
                issues.append(
                    ImportIssue(
                        message=(
                            "game_name/display_name mismatch: "
                            f"existing={game.name!r} parsed={name!r}"
                        ),
                        game_number=detail.game_number,
                        game_name=name,
                    )
                )
                game.name = name
                changed = True
            elif not game.name:
                game.name = name
                changed = True

        if detail.ticket_price is not None:
            parsed_price = _money(detail.ticket_price)
            if game.ticket_price is not None and game.ticket_price != parsed_price:
                issues.append(
                    ImportIssue(
                        message=(
                            "ticket_price mismatch: "
                            f"existing={game.ticket_price!s} parsed={parsed_price!s}"
                        ),
                        game_number=detail.game_number,
                        game_name=name,
                    )
                )
            elif game.ticket_price is None:
                game.ticket_price = parsed_price
                changed = True

        updates = (
            ("source_url", detail.source_url),
            ("launch_date", detail.launch_date),
            ("overall_odds_one_in", detail.overall_odds),
            ("category", detail.category),
            ("play_style", detail.play_style),
            ("top_prize_amount", _top_prize_amount(detail.top_prize_text)),
        )
        for attr, value in updates:
            if value is not None and getattr(game, attr) is None:
                setattr(game, attr, value)
                changed = True

        unsupported_fields = []
        if detail.image_url is not None:
            unsupported_fields.append("image_url")
        if detail.play_instructions is not None:
            unsupported_fields.append("play_instructions")
        if detail.overall_odds_text is not None:
            unsupported_fields.append("overall_odds_text")
        if detail.consolidated_odds_present:
            unsupported_fields.append("consolidated_odds_present")
        if detail.raw_fields:
            unsupported_fields.append("raw_fields")
        if unsupported_fields:
            issues.append(
                ImportIssue(
                    message=(
                        "unsupported parsed fields not stored due to schema gaps: "
                        + ", ".join(unsupported_fields)
                    ),
                    game_number=detail.game_number,
                    game_name=name,
                )
            )

        if created:
            games_created += 1
        elif changed:
            games_updated += 1

    return DetailMetadataImportResult(
        details_seen=details_seen,
        games_created=games_created,
        games_updated=games_updated,
        details_skipped=details_skipped,
        parser_warnings=parser_warnings,
        issues=issues,
    )
