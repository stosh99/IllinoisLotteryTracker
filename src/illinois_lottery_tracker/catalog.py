"""Collect, normalize, map, and persist instant-ticket retail catalog runs."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
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


class CatalogValidationError(ValueError):
    """Raised when a catalog crawl cannot be published as complete."""


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
    cards = _unique_cards(captures)
    _validate_catalog_pages(captures, cards)
    return captures


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
) -> None:
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
    if expected_total != len(cards):
        raise CatalogValidationError(
            f"catalog unique-card count {len(cards)} does not match source total "
            f"{expected_total}"
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
    _validate_catalog_pages(pages, cards)
    manifest_sha256 = catalog_manifest_sha256(pages)
    observed_at = max(page.collection.captured_at for page in pages).astimezone(UTC)
    source_date = chicago_source_date(observed_at)
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
    )


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
