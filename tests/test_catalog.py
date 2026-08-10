"""Catalog normalization and one-run persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.catalog import (
    CatalogPageCapture,
    CatalogValidationError,
    normalize_catalog_name,
    persist_catalog_run,
)
from illinois_lottery_tracker.instant_ticket_discovery import (
    DiscoveredInstantTicket,
    InstantTicketHubDiscoveryResult,
)
from illinois_lottery_tracker.models import (
    Base,
    CatalogQualityIssue,
    Game,
    GameCatalogSnapshot,
    ScrapeRun,
)
from illinois_lottery_tracker.raw_collector import RawCollectionResult


def test_normalize_catalog_name_handles_unicode_currency_and_punctuation():
    assert normalize_catalog_name("  Lotería™ — $50,000! ") == "loteria 50 000"
    assert normalize_catalog_name("Lucky & Rich") == normalize_catalog_name(
        "LUCKY and RICH"
    )


def test_catalog_run_persists_daily_53_unique_entries_and_maps_known_games(
    tmp_path: Path,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Game(
                game_number="9001",
                name="Catalog Game 1",
                ticket_price=1,
                source_url="https://example.test/game-1",
            )
        )
        session.add(
            Game(game_number="9002", name="Catalog Game 2", ticket_price=2)
        )
        session.flush()
        pages = _catalog_pages(tmp_path)

        result = persist_catalog_run(session, pages)
        repeated = persist_catalog_run(session, pages)
        next_day = persist_catalog_run(
            session,
            _catalog_pages(tmp_path, captured_at=datetime(2026, 8, 9, 12, tzinfo=UTC)),
        )

        assert result.created is True
        assert result.unique_entry_count == 53
        assert result.page_count == 3
        assert result.mapped_count == 1
        assert repeated.created is False
        assert next_day.created is True
        assert next_day.scrape_run_id != result.scrape_run_id
        assert session.scalar(select(ScrapeRun).where(ScrapeRun.id == result.scrape_run_id))
        assert len(session.scalars(select(GameCatalogSnapshot)).all()) == 106
        assert len(session.scalars(select(CatalogQualityIssue)).all()) == 104


def test_catalog_run_rejects_partial_card_count(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path)
        pages[-1].discovery.tickets.pop()
        with pytest.raises(CatalogValidationError, match="does not match source total"):
            persist_catalog_run(session, pages)
        assert session.scalar(select(ScrapeRun)) is None


def _catalog_pages(
    tmp_path: Path,
    *,
    captured_at: datetime = datetime(2026, 8, 8, 12, tzinfo=UTC),
) -> list[CatalogPageCapture]:
    cards = [
        DiscoveredInstantTicket(
            detail_url=f"https://example.test/game-{index}",
            slug=f"game-{index}",
            display_name=f"Catalog Game {index}",
            ticket_price=index if index <= 30 else 30,
        )
        for index in range(1, 54)
    ]
    pages: list[CatalogPageCapture] = []
    for number, start in enumerate((0, 20, 40), start=1):
        path = tmp_path / f"hub-{number}.html"
        path.write_text(f"page {number}", encoding="utf-8")
        page_cards = cards[start : start + 20]
        pages.append(
            CatalogPageCapture(
                page_number=number,
                collection=RawCollectionResult(
                    source_url=f"https://example.test/hub?page={number}",
                    file_path=str(path),
                    sha256=str(number) * 64,
                    captured_at=captured_at.replace(minute=number),
                    content_type="text/html",
                    bytes_written=path.stat().st_size,
                    fetch_method="playwright",
                ),
                discovery=InstantTicketHubDiscoveryResult(
                    source_url=str(path),
                    tickets=page_cards,
                    pagination_urls=(
                        [f"https://example.test/hub?page={number + 1}"]
                        if number < 3
                        else []
                    ),
                    current_page_label=None,
                    total_count=53,
                    warnings=[],
                ),
            )
        )
    return pages
