"""Collect, normalize, map, and persist instant-ticket retail catalog runs."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .instant_ticket_discovery import (
    DiscoveredInstantTicket,
    InstantTicketHubDiscoveryResult,
    parse_instant_ticket_hub_html,
)
from .models import (
    CatalogQualityIssue,
    Game,
    GameCatalogSnapshot,
    GameSnapshot,
    RawSourceSnapshot,
    ScrapeRun,
)
from .raw_collector import (
    PersistentChromeOptions,
    RawCollectionResult,
    collect_raw_snapshot,
)
from .source_quality import chicago_source_date

HUB_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"
HUB_WAIT_SELECTOR = "div.simple-game-card"
CATALOG_PIPELINE_VERSION = "instant-ticket-catalog-v1"
# The hub's own total occasionally disagrees with the cards it serves (for example,
# a card repeated across a page boundary after games retire). Small disagreements
# are published with a quality issue; larger ones still indicate a broken crawl.
CATALOG_COUNT_TOLERANCE = 3


class CatalogValidationError(ValueError):
    """Raised when a catalog crawl cannot be published as complete."""


@dataclass(frozen=True)
class CatalogCountCheck:
    source_total: int
    unique_count: int
    raw_count: int
    duplicate_urls: list[str]

    @property
    def mismatch(self) -> int:
        return self.unique_count - self.source_total


@dataclass(frozen=True)
class CatalogPageCapture:
    page_number: int
    collection: RawCollectionResult
    discovery: InstantTicketHubDiscoveryResult


@dataclass(frozen=True)
class CatalogPersistResult:
    scrape_run_id: int
    created: bool
    page_count: int
    unique_entry_count: int
    mapped_count: int
    unmapped_count: int
    ambiguous_count: int
    manifest_sha256: str
    source_total: int
    duplicate_urls: list[str]
    missing_since_previous: list[str]
    new_since_previous: list[str]


def normalize_catalog_name(value: str) -> str:
    value = value.replace("™", " ").replace("®", " ").replace("©", " ")
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def catalog_manifest_sha256(pages: list[CatalogPageCapture]) -> str:
    document = [
        {
            "page_number": page.page_number,
            "source_url": page.collection.source_url,
            "sha256": page.collection.sha256,
        }
        for page in sorted(pages, key=lambda item: item.page_number)
    ]
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def collect_catalog_pages(
    *,
    settings: Settings | None = None,
    collect_raw_snapshot_fn=collect_raw_snapshot,
    progress=None,
    chrome_options: PersistentChromeOptions | None = None,
) -> list[CatalogPageCapture]:
    settings = settings or get_settings()
    captures: list[CatalogPageCapture] = []
    current_url: str | None = HUB_URL
    visited: set[str] = set()
    page_number = 0
    while current_url and current_url not in visited:
        visited.add(current_url)
        page_number += 1
        if progress:
            progress(f"Catalog page {page_number}: {current_url}")
        collection_kwargs = {
            "url": current_url,
            "settings": settings,
            "filename_prefix": f"instant-ticket-hub-page-{page_number:03d}",
            "wait_selector": HUB_WAIT_SELECTOR,
        }
        if chrome_options is not None:
            collection_kwargs["chrome_options"] = chrome_options
        collection = collect_raw_snapshot_fn(**collection_kwargs)
        discovery = parse_instant_ticket_hub_html(
            Path(collection.file_path), source_url=current_url
        )
        captures.append(CatalogPageCapture(page_number, collection, discovery))
        current_url = discovery.pagination_urls[0] if discovery.pagination_urls else None
    if not captures:
        raise CatalogValidationError("catalog crawl returned no pages")
    check_catalog_pages(captures)
    return captures


def check_catalog_pages(pages: list[CatalogPageCapture]) -> CatalogCountCheck:
    """Validate a crawl and report how its card count compares with the hub total."""
    cards = _unique_cards(pages)
    return _validate_catalog_pages(pages, cards)


def _unique_cards(
    pages: list[CatalogPageCapture],
) -> list[tuple[int, int, DiscoveredInstantTicket]]:
    entries: list[tuple[int, int, DiscoveredInstantTicket]] = []
    seen: set[str] = set()
    for page in sorted(pages, key=lambda item: item.page_number):
        for position, card in enumerate(page.discovery.tickets):
            if card.detail_url in seen:
                continue
            seen.add(card.detail_url)
            if (
                not card.detail_url
                or not card.display_name
                or card.ticket_price is None
                or card.ticket_price <= 0
            ):
                raise CatalogValidationError(
                    f"catalog card lacks required name/price: {card.detail_url}"
                )
            entries.append((page.page_number, position, card))
    if not entries:
        raise CatalogValidationError("catalog crawl returned no valid unique cards")
    return entries


def _validate_catalog_pages(
    pages: list[CatalogPageCapture],
    cards: list[tuple[int, int, DiscoveredInstantTicket]],
) -> CatalogCountCheck:
    ordered = sorted(pages, key=lambda item: item.page_number)
    page_numbers = [page.page_number for page in ordered]
    if page_numbers != list(range(1, len(ordered) + 1)):
        raise CatalogValidationError("catalog pages are not a contiguous 1-based sequence")
    source_urls = [page.collection.source_url.rstrip("/") for page in ordered]
    if len(source_urls) != len(set(source_urls)):
        raise CatalogValidationError("catalog crawl repeated a page URL")
    totals = {
        page.discovery.total_count
        for page in ordered
        if page.discovery.total_count is not None
    }
    if not totals:
        raise CatalogValidationError("catalog source total is unavailable")
    if len(totals) != 1:
        raise CatalogValidationError("catalog pages disagree on the source total")
    expected_total = totals.pop()
    if abs(expected_total - len(cards)) > CATALOG_COUNT_TOLERANCE:
        raise CatalogValidationError(
            f"catalog unique-card count {len(cards)} does not match source total "
            f"{expected_total}"
        )
    # The tolerance must not hide a partially loaded page: every page before the
    # last is a full page, and the last page is no larger than a full page.
    page_size = len(ordered[0].discovery.tickets)
    for page in ordered[:-1]:
        if len(page.discovery.tickets) != page_size:
            raise CatalogValidationError(
                f"catalog page {page.page_number} has {len(page.discovery.tickets)} "
                f"cards; expected a full page of {page_size}"
            )
    if len(ordered) > 1 and len(ordered[-1].discovery.tickets) > page_size:
        raise CatalogValidationError(
            f"catalog page {ordered[-1].page_number} has more cards than a full page"
        )
    for index, page in enumerate(ordered):
        next_urls = [url.rstrip("/") for url in page.discovery.pagination_urls]
        if len(next_urls) > 1:
            raise CatalogValidationError(
                f"catalog page {page.page_number} has multiple next-page URLs"
            )
        if index < len(ordered) - 1:
            expected_next = source_urls[index + 1]
            if next_urls != [expected_next]:
                raise CatalogValidationError(
                    f"catalog page {page.page_number} does not link to captured page "
                    f"{ordered[index + 1].page_number}"
                )
        elif next_urls:
            raise CatalogValidationError("catalog crawl ended while a next page remained")
    seen: set[str] = set()
    duplicate_urls: list[str] = []
    raw_count = 0
    for page in ordered:
        for card in page.discovery.tickets:
            raw_count += 1
            if card.detail_url in seen and card.detail_url not in duplicate_urls:
                duplicate_urls.append(card.detail_url)
            seen.add(card.detail_url)
    return CatalogCountCheck(
        source_total=expected_total,
        unique_count=len(cards),
        raw_count=raw_count,
        duplicate_urls=duplicate_urls,
    )


def _mapping_indexes(
    session: Session,
) -> tuple[dict[str, Game], dict[tuple[str, Decimal], list[Game]]]:
    by_url: dict[str, Game] = {}
    by_name_price: dict[tuple[str, Decimal], list[Game]] = {}
    for game in session.scalars(select(Game)):
        if game.source_url:
            by_url[game.source_url.rstrip("/")] = game
        if game.ticket_price is not None:
            key = (normalize_catalog_name(game.name), game.ticket_price)
            by_name_price.setdefault(key, []).append(game)
    return by_url, by_name_price


def persist_catalog_run(
    session: Session,
    pages: list[CatalogPageCapture],
) -> CatalogPersistResult:
    cards = _unique_cards(pages)
    count_check = _validate_catalog_pages(pages, cards)
    manifest_sha256 = catalog_manifest_sha256(pages)
    observed_at = max(page.collection.captured_at for page in pages).astimezone(UTC)
    source_date = chicago_source_date(observed_at)
    previous_run = _previous_catalog_run(session, observed_at)
    previous_snapshots = previous_run.catalog_snapshots if previous_run else []
    previous_entries = _catalog_entry_names(session, previous_snapshots)
    current_urls = {card.detail_url for _, _, card in cards}
    missing_since_previous = sorted(
        url for url in previous_entries if url not in current_urls
    )
    new_since_previous = (
        sorted(url for url in current_urls if url not in previous_entries)
        if previous_entries
        else []
    )
    comparison = {
        "source_total": count_check.source_total,
        "duplicate_urls": count_check.duplicate_urls,
        "missing_since_previous": missing_since_previous,
        "new_since_previous": new_since_previous,
    }
    existing = session.scalar(
        select(ScrapeRun).where(
            ScrapeRun.workflow == "instant_ticket_catalog",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_sha256 == manifest_sha256,
            ScrapeRun.source_date == source_date,
        )
    )
    if existing is not None:
        mapped = sum(1 for entry in existing.catalog_snapshots if entry.game_id is not None)
        ambiguous = session.scalar(
            select(func.count())
            .select_from(CatalogQualityIssue)
            .where(
                CatalogQualityIssue.scrape_run_id == existing.id,
                CatalogQualityIssue.code == "AMBIGUOUS_CATALOG_MAPPING",
                CatalogQualityIssue.resolved_at.is_(None),
            )
        ) or 0
        return CatalogPersistResult(
            scrape_run_id=existing.id,
            created=False,
            page_count=len(pages),
            unique_entry_count=len(existing.catalog_snapshots),
            mapped_count=mapped,
            unmapped_count=len(existing.catalog_snapshots) - mapped,
            ambiguous_count=ambiguous,
            manifest_sha256=manifest_sha256,
            **comparison,
        )

    run = ScrapeRun(
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        workflow="instant_ticket_catalog",
        source_url=HUB_URL,
        source_observed_at=observed_at,
        source_date=source_date,
        source_sha256=manifest_sha256,
        is_complete=False,
        parsed_game_count=len(cards),
        parsed_prize_tier_count=0,
        pipeline_version=CATALOG_PIPELINE_VERSION,
    )
    session.add(run)
    session.flush()
    for page in pages:
        collection = page.collection
        session.add(
            RawSourceSnapshot(
                scrape_run=run,
                source_url=collection.source_url,
                content_type=collection.content_type,
                file_path=collection.file_path,
                sha256=collection.sha256,
                captured_at=collection.captured_at,
            )
        )

    by_url, by_name_price = _mapping_indexes(session)
    mapped_count = 0
    ambiguous_count = 0
    mapped_cards: list[tuple[DiscoveredInstantTicket, Game]] = []
    for page_number, position, card in cards:
        mapped_game = by_url.get(card.detail_url.rstrip("/"))
        candidates = (
            by_name_price.get(
                (normalize_catalog_name(card.display_name or ""), Decimal(card.ticket_price)),
                [],
            )
            if mapped_game is None
            else []
        )
        if len(candidates) > 1:
            ambiguous_count += 1
        if mapped_game is not None:
            mapped_count += 1
            mapped_cards.append((card, mapped_game))
        snapshot = GameCatalogSnapshot(
            scrape_run=run,
            game_id=mapped_game.id if mapped_game else None,
            detail_url=card.detail_url,
            slug=card.slug,
            display_name=card.display_name or "",
            ticket_price=Decimal(card.ticket_price),
            top_prize_text=card.top_prize_text,
            page_number=page_number,
            card_position=position,
        )
        session.add(snapshot)
        session.flush()
        if mapped_game is None:
            if len(candidates) > 1:
                code = "AMBIGUOUS_CATALOG_MAPPING"
            elif len(candidates) == 1:
                code = "UNKNOWN_URL_REQUIRES_VERIFICATION"
            else:
                code = "UNMAPPED_CATALOG_CARD"
            session.add(
                CatalogQualityIssue(
                    scrape_run_id=run.id,
                    catalog_snapshot_id=snapshot.id,
                    code=code,
                    severity="warning",
                    detail_url=card.detail_url,
                    details={"candidate_game_ids": [candidate.id for candidate in candidates]},
                )
            )
    if count_check.mismatch or count_check.duplicate_urls:
        session.add(
            CatalogQualityIssue(
                scrape_run_id=run.id,
                code=(
                    "CATALOG_COUNT_MISMATCH"
                    if count_check.mismatch
                    else "CATALOG_DUPLICATE_CARDS"
                ),
                severity="warning" if count_check.mismatch else "info",
                details={
                    "summary": (
                        f"{count_check.unique_count} unique catalog cards "
                        f"({count_check.raw_count} raw) against a source total of "
                        f"{count_check.source_total}; repeated: "
                        f"{', '.join(count_check.duplicate_urls) or 'none'}"
                    ),
                    "unique_count": count_check.unique_count,
                    "raw_count": count_check.raw_count,
                    **comparison,
                    "missing_names": {
                        url: previous_entries[url] for url in missing_since_previous
                    },
                },
            )
        )
    for issue in _game_identity_issues(
        session,
        run_id=run.id,
        source_date=source_date,
        mapped_cards=mapped_cards,
        previous_snapshots=previous_snapshots,
    ):
        session.add(issue)
    run.is_complete = True
    session.flush()
    return CatalogPersistResult(
        scrape_run_id=run.id,
        created=True,
        page_count=len(pages),
        unique_entry_count=len(cards),
        mapped_count=mapped_count,
        unmapped_count=len(cards) - mapped_count,
        ambiguous_count=ambiguous_count,
        manifest_sha256=manifest_sha256,
        **comparison,
    )


def _previous_catalog_run(session: Session, observed_at: datetime) -> ScrapeRun | None:
    """Return the latest complete catalog run observed before this one."""
    return session.scalar(
        select(ScrapeRun)
        .where(
            ScrapeRun.workflow == "instant_ticket_catalog",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_observed_at < observed_at,
        )
        .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )


def _catalog_entry_names(
    session: Session, snapshots: list[GameCatalogSnapshot]
) -> dict[str, str]:
    """Return detail URL -> name, preferring the mapped game's name.

    Card display names can be image alt text, so they are only a fallback.
    """
    game_ids = [entry.game_id for entry in snapshots if entry.game_id is not None]
    names = (
        {game.id: game.name for game in session.scalars(select(Game).where(Game.id.in_(game_ids)))}
        if game_ids
        else {}
    )
    return {entry.detail_url: names.get(entry.game_id, entry.display_name) for entry in snapshots}


def _game_identity_issues(
    session: Session,
    *,
    run_id: int,
    source_date: date,
    mapped_cards: list[tuple[DiscoveredInstantTicket, Game]],
    previous_snapshots: list[GameCatalogSnapshot],
) -> list[CatalogQualityIssue]:
    """Check mapped cards by game number rather than by URL or page position."""
    issues: list[CatalogQualityIssue] = []

    def issue(code: str, game: Game, summary: str, **details) -> None:
        issues.append(
            CatalogQualityIssue(
                scrape_run_id=run_id,
                code=code,
                severity="warning",
                detail_url=game.source_url,
                details={
                    "game_number": game.game_number,
                    "name": game.name,
                    "summary": summary,
                    **details,
                },
            )
        )

    cards_by_game: dict[int, list[DiscoveredInstantTicket]] = {}
    games: dict[int, Game] = {}
    for card, game in mapped_cards:
        cards_by_game.setdefault(game.id, []).append(card)
        games[game.id] = game
    previous_names = {
        entry.game_id: entry.display_name
        for entry in previous_snapshots
        if entry.game_id is not None
    }

    for game_id, game_cards in cards_by_game.items():
        game = games[game_id]
        for card in game_cards:
            if game.ticket_price is not None and Decimal(card.ticket_price) != game.ticket_price:
                issue(
                    "CATALOG_PRICE_MISMATCH",
                    game,
                    f"catalog price ${card.ticket_price} differs from recorded "
                    f"${game.ticket_price}",
                    catalog_price=card.ticket_price,
                    recorded_price=str(game.ticket_price),
                )
            card_name = card.display_name or ""
            # Some card names differ cosmetically from the recorded name every day;
            # only report a mismatch when the card's name is new since the last run.
            if normalize_catalog_name(card_name) != normalize_catalog_name(
                game.name
            ) and previous_names.get(game_id) != card_name:
                issue(
                    "CATALOG_NAME_MISMATCH",
                    game,
                    f"catalog name {card_name!r} differs from recorded {game.name!r}",
                    catalog_name=card_name,
                    previous_catalog_name=previous_names.get(game_id),
                )

    prize_run_id = session.scalar(
        select(ScrapeRun.id)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_date == source_date,
        )
        .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )
    if prize_run_id is not None:
        prize_game_ids = set(
            session.scalars(
                select(GameSnapshot.game_id).where(GameSnapshot.scrape_run_id == prize_run_id)
            )
        )
        for game_id in sorted(set(previous_names) - set(cards_by_game)):
            if game_id not in prize_game_ids:
                continue
            game = session.get(Game, game_id)
            issue(
                "CATALOG_GAME_MISSING",
                game,
                f"game {game.game_number} was in the previous catalog and is still in "
                "the prize data, but is missing from this catalog",
            )
    return issues


def record_duplicate_game_numbers(
    session: Session,
    scrape_run_id: int,
    detail_game_numbers: dict[str, str | None],
) -> int:
    """Record catalog cards whose detail pages report the same game number.

    ``detail_game_numbers`` maps detail URL -> the game number its detail page states.
    URLs alone are not a reliable identity: the hub can link one game from two cards.
    """
    urls_by_number: dict[str, list[str]] = {}
    for snapshot in session.scalars(
        select(GameCatalogSnapshot).where(GameCatalogSnapshot.scrape_run_id == scrape_run_id)
    ):
        number = detail_game_numbers.get(snapshot.detail_url.rstrip("/"))
        if number:
            urls_by_number.setdefault(number, []).append(snapshot.detail_url)
    recorded = 0
    for number, urls in sorted(urls_by_number.items()):
        if len(urls) < 2:
            continue
        game = session.scalar(select(Game).where(Game.game_number == number))
        session.add(
            CatalogQualityIssue(
                scrape_run_id=scrape_run_id,
                code="CATALOG_DUPLICATE_GAME",
                severity="warning",
                details={
                    "game_number": number,
                    "name": game.name if game else None,
                    "summary": f"{len(urls)} catalog cards link to game {number}",
                    "detail_urls": sorted(urls),
                },
            )
        )
        recorded += 1
    session.flush()
    return recorded


def reconcile_catalog_run_mappings(session: Session, scrape_run_id: int) -> int:
    """Resolve previously unknown cards only after a verified detail URL is stored."""
    by_url = {
        game.source_url.rstrip("/"): game
        for game in session.scalars(select(Game).where(Game.source_url.is_not(None)))
        if game.source_url
    }
    snapshots = session.scalars(
        select(GameCatalogSnapshot).where(
            GameCatalogSnapshot.scrape_run_id == scrape_run_id,
            GameCatalogSnapshot.game_id.is_(None),
        )
    ).all()
    resolved = 0
    for snapshot in snapshots:
        game = by_url.get(snapshot.detail_url.rstrip("/"))
        if game is None:
            continue
        snapshot.game_id = game.id
        for issue in session.scalars(
            select(CatalogQualityIssue).where(
                CatalogQualityIssue.catalog_snapshot_id == snapshot.id,
                CatalogQualityIssue.resolved_at.is_(None),
            )
        ):
            issue.resolved_at = datetime.now(UTC)
            issue.resolved_game_id = game.id
        resolved += 1
    session.flush()
    return resolved
