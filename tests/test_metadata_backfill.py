"""Tests for missing instant-ticket metadata backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.metadata_backfill import (
    backfill_missing_game_metadata,
    find_missing_metadata_games,
    ignored_missing_metadata_game_numbers,
)
from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    MetadataAttempt,
    ScrapeRun,
)
from illinois_lottery_tracker.raw_collector import BatchPageResult, RawCollectionResult


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_url="sqlite+pysqlite:///:memory:", raw_data_dir=str(tmp_path))


def test_find_missing_metadata_has_no_hard_coded_game_exception(session: Session):
    _game_with_snapshot(session, game_number="7661", name="$3 MILLION VAULT")
    _game_with_snapshot(session, game_number="7587", name="$250,000 CROSSWORD")

    missing = find_missing_metadata_games(session)
    ignored = ignored_missing_metadata_game_numbers(session)

    assert [game.game_number for game in missing] == ["7587", "7661"]
    assert ignored == ()


def test_backfill_missing_game_metadata_imports_matching_detail(
    session: Session,
    settings: Settings,
    tmp_path: Path,
):
    _game_with_snapshot(session, game_number="7661", name="$3 MILLION VAULT")

    hub_file = tmp_path / "hub.html"
    hub_file.write_text(
        """
        <html><body>
          <div class="simple-game-card">
            <a aria-label="$3 Million Vault Find out more"
               href="/games-hub/instant-tickets/3-million-vault">More</a>
            <span class="simple-game-card-prize__price">$20</span>
          </div>
          <div class="simple-game-card">
            <a aria-label="Older Game Find out more"
               href="/games-hub/instant-tickets/older-game">More</a>
            <span class="simple-game-card-prize__price">$5</span>
          </div>
          <div class="itg-container__pagination">
            <span class="itg-container__pagination-range">1 - 2</span>
            <span class="itg-container__pagination-of-text">of 2</span>
          </div>
        </body></html>
        """,
        encoding="utf-8",
    )
    detail_files = {
        "https://www.illinoislottery.com/games-hub/instant-tickets/3-million-vault": (
            _detail_file(
                tmp_path,
                "3-million-vault",
                name="$3 MILLION VAULT",
                game_number="7661",
                price=20,
                odds="1 in 3.12",
                launch_date="May 20, 2026",
            )
        ),
        "https://www.illinoislottery.com/games-hub/instant-tickets/older-game": (
            _detail_file(
                tmp_path,
                "older-game",
                name="OLDER GAME",
                game_number="7000",
                price=5,
                odds="1 in 4.00",
                launch_date="Jan 1, 2025",
            )
        ),
    }

    def fake_collect_raw_snapshot(**_: object) -> RawCollectionResult:
        return RawCollectionResult(
            source_url="https://www.illinoislottery.com/games-hub/instant-tickets",
            file_path=str(hub_file),
            sha256="hub-sha",
            captured_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
            content_type="text/html",
            bytes_written=hub_file.stat().st_size,
            fetch_method="playwright",
        )

    def fake_collect_pages_batch(
        url_prefix_pairs: list[tuple[str, str]],
        **_: object,
    ) -> list[BatchPageResult]:
        results = []
        for url, _prefix in url_prefix_pairs:
            path = detail_files[url]
            results.append(
                BatchPageResult(
                    url=url,
                    file_path=str(path),
                    sha256="detail-sha",
                    captured_at=datetime(2026, 5, 31, 12, 1, tzinfo=UTC),
                    content_type="text/html",
                    bytes_written=path.stat().st_size,
                    fetch_method="playwright",
                    error=None,
                )
            )
        return results

    result = backfill_missing_game_metadata(
        session,
        settings=settings,
        collect_raw_snapshot_fn=fake_collect_raw_snapshot,
        collect_pages_batch_fn=fake_collect_pages_batch,
    )

    game = session.scalar(select(Game).where(Game.game_number == "7661"))
    assert game is not None
    assert result.missing_before == 1
    assert result.ignored_known_missing == ()
    assert result.attempted_games == ("7661",)
    assert result.detail_pages_fetched == 1
    assert result.matching_details == 1
    assert result.games_updated == 1
    assert result.still_missing == ()
    assert game.source_url == (
        "https://www.illinoislottery.com/games-hub/instant-tickets/3-million-vault"
    )
    assert game.launch_date is not None
    assert game.launch_date.isoformat() == "2026-05-20"
    assert game.overall_odds_one_in == Decimal("3.12")


def test_retry_backoff_prevents_premature_second_fetch(
    session: Session,
    settings: Settings,
    tmp_path: Path,
):
    game = _game_with_snapshot(session, game_number="7587", name="$250,000 CROSSWORD")
    now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    session.add(
        MetadataAttempt(
            game_id=game.id,
            attempted_at=now,
            outcome_code="no_candidate",
            attempt_number=1,
            next_retry_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        )
    )
    session.flush()

    def unexpected_collect(**_: object) -> RawCollectionResult:
        raise AssertionError("catalog must not be collected before retry is due")

    result = backfill_missing_game_metadata(
        session,
        settings=settings,
        collect_raw_snapshot_fn=unexpected_collect,
        now=datetime(2026, 8, 8, 18, tzinfo=UTC),
    )

    assert result.attempted_games == ()
    assert result.not_due_games == ("7587",)
    assert session.scalar(select(MetadataAttempt).where(MetadataAttempt.game_id == game.id))


def test_ambiguous_catalog_match_fetches_no_arbitrary_page(
    session: Session,
    settings: Settings,
    tmp_path: Path,
):
    game = _game_with_snapshot(session, game_number="8000", name="LUCKY & RICH")
    hub_file = tmp_path / "ambiguous-hub.html"
    hub_file.write_text(
        """
        <div class="simple-game-card"><a aria-label="Lucky and Rich Find out more"
          href="/games-hub/instant-tickets/lucky-rich-a">More</a>
          <span class="simple-game-card-prize__price">$20</span></div>
        <div class="simple-game-card"><a aria-label="Lucky &amp; Rich Find out more"
          href="/games-hub/instant-tickets/lucky-rich-b">More</a>
          <span class="simple-game-card-prize__price">$20</span></div>
        <div class="itg-container__pagination">
          <span class="itg-container__pagination-range">1 - 2</span>
          <span class="itg-container__pagination-of-text">of 2</span>
        </div>
        """,
        encoding="utf-8",
    )

    def fake_collect(**_: object) -> RawCollectionResult:
        return RawCollectionResult(
            source_url="https://www.illinoislottery.com/games-hub/instant-tickets",
            file_path=str(hub_file),
            sha256="a" * 64,
            captured_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
            content_type="text/html",
            bytes_written=hub_file.stat().st_size,
            fetch_method="playwright",
        )

    def unexpected_batch(*_: object, **__: object) -> list[BatchPageResult]:
        raise AssertionError("ambiguous candidates must not be fetched")

    result = backfill_missing_game_metadata(
        session,
        settings=settings,
        collect_raw_snapshot_fn=fake_collect,
        collect_pages_batch_fn=unexpected_batch,
        now=datetime(2026, 8, 8, 12, tzinfo=UTC),
    )

    attempt = session.scalar(
        select(MetadataAttempt).where(MetadataAttempt.game_id == game.id)
    )
    assert result.ambiguous_games == ("8000",)
    assert result.detail_pages_fetched == 0
    assert attempt is not None
    assert attempt.outcome_code == "ambiguous"
    assert attempt.next_retry_at == datetime(2026, 8, 9, 12)


def _game_with_snapshot(
    session: Session,
    *,
    game_number: str,
    name: str,
) -> Game:
    run = session.scalar(select(ScrapeRun).limit(1))
    if run is None:
        run = ScrapeRun(
            started_at=datetime(2026, 5, 31, 3, 0, tzinfo=UTC),
            finished_at=datetime(2026, 5, 31, 3, 1, tzinfo=UTC),
            status="success",
            source_url="https://example.test/unpaid",
            raw_file_path="/tmp/unpaid.html",
        )
        session.add(run)
        session.flush()

    game = Game(game_number=game_number, name=name, ticket_price=20)
    session.add(game)
    session.flush()
    session.add(
        GameSnapshot(
            game=game,
            scrape_run=run,
            total_original_prize_value=100,
            total_remaining_prize_value=100,
            total_original_winning_tickets=10,
            total_remaining_winning_tickets=10,
        )
    )
    session.flush()
    return game


def _detail_file(
    tmp_path: Path,
    slug: str,
    *,
    name: str,
    game_number: str,
    price: int,
    odds: str,
    launch_date: str,
) -> Path:
    path = tmp_path / f"{slug}.html"
    path.write_text(
        f"""
        <html>
          <head><title>{name} | Instant Ticket | Illinois Lottery</title></head>
          <body>
            <h1 class="cmp-title__text">{name}</h1>
            <div class="itg-details-block">
              <table>
                <tr><td>Price Point</td><td>${price}</td></tr>
                <tr><td>Overall Odds</td><td>{odds}</td></tr>
                <tr><td>Category</td><td>Cash</td></tr>
                <tr><td>Play Style</td><td>Key Number Match</td></tr>
                <tr><td>Launch Date</td><td>{launch_date}</td></tr>
                <tr><td>Game Number</td><td>{game_number}</td></tr>
                <tr><td>Top Prize</td><td>$3,000,000</td></tr>
              </table>
            </div>
            <h3>Consolidated Odds</h3>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    return path
