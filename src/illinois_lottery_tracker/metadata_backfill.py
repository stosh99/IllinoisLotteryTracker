"""Backfill stable game metadata for games found in unpaid-prizes snapshots."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .importer import import_instant_ticket_detail_metadata
from .instant_ticket_detail_parser import (
    ParsedInstantTicketDetail,
    parse_instant_ticket_detail_html,
)
from .instant_ticket_discovery import parse_instant_ticket_hub_html
from .models import Game, GameSnapshot
from .raw_collector import (
    BatchPageResult,
    RawCollectionResult,
    collect_pages_batch,
    collect_raw_snapshot,
)

HUB_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"
DETAIL_WAIT_SELECTOR = "div.itg-details-block"
HUB_WAIT_SELECTOR = "div.simple-game-card"

KNOWN_METADATA_MISSING_GAME_NUMBERS = frozenset(
    {
        # Active in unpaid-prizes data, but no current detail page was found.
        # The likely slug resolves to a newer game.
        "7587",
    }
)

CollectRawSnapshot = Callable[..., RawCollectionResult]
CollectPagesBatch = Callable[..., list[BatchPageResult]]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class MissingMetadataGame:
    game_number: str
    name: str


@dataclass(frozen=True)
class MetadataBackfillResult:
    missing_before: int
    ignored_known_missing: tuple[str, ...]
    attempted_games: tuple[str, ...]
    detail_urls_discovered: int
    detail_pages_fetched: int
    detail_pages_failed: int
    detail_pages_parsed: int
    matching_details: int
    games_created: int
    games_updated: int
    details_skipped: int
    parser_warnings: tuple[str, ...] = ()
    import_issues: tuple[str, ...] = ()
    still_missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed_games(self) -> int:
        return self.games_created + self.games_updated


def find_missing_metadata_games(
    session: Session,
    *,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
) -> list[MissingMetadataGame]:
    """Return games with snapshots but incomplete detail metadata."""
    rows = session.execute(
        select(Game.game_number, Game.name)
        .where(
            exists(select(GameSnapshot.id).where(GameSnapshot.game_id == Game.id)),
            Game.game_number.not_in(tuple(ignored_game_numbers)),
            (
                (Game.source_url.is_(None))
                | (Game.launch_date.is_(None))
                | (Game.overall_odds_one_in.is_(None))
            ),
        )
        .order_by(Game.game_number)
    ).all()
    return [MissingMetadataGame(game_number=row[0], name=row[1]) for row in rows]


def ignored_missing_metadata_game_numbers(
    session: Session,
    *,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
) -> tuple[str, ...]:
    """Return ignored game numbers that are currently missing metadata."""
    rows = session.scalars(
        select(Game.game_number)
        .where(
            exists(select(GameSnapshot.id).where(GameSnapshot.game_id == Game.id)),
            Game.game_number.in_(tuple(ignored_game_numbers)),
            (
                (Game.source_url.is_(None))
                | (Game.launch_date.is_(None))
                | (Game.overall_odds_one_in.is_(None))
            ),
        )
        .order_by(Game.game_number)
    ).all()
    return tuple(rows)


def discover_instant_ticket_detail_urls(
    settings: Settings,
    *,
    collect_raw_snapshot_fn: CollectRawSnapshot = collect_raw_snapshot,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Walk the instant-ticket hub and return unique detail page URLs."""
    detail_urls: list[str] = []
    seen_detail: set[str] = set()
    hub_url: str | None = HUB_URL
    visited_hub: set[str] = set()
    page_num = 0

    while hub_url and hub_url not in visited_hub:
        visited_hub.add(hub_url)
        page_num += 1
        if progress:
            progress(f"Hub page {page_num}: {hub_url}")
        result = collect_raw_snapshot_fn(
            url=hub_url,
            settings=settings,
            filename_prefix=f"instant-ticket-hub-page-{page_num:03d}",
            wait_selector=HUB_WAIT_SELECTOR,
        )
        html = Path(result.file_path).read_text(encoding="utf-8")
        discovery = parse_instant_ticket_hub_html(html, source_url=hub_url)
        for ticket in discovery.tickets:
            if ticket.detail_url not in seen_detail:
                seen_detail.add(ticket.detail_url)
                detail_urls.append(ticket.detail_url)
        hub_url = discovery.pagination_urls[0] if discovery.pagination_urls else None

    return detail_urls


def backfill_missing_game_metadata(
    session: Session,
    *,
    settings: Settings | None = None,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
    max_detail_pages: int | None = None,
    collect_raw_snapshot_fn: CollectRawSnapshot = collect_raw_snapshot,
    collect_pages_batch_fn: CollectPagesBatch = collect_pages_batch,
    progress: ProgressCallback | None = None,
) -> MetadataBackfillResult:
    """Fetch current detail pages and import metadata for missing games.

    The caller owns transaction commit/rollback. Network and page-fetch failures
    are reported in the result; they do not raise unless discovery itself fails.
    """
    settings = settings or get_settings()
    ignored = ignored_missing_metadata_game_numbers(
        session,
        ignored_game_numbers=ignored_game_numbers,
    )
    missing_games = find_missing_metadata_games(
        session,
        ignored_game_numbers=ignored_game_numbers,
    )
    missing_numbers = {game.game_number for game in missing_games}
    missing_before = len(missing_games) + len(ignored)

    if not missing_games:
        return MetadataBackfillResult(
            missing_before=missing_before,
            ignored_known_missing=ignored,
            attempted_games=(),
            detail_urls_discovered=0,
            detail_pages_fetched=0,
            detail_pages_failed=0,
            detail_pages_parsed=0,
            matching_details=0,
            games_created=0,
            games_updated=0,
            details_skipped=0,
            still_missing=(),
        )

    detail_urls = discover_instant_ticket_detail_urls(
        settings,
        collect_raw_snapshot_fn=collect_raw_snapshot_fn,
        progress=progress,
    )
    if max_detail_pages is not None:
        detail_urls = detail_urls[:max_detail_pages]

    url_prefix_pairs = [
        (url, f"instant-ticket-detail-{_slug_from_url(url)}")
        for url in detail_urls
    ]

    if progress:
        progress(f"Fetching {len(url_prefix_pairs)} detail pages")
    batch_results = collect_pages_batch_fn(
        url_prefix_pairs,
        settings=settings,
        wait_selector=DETAIL_WAIT_SELECTOR,
    )

    parsed_details: list[ParsedInstantTicketDetail] = []
    parser_errors: list[str] = []
    parsed_page_count = 0
    for result in batch_results:
        if not result.success:
            continue
        assert result.file_path is not None
        try:
            parsed = parse_instant_ticket_detail_html(
                Path(result.file_path),
                source_url=result.url,
            )
        except Exception as exc:  # noqa: BLE001
            parser_errors.append(f"{result.url}: {exc}")
            continue
        parsed_page_count += 1
        if parsed.game_number in missing_numbers:
            parsed_details.append(parsed)
            if progress:
                progress(f"Matched metadata for game {parsed.game_number}")
            if len({detail.game_number for detail in parsed_details}) == len(missing_numbers):
                break

    import_result = import_instant_ticket_detail_metadata(session, parsed_details)
    session.flush()

    still_missing = tuple(
        game.game_number
        for game in find_missing_metadata_games(
            session,
            ignored_game_numbers=ignored_game_numbers,
        )
    )
    import_issues = tuple(
        f"game_number={issue.game_number!r} game={issue.game_name!r}: {issue.message}"
        for issue in import_result.issues
    )

    return MetadataBackfillResult(
        missing_before=missing_before,
        ignored_known_missing=ignored,
        attempted_games=tuple(game.game_number for game in missing_games),
        detail_urls_discovered=len(detail_urls),
        detail_pages_fetched=sum(1 for result in batch_results if result.success),
        detail_pages_failed=sum(1 for result in batch_results if not result.success),
        detail_pages_parsed=parsed_page_count,
        matching_details=len(parsed_details),
        games_created=import_result.games_created,
        games_updated=import_result.games_updated,
        details_skipped=import_result.details_skipped,
        parser_warnings=tuple(import_result.parser_warnings + parser_errors),
        import_issues=import_issues,
        still_missing=still_missing,
    )


def render_metadata_backfill_result(result: MetadataBackfillResult) -> str:
    """Render a concise text summary for CLI and nightly logs."""
    lines = [
        "Metadata backfill:",
        f"  Missing before:              {result.missing_before}",
        f"  Ignored known missing:       {len(result.ignored_known_missing)}",
        f"  Attempted games:             {len(result.attempted_games)}",
        f"  Detail URLs discovered:      {result.detail_urls_discovered}",
        f"  Detail pages fetched:        {result.detail_pages_fetched}",
        f"  Detail pages failed:         {result.detail_pages_failed}",
        f"  Matching details parsed:     {result.matching_details}",
        f"  Games created:               {result.games_created}",
        f"  Games updated:               {result.games_updated}",
        f"  Details skipped:             {result.details_skipped}",
        f"  Still missing:               {len(result.still_missing)}",
    ]
    if result.ignored_known_missing:
        lines.append("  Ignored game numbers:        " + ", ".join(result.ignored_known_missing))
    if result.attempted_games:
        lines.append("  Attempted game numbers:      " + ", ".join(result.attempted_games))
    if result.still_missing:
        lines.append("  Still missing game numbers:  " + ", ".join(result.still_missing))
    if result.parser_warnings:
        lines.append(f"  Parser warnings:             {len(result.parser_warnings)}")
    if result.import_issues:
        lines.append(f"  Import issues:               {len(result.import_issues)}")
    return "\n".join(lines) + "\n"


def stderr_progress(message: str) -> None:
    print(message, file=sys.stderr)


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown"
