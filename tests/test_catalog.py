"""Catalog normalization and one-run persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.catalog import (
    CATALOG_COUNT_TOLERANCE,
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


def test_catalog_run_rejects_card_count_beyond_tolerance(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path)
        for _ in range(CATALOG_COUNT_TOLERANCE + 1):
            pages[-1].discovery.tickets.pop()
        with pytest.raises(CatalogValidationError, match="does not match source total"):
            persist_catalog_run(session, pages)
        assert session.scalar(select(ScrapeRun)) is None


def test_catalog_run_rejects_short_page_before_the_last(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path)
        pages[1].discovery.tickets.pop()
        with pytest.raises(CatalogValidationError, match="expected a full page"):
            persist_catalog_run(session, pages)
        assert session.scalar(select(ScrapeRun)) is None


@pytest.mark.parametrize("total_count", [52, 54, 56])
def test_catalog_run_publishes_small_count_mismatch_with_warning(
    tmp_path: Path, total_count: int
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path, total_count=total_count)

        result = persist_catalog_run(session, pages)

        assert result.created is True
        assert result.unique_entry_count == 53
        assert result.source_total == total_count
        issue = session.scalar(
            select(CatalogQualityIssue).where(
                CatalogQualityIssue.code == "CATALOG_COUNT_MISMATCH"
            )
        )
        assert issue is not None
        assert issue.severity == "warning"
        assert issue.details["source_total"] == total_count
        assert issue.details["unique_count"] == 53


def test_catalog_run_records_card_repeated_across_page_boundary(tmp_path: Path):
    # Reproduces 2026-10-22: the hub repeated page 2's last card as page 3's first
    # card, so 53 slots held 52 unique games against a stated total of 53.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path)
        repeated = pages[1].discovery.tickets[-1]
        pages[2].discovery.tickets[0] = repeated

        result = persist_catalog_run(session, pages)

        assert result.unique_entry_count == 52
        assert result.duplicate_urls == [repeated.detail_url]
        issue = session.scalar(
            select(CatalogQualityIssue).where(
                CatalogQualityIssue.code == "CATALOG_COUNT_MISMATCH"
            )
        )
        assert issue.details["raw_count"] == 53
        assert issue.details["duplicate_urls"] == [repeated.detail_url]


def test_catalog_run_records_duplicates_even_when_count_matches(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pages = _catalog_pages(tmp_path, total_count=52)
        pages[2].discovery.tickets[0] = pages[1].discovery.tickets[-1]

        persist_catalog_run(session, pages)

        issue = session.scalar(
            select(CatalogQualityIssue).where(
                CatalogQualityIssue.code == "CATALOG_DUPLICATE_CARDS"
            )
        )
        assert issue is not None
        assert issue.severity == "info"


def test_catalog_run_names_games_missing_since_previous_run(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = persist_catalog_run(session, _catalog_pages(tmp_path))
        pages = _catalog_pages(
            tmp_path, captured_at=datetime(2026, 8, 9, 12, tzinfo=UTC)
        )
        dropped = pages[-1].discovery.tickets.pop()

        result = persist_catalog_run(session, pages)

        assert first.missing_since_previous == []
        assert result.missing_since_previous == [dropped.detail_url]
        assert result.new_since_previous == []
        issue = session.scalar(
            select(CatalogQualityIssue).where(
                CatalogQualityIssue.scrape_run_id == result.scrape_run_id,
                CatalogQualityIssue.code == "CATALOG_COUNT_MISMATCH",
            )
        )
        assert issue.details["missing_names"] == {
            dropped.detail_url: dropped.display_name
        }


def _catalog_pages(
    tmp_path: Path,
    *,
    captured_at: datetime = datetime(2026, 8, 8, 12, tzinfo=UTC),
    total_count: int = 53,
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
                    total_count=total_count,
                    warnings=[],
                ),
            )
        )
    return pages
