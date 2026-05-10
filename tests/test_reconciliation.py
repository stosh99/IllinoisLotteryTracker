"""Tests for illinois_lottery_tracker.reconciliation.

All tests use an in-memory SQLite database seeded with minimal fixture data.
No network access. No filesystem access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.importer import (
    import_instant_ticket_detail_metadata,
    import_unpaid_prizes_parse_result,
)
from illinois_lottery_tracker.instant_ticket_detail_parser import ParsedInstantTicketDetail
from illinois_lottery_tracker.models import Base, Game, GameSnapshot, ScrapeRun
from illinois_lottery_tracker.parser import ParsedGame, ParsedPrizeTier, ParseResult
from illinois_lottery_tracker.reconciliation import (
    GameReconciliationRow,
    NameMismatchRow,
    PriceMismatchRow,
    ReconciliationReport,
    reconcile,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


def _scrape_run(session: Session) -> ScrapeRun:
    run = ScrapeRun(
        started_at=datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 8, 12, 1, tzinfo=UTC),
        status="success",
        source_url="https://example.test/unpaid",
        raw_file_path="/tmp/unpaid.html",
    )
    session.add(run)
    session.flush()
    return run


def _unpaid_game(
    *,
    game_number: str = "1001",
    name: str = "TEST GAME",
    ticket_price: int = 5,
) -> ParsedGame:
    return ParsedGame(
        game_name=name,
        display_name=f"{name} (${ticket_price})",
        ticket_price=ticket_price,
        data_price=ticket_price,
        game_number=game_number,
        weeks_in_market=4,
        prize_tiers=[
            ParsedPrizeTier(prize_amount=5, total_prizes=100, unclaimed_prizes=80),
        ],
    )


def _detail(
    *,
    game_number: str | None = "1001",
    name: str | None = "Test Game",
    ticket_price: int | None = 5,
    source_url: str | None = "https://www.illinoislottery.com/games-hub/instant-tickets/test-game",
    overall_odds: Decimal = Decimal("4.97"),
    launch_date_year: int = 2026,
) -> ParsedInstantTicketDetail:
    from datetime import date

    return ParsedInstantTicketDetail(
        source_url=source_url,
        detail_slug="test-game",
        game_name=name,
        display_name=name,
        game_number=game_number,
        ticket_price=ticket_price,
        overall_odds=overall_odds,
        overall_odds_text=f"1 in {overall_odds}",
        category="Test",
        play_style="Match",
        launch_date=date(launch_date_year, 3, 1),
        top_prize_text="$50,000",
        image_url=None,
        play_instructions=None,
        consolidated_odds_present=False,
        raw_fields={},
        warnings=[],
    )


def _seed_matched_game(session: Session) -> Game:
    """Create a game that has both unpaid snapshot and detail metadata."""
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(session, ParseResult(games=[_unpaid_game()]), scrape_run=run)
    import_instant_ticket_detail_metadata(session, [_detail()])
    session.flush()
    return session.scalar(select(Game).where(Game.game_number == "1001"))


def _seed_unpaid_only_game(session: Session) -> Game:
    """Create a game that has only unpaid-prizes snapshot data."""
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(
        session,
        ParseResult(games=[_unpaid_game(game_number="2001", name="UNPAID ONLY")]),
        scrape_run=run,
    )
    session.flush()
    return session.scalar(select(Game).where(Game.game_number == "2001"))


def _seed_detail_only_game(session: Session) -> Game:
    """Create a game that has only detail metadata (no snapshots)."""
    import_instant_ticket_detail_metadata(
        session,
        [_detail(game_number="3001", name="Detail Only")],
    )
    session.flush()
    return session.scalar(select(Game).where(Game.game_number == "3001"))


# ---------------------------------------------------------------------------
# Return-type sanity
# ---------------------------------------------------------------------------

def test_reconcile_returns_report_type(session: Session):
    report = reconcile(session=session)
    assert isinstance(report, ReconciliationReport)


def test_empty_db_produces_zero_counts(session: Session):
    report = reconcile(session=session)
    assert report.total_games == 0
    assert report.games_with_unpaid_snapshot == 0
    assert report.games_with_detail_metadata == 0
    assert report.games_matched == 0
    assert report.unpaid_only_count == 0
    assert report.detail_only_count == 0
    assert report.all_rows == []


# ---------------------------------------------------------------------------
# Clean match
# ---------------------------------------------------------------------------

def test_clean_match_counted_correctly(session: Session):
    _seed_matched_game(session)
    report = reconcile(session=session)

    assert report.total_games == 1
    assert report.games_matched == 1
    assert report.unpaid_only_count == 0
    assert report.detail_only_count == 0


def test_clean_match_row_flags(session: Session):
    _seed_matched_game(session)
    report = reconcile(session=session)

    row = report.all_rows[0]
    assert isinstance(row, GameReconciliationRow)
    assert row.game_number == "1001"
    assert row.has_unpaid_snapshot is True
    assert row.has_detail_metadata is True


def test_clean_match_no_mismatch_rows(session: Session):
    _seed_matched_game(session)
    detail = _detail()
    report = reconcile(session=session, detail_inputs=[detail])

    assert report.price_mismatch_count == 0
    assert report.name_mismatch_count == 0
    assert report.price_mismatches == []
    assert report.name_mismatches == []


# ---------------------------------------------------------------------------
# Unpaid-prizes only
# ---------------------------------------------------------------------------

def test_unpaid_only_counted_correctly(session: Session):
    _seed_unpaid_only_game(session)
    report = reconcile(session=session)

    assert report.total_games == 1
    assert report.games_with_unpaid_snapshot == 1
    assert report.games_with_detail_metadata == 0
    assert report.unpaid_only_count == 1
    assert report.detail_only_count == 0
    assert len(report.unpaid_only) == 1


def test_unpaid_only_row_flags(session: Session):
    _seed_unpaid_only_game(session)
    report = reconcile(session=session)

    row = report.unpaid_only[0]
    assert row.game_number == "2001"
    assert row.has_unpaid_snapshot is True
    assert row.has_detail_metadata is False


# ---------------------------------------------------------------------------
# Detail-metadata only
# ---------------------------------------------------------------------------

def test_detail_only_counted_correctly(session: Session):
    _seed_detail_only_game(session)
    report = reconcile(session=session)

    assert report.total_games == 1
    assert report.games_with_unpaid_snapshot == 0
    assert report.games_with_detail_metadata == 1
    assert report.unpaid_only_count == 0
    assert report.detail_only_count == 1
    assert len(report.detail_only) == 1


def test_detail_only_row_flags(session: Session):
    _seed_detail_only_game(session)
    report = reconcile(session=session)

    row = report.detail_only[0]
    assert row.game_number == "3001"
    assert row.has_unpaid_snapshot is False
    assert row.has_detail_metadata is True


def test_detail_only_not_yet_imported_appears_when_detail_inputs_given(session: Session):
    """A game in detail_inputs with no DB row at all is reported as detail-only."""
    fresh_detail = _detail(game_number="9001", name="Not Imported Yet")
    report = reconcile(session=session, detail_inputs=[fresh_detail])

    assert report.total_games == 1
    assert report.detail_only_count == 1
    assert report.detail_only[0].game_number == "9001"
    assert report.detail_only[0].has_detail_metadata is True
    assert report.detail_only[0].has_unpaid_snapshot is False


# ---------------------------------------------------------------------------
# Price mismatch
# ---------------------------------------------------------------------------

def test_price_mismatch_detected_with_detail_inputs(session: Session):
    _seed_unpaid_only_game(session)  # game 2001, price $5 in DB
    mismatched = _detail(game_number="2001", name="UNPAID ONLY", ticket_price=10)

    report = reconcile(session=session, detail_inputs=[mismatched])

    assert report.price_mismatch_count == 1
    mismatch = report.price_mismatches[0]
    assert isinstance(mismatch, PriceMismatchRow)
    assert mismatch.game_number == "2001"
    assert mismatch.db_price == Decimal("5.00")
    assert mismatch.detail_price == Decimal("10")


def test_price_mismatch_not_detected_without_detail_inputs(session: Session):
    _seed_unpaid_only_game(session)
    report = reconcile(session=session)

    assert report.price_mismatch_count == 0
    assert report.price_mismatches == []


def test_price_mismatch_zero_when_prices_match(session: Session):
    _seed_matched_game(session)
    matching_detail = _detail(game_number="1001", ticket_price=5)
    report = reconcile(session=session, detail_inputs=[matching_detail])

    assert report.price_mismatch_count == 0


# ---------------------------------------------------------------------------
# Name / display-name mismatch
# ---------------------------------------------------------------------------

def test_name_mismatch_detected_with_detail_inputs(session: Session):
    _seed_matched_game(session)
    # Importer resolved name to "Test Game" (from detail import).
    # Supply a different name in fresh detail inputs.
    different_name_detail = _detail(game_number="1001", name="DIFFERENT NAME")

    report = reconcile(session=session, detail_inputs=[different_name_detail])

    assert report.name_mismatch_count == 1
    mismatch = report.name_mismatches[0]
    assert isinstance(mismatch, NameMismatchRow)
    assert mismatch.game_number == "1001"
    assert mismatch.detail_name == "DIFFERENT NAME"


def test_name_mismatch_not_detected_without_detail_inputs(session: Session):
    _seed_matched_game(session)
    report = reconcile(session=session)

    assert report.name_mismatch_count == 0
    assert report.name_mismatches == []


def test_name_mismatch_zero_when_names_match(session: Session):
    _seed_matched_game(session)
    game = session.scalar(select(Game).where(Game.game_number == "1001"))
    same_name_detail = _detail(game_number="1001", name=game.name)

    report = reconcile(session=session, detail_inputs=[same_name_detail])

    assert report.name_mismatch_count == 0


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------

def test_missing_overall_odds_detected(session: Session):
    game = Game(game_number="4001", name="No Odds Game", is_active=True)
    session.add(game)
    session.flush()

    report = reconcile(session=session)

    assert report.missing_overall_odds_count == 1
    assert report.missing_odds[0].game_number == "4001"


def test_missing_launch_date_detected(session: Session):
    game = Game(game_number="5001", name="No Date Game", is_active=True)
    session.add(game)
    session.flush()

    report = reconcile(session=session)

    assert report.missing_launch_date_count == 1
    assert report.missing_dates[0].game_number == "5001"


def test_no_missing_fields_when_fully_populated(session: Session):
    _seed_matched_game(session)
    report = reconcile(session=session)

    assert report.missing_overall_odds_count == 0
    assert report.missing_launch_date_count == 0
    assert report.missing_odds == []
    assert report.missing_dates == []


# ---------------------------------------------------------------------------
# Duplicate game_numbers in detail inputs
# ---------------------------------------------------------------------------

def test_duplicate_game_numbers_in_detail_inputs_detected(session: Session):
    dup1 = _detail(game_number="6001", name="Game A")
    dup2 = _detail(game_number="6001", name="Game A Duplicate")

    report = reconcile(session=session, detail_inputs=[dup1, dup2])

    assert report.duplicate_game_numbers_in_details == 1
    assert "6001" in report.duplicate_game_numbers


def test_no_duplicates_when_all_unique(session: Session):
    d1 = _detail(game_number="7001", name="Alpha")
    d2 = _detail(game_number="7002", name="Beta")

    report = reconcile(session=session, detail_inputs=[d1, d2])

    assert report.duplicate_game_numbers_in_details == 0
    assert report.duplicate_game_numbers == []


# ---------------------------------------------------------------------------
# Summary count accuracy with multiple games
# ---------------------------------------------------------------------------

def test_summary_counts_with_mixed_population(session: Session):
    _seed_matched_game(session)       # 1001: both
    _seed_unpaid_only_game(session)   # 2001: unpaid only
    _seed_detail_only_game(session)   # 3001: detail only

    report = reconcile(session=session)

    assert report.total_games == 3
    assert report.games_matched == 1
    assert report.unpaid_only_count == 1
    assert report.detail_only_count == 1
    assert report.games_with_unpaid_snapshot == 2  # 1001 + 2001
    assert report.games_with_detail_metadata == 2  # 1001 + 3001


# ---------------------------------------------------------------------------
# Read-only guarantee — no DB mutations
# ---------------------------------------------------------------------------

def test_reconcile_does_not_mutate_session(session: Session):
    _seed_matched_game(session)
    game_count_before = session.scalar(select(func.count()).select_from(Game))
    snapshot_count_before = session.scalar(select(func.count()).select_from(GameSnapshot))

    reconcile(session=session)

    # No new or modified objects should be pending
    assert len(session.new) == 0
    assert len(session.dirty) == 0
    assert len(session.deleted) == 0

    game_count_after = session.scalar(select(func.count()).select_from(Game))
    snapshot_count_after = session.scalar(select(func.count()).select_from(GameSnapshot))
    assert game_count_after == game_count_before
    assert snapshot_count_after == snapshot_count_before


def test_reconcile_with_detail_inputs_does_not_mutate_session(session: Session):
    _seed_matched_game(session)
    detail_inputs = [_detail(game_number="1001", ticket_price=99, name="Different")]

    reconcile(session=session, detail_inputs=detail_inputs)

    assert len(session.new) == 0
    assert len(session.dirty) == 0
    assert len(session.deleted) == 0

    game = session.scalar(select(Game).where(Game.game_number == "1001"))
    assert game.ticket_price != Decimal("99")


# ---------------------------------------------------------------------------
# Schema limitation note
# ---------------------------------------------------------------------------

def test_schema_note_present_without_detail_inputs(session: Session):
    report = reconcile(session=session)
    assert len(report.schema_notes) > 0
    assert any("detail_inputs" in note for note in report.schema_notes)


def test_no_schema_note_when_detail_inputs_provided(session: Session):
    report = reconcile(session=session, detail_inputs=[])
    assert report.schema_notes == []


# ---------------------------------------------------------------------------
# Hub note is always present
# ---------------------------------------------------------------------------

def test_hub_note_is_always_set(session: Session):
    report = reconcile(session=session)
    assert "jurassic-park" in report.hub_note
    assert "58" in report.hub_note
    assert "57" in report.hub_note
