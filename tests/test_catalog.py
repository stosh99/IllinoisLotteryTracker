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
    record_duplicate_game_numbers,
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
    GameSnapshot,
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


def _seed_catalog_games(session: Session) -> dict[int, Game]:
    games = {
        index: Game(
            game_number=str(9000 + index),
            name=f"Catalog Game {index}",
            ticket_price=index if index <= 30 else 30,
            source_url=f"https://example.test/game-{index}",
        )
        for index in range(1, 54)
    }
    session.add_all(games.values())
    session.flush()
    return games


def _seed_prize_run(session: Session, games: list[Game], *, source_date) -> None:
    run = ScrapeRun(
        started_at=datetime(2026, 8, 9, 11, tzinfo=UTC),
        status="success",
        workflow="unpaid_prizes",
        source_observed_at=datetime(2026, 8, 9, 11, tzinfo=UTC),
        source_date=source_date,
        source_sha256="f" * 64,
        parsed_game_count=len(games),
        parsed_prize_tier_count=len(games),
        is_complete=True,
    )
    session.add(run)
    session.flush()
    session.add_all(GameSnapshot(game_id=game.id, scrape_run_id=run.id) for game in games)
    session.flush()


def _issues(session: Session, run_id: int, code: str) -> list[CatalogQualityIssue]:
    return session.scalars(
        select(CatalogQualityIssue).where(
            CatalogQualityIssue.scrape_run_id == run_id,
            CatalogQualityIssue.code == code,
        )
    ).all()


def test_catalog_run_flags_game_missing_that_is_still_in_prize_data(tmp_path: Path):
    # Reproduces 2026-10-22: Monopoly vanished from the catalog for a morning while
    # it still had unclaimed prizes, then returned the same afternoon.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        games = _seed_catalog_games(session)
        persist_catalog_run(session, _catalog_pages(tmp_path))
        next_day = datetime(2026, 8, 9, 12, tzinfo=UTC)
        # Game 53 is still in the prize data; game 52 has left it (retired).
        _seed_prize_run(
            session,
            [game for index, game in games.items() if index != 52],
            source_date=next_day.date(),
        )
        pages = _catalog_pages(tmp_path, captured_at=next_day)
        pages[-1].discovery.tickets.pop()
        pages[-1].discovery.tickets.pop()

        result = persist_catalog_run(session, pages)

        missing = _issues(session, result.scrape_run_id, "CATALOG_GAME_MISSING")
        assert [issue.details["game_number"] for issue in missing] == ["9053"]
        assert missing[0].details["name"] == "Catalog Game 53"
        assert missing[0].severity == "warning"


def test_catalog_run_flags_price_mismatch_against_recorded_game(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        games = _seed_catalog_games(session)
        games[5].ticket_price = 10
        session.flush()

        result = persist_catalog_run(session, _catalog_pages(tmp_path))

        mismatches = _issues(session, result.scrape_run_id, "CATALOG_PRICE_MISMATCH")
        assert [issue.details["game_number"] for issue in mismatches] == ["9005"]
        assert mismatches[0].details["catalog_price"] == 5


def test_catalog_run_flags_name_mismatch_only_when_card_name_changes(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        games = _seed_catalog_games(session)
        # A permanent cosmetic difference, like "Gold Casino" vs "Golden Casino".
        games[7].name = "Golden Game 7"
        session.flush()
        first = persist_catalog_run(session, _catalog_pages(tmp_path))
        same = persist_catalog_run(
            session,
            _catalog_pages(tmp_path, captured_at=datetime(2026, 8, 9, 12, tzinfo=UTC)),
        )
        changed_pages = _catalog_pages(
            tmp_path, captured_at=datetime(2026, 8, 10, 12, tzinfo=UTC)
        )
        changed_pages[0].discovery.tickets[6] = DiscoveredInstantTicket(
            detail_url="https://example.test/game-7",
            slug="game-7",
            display_name="Renamed Game 7",
            ticket_price=7,
        )
        changed = persist_catalog_run(session, changed_pages)

        assert len(_issues(session, first.scrape_run_id, "CATALOG_NAME_MISMATCH")) == 1
        assert _issues(session, same.scrape_run_id, "CATALOG_NAME_MISMATCH") == []
        renamed = _issues(session, changed.scrape_run_id, "CATALOG_NAME_MISMATCH")
        assert renamed[0].details["catalog_name"] == "Renamed Game 7"
        assert renamed[0].details["previous_catalog_name"] == "Catalog Game 7"


def test_duplicate_game_numbers_across_detail_pages_are_recorded(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_catalog_games(session)
        result = persist_catalog_run(session, _catalog_pages(tmp_path))
        numbers = {
            f"https://example.test/game-{index}": str(9000 + index) for index in range(1, 54)
        }
        numbers["https://example.test/game-41"] = "9040"

        recorded = record_duplicate_game_numbers(session, result.scrape_run_id, numbers)

        duplicates = _issues(session, result.scrape_run_id, "CATALOG_DUPLICATE_GAME")
        assert recorded == 1
        assert duplicates[0].details["game_number"] == "9040"
        assert duplicates[0].details["detail_urls"] == [
            "https://example.test/game-40",
            "https://example.test/game-41",
        ]
