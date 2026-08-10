"""Tests for importing unpaid-prizes parser output into snapshot tables."""

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
from illinois_lottery_tracker.models import Base, Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun
from illinois_lottery_tracker.parser import (
    ParsedGame,
    ParsedPrizeTier,
    ParseResult,
    ParseWarning,
)


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


def _game(
    *,
    game_number: str = "7647",
    name: str = "EMERALDS",
    ticket_price: int = 1,
    weeks_in_market: int | None = 9,
) -> ParsedGame:
    return ParsedGame(
        game_name=name,
        display_name=f"{name} (${ticket_price})",
        ticket_price=ticket_price,
        data_price=ticket_price,
        game_number=game_number,
        weeks_in_market=weeks_in_market,
        prize_tiers=[
            ParsedPrizeTier(prize_amount=1, total_prizes=100, unclaimed_prizes=75),
            ParsedPrizeTier(prize_amount=5, total_prizes=50, unclaimed_prizes=30),
            ParsedPrizeTier(prize_amount=50_000, total_prizes=2, unclaimed_prizes=1),
        ],
    )


def _detail(
    *,
    game_number: str | None = "7647",
    name: str | None = "Emeralds",
    ticket_price: int | None = 1,
    source_url: str | None = "https://www.illinoislottery.com/games-hub/instant-tickets/emeralds",
) -> ParsedInstantTicketDetail:
    return ParsedInstantTicketDetail(
        source_url=source_url,
        detail_slug="emeralds",
        game_name=name,
        display_name=name,
        game_number=game_number,
        ticket_price=ticket_price,
        overall_odds=Decimal("4.97"),
        overall_odds_text="1 in 4.97",
        category="Gems",
        play_style="Key Number Match",
        launch_date=datetime(2026, 3, 3, tzinfo=UTC).date(),
        top_prize_text="$50,000",
        image_url=None,
        play_instructions=None,
        consolidated_odds_present=True,
        raw_fields={},
        warnings=[],
    )


def test_imports_one_game_with_multiple_prize_tiers(session: Session):
    run = _scrape_run(session)
    parsed = ParseResult(games=[_game()])

    result = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert result.games_seen == 1
    assert result.games_upserted == 1
    assert result.snapshots_inserted == 1
    assert result.prize_tiers_inserted == 3
    assert result.issues == []

    game = session.scalar(select(Game).where(Game.game_number == "7647"))
    assert game is not None
    assert game.name == "EMERALDS"
    assert game.ticket_price == Decimal("1.00")

    snapshot = session.scalar(select(GameSnapshot).where(GameSnapshot.game_id == game.id))
    assert snapshot is not None
    assert snapshot.scrape_run_id == run.id
    assert snapshot.total_original_winning_tickets == 152
    assert snapshot.total_remaining_winning_tickets == 106
    assert snapshot.total_original_prize_value == Decimal("100350.00")
    assert snapshot.total_remaining_prize_value == Decimal("50225.00")
    assert snapshot.top_prizes_original == 2
    assert snapshot.top_prizes_remaining == 1
    assert snapshot.weeks_in_market == 9
    assert snapshot.estimated_ev is None
    assert snapshot.estimated_ev_excluding_top_prize is None

    tiers = session.scalars(
        select(PrizeTierSnapshot)
        .where(PrizeTierSnapshot.game_snapshot_id == snapshot.id)
        .order_by(PrizeTierSnapshot.prize_amount)
    ).all()
    assert [tier.prize_amount for tier in tiers] == [
        Decimal("1.00"),
        Decimal("5.00"),
        Decimal("50000.00"),
    ]
    assert [tier.original_count for tier in tiers] == [100, 50, 2]
    assert [tier.remaining_count for tier in tiers] == [75, 30, 1]
    assert [tier.claimed_count for tier in tiers] == [25, 20, 1]


def test_repeat_import_for_same_scrape_run_skips_existing_snapshot(session: Session):
    run = _scrape_run(session)
    parsed = ParseResult(games=[_game()])

    first = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    second = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert first.snapshots_inserted == 1
    assert second.snapshots_inserted == 0
    assert second.snapshots_skipped_existing == 1
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == 1
    assert session.scalar(select(func.count()).select_from(PrizeTierSnapshot)) == 3


def test_duplicate_game_names_with_different_numbers_create_distinct_games(
    session: Session,
):
    run = _scrape_run(session)
    parsed = ParseResult(
        games=[
            _game(game_number="1001", name="LUCKY", ticket_price=1),
            _game(game_number="2002", name="LUCKY", ticket_price=5),
        ]
    )

    result = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert result.games_upserted == 2
    games = session.scalars(select(Game).order_by(Game.game_number)).all()
    assert [(game.game_number, game.name) for game in games] == [
        ("1001", "LUCKY"),
        ("2002", "LUCKY"),
    ]
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == 2


def test_parser_warnings_are_returned_without_crashing(session: Session):
    run = _scrape_run(session)
    warning = ParseWarning(
        message="prize tier list length mismatch",
        row_index=0,
        game_name="ODD GAME",
    )
    parsed = ParseResult(games=[_game(name="ODD GAME")], warnings=[warning])

    result = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert result.snapshots_inserted == 1
    assert result.parser_warnings == [warning]


def test_game_without_number_is_skipped_and_reported(session: Session):
    run = _scrape_run(session)
    parsed_game = _game()
    parsed_game.game_number = None
    parsed = ParseResult(games=[parsed_game])

    result = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert result.games_seen == 1
    assert result.games_skipped == 1
    assert result.snapshots_inserted == 0
    assert result.issues[0].message == "skipped parsed game without game_number"


def test_missing_weeks_in_market_is_allowed_and_stored_null(session: Session):
    run = _scrape_run(session)
    parsed = ParseResult(games=[_game(weeks_in_market=None)])

    result = import_unpaid_prizes_parse_result(session, parsed, scrape_run=run)
    session.commit()

    assert result.snapshots_inserted == 1
    snapshot = session.scalar(select(GameSnapshot))
    assert snapshot is not None
    assert snapshot.weeks_in_market is None


def test_detail_metadata_updates_existing_game_by_game_number(session: Session):
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(session, ParseResult(games=[_game()]), scrape_run=run)
    snapshot_count = session.scalar(select(func.count()).select_from(GameSnapshot))
    tier_count = session.scalar(select(func.count()).select_from(PrizeTierSnapshot))

    result = import_instant_ticket_detail_metadata(session, [_detail()])
    session.commit()

    assert result.details_seen == 1
    assert result.games_created == 0
    assert result.games_updated == 1
    assert result.details_skipped == 0
    assert any("game_name/display_name mismatch" in i.message for i in result.issues)

    game = session.scalar(select(Game).where(Game.game_number == "7647"))
    assert game is not None
    assert game.name == "Emeralds"
    assert game.source_url == "https://www.illinoislottery.com/games-hub/instant-tickets/emeralds"
    assert game.ticket_price == Decimal("1.00")
    assert game.launch_date == datetime(2026, 3, 3, tzinfo=UTC).date()
    assert game.overall_odds_one_in == Decimal("4.9700")
    assert game.category == "Gems"
    assert game.play_style == "Key Number Match"
    assert game.top_prize_amount == Decimal("50000.00")
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == snapshot_count
    assert session.scalar(select(func.count()).select_from(PrizeTierSnapshot)) == tier_count


def test_detail_metadata_repeat_import_is_idempotent(session: Session):
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(session, ParseResult(games=[_game()]), scrape_run=run)
    first = import_instant_ticket_detail_metadata(session, [_detail()])
    second = import_instant_ticket_detail_metadata(session, [_detail()])
    session.commit()

    assert first.games_updated == 1
    assert second.games_created == 0
    assert second.games_updated == 0
    assert session.scalar(select(func.count()).select_from(Game)) == 1


def test_detail_metadata_identity_conflict_is_skipped_without_mutation(
    session: Session,
):
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(
        session, ParseResult(games=[_game()]), scrape_run=run
    )
    conflicting = _detail(name="Different Game", ticket_price=5)

    result = import_instant_ticket_detail_metadata(session, [conflicting])
    session.flush()

    game = session.scalar(select(Game).where(Game.game_number == "7647"))
    assert game is not None
    assert result.details_skipped == 1
    assert result.games_updated == 0
    assert "identity fields conflict" in result.issues[0].message
    assert game.name == "EMERALDS"
    assert game.ticket_price == Decimal("1.00")
    assert game.source_url is None
    assert game.launch_date is None
    assert game.overall_odds_one_in is None


def test_detail_metadata_missing_game_number_is_skipped_and_reported(
    session: Session,
):
    result = import_instant_ticket_detail_metadata(
        session,
        [_detail(game_number=None)],
    )
    session.commit()

    assert result.details_seen == 1
    assert result.details_skipped == 1
    assert result.games_created == 0
    assert result.issues[0].message == "skipped detail metadata without game_number"
    assert session.scalar(select(func.count()).select_from(Game)) == 0


def test_detail_metadata_duplicate_game_number_is_reported(session: Session):
    result = import_instant_ticket_detail_metadata(
        session,
        [
            _detail(game_number="7647", name="Emeralds"),
            _detail(game_number="7647", name="Emeralds Duplicate"),
        ],
    )
    session.commit()

    assert result.games_created == 1
    assert result.details_skipped == 1
    assert any("duplicate game_number" in issue.message for issue in result.issues)
    assert session.scalar(select(func.count()).select_from(Game)) == 1


def test_detail_metadata_price_mismatch_is_reported_without_overwrite(
    session: Session,
):
    run = _scrape_run(session)
    import_unpaid_prizes_parse_result(session, ParseResult(games=[_game()]), scrape_run=run)

    result = import_instant_ticket_detail_metadata(
        session,
        [_detail(ticket_price=2)],
    )
    session.commit()

    game = session.scalar(select(Game).where(Game.game_number == "7647"))
    assert game is not None
    assert game.ticket_price == Decimal("1.00")
    assert any("ticket_price mismatch" in issue.message for issue in result.issues)


def test_detail_metadata_creates_metadata_only_game_when_missing(session: Session):
    result = import_instant_ticket_detail_metadata(
        session,
        [_detail(game_number="9999", name="New Detail Game", ticket_price=10)],
    )
    session.commit()

    assert result.games_created == 1
    game = session.scalar(select(Game).where(Game.game_number == "9999"))
    assert game is not None
    assert game.name == "New Detail Game"
    assert game.ticket_price == Decimal("10.00")
    assert game.overall_odds_one_in == Decimal("4.9700")
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == 0


def test_detail_metadata_null_fields_do_not_overwrite_existing_values(
    session: Session,
):
    game = Game(
        game_number="7647",
        name="Emeralds",
        source_url="https://example.test/existing",
        ticket_price=Decimal("1.00"),
        launch_date=datetime(2026, 3, 3, tzinfo=UTC).date(),
        overall_odds_one_in=Decimal("4.9700"),
        top_prize_amount=Decimal("50000.00"),
        category="Gems",
        play_style="Key Number Match",
    )
    session.add(game)
    session.flush()

    detail = _detail(
        name=None,
        ticket_price=None,
        source_url=None,
    )
    detail.overall_odds = None
    detail.launch_date = None
    detail.category = None
    detail.play_style = None
    detail.top_prize_text = None

    result = import_instant_ticket_detail_metadata(session, [detail])
    session.commit()

    assert result.games_updated == 0
    assert game.name == "Emeralds"
    assert game.source_url == "https://example.test/existing"
    assert game.ticket_price == Decimal("1.00")
    assert game.launch_date == datetime(2026, 3, 3, tzinfo=UTC).date()
    assert game.overall_odds_one_in == Decimal("4.9700")
    assert game.top_prize_amount == Decimal("50000.00")
    assert game.category == "Gems"
    assert game.play_style == "Key Number Match"


def test_detail_metadata_unsupported_fields_are_reported(session: Session):
    detail = _detail(game_number="9999", name="Unsupported")
    detail.image_url = "https://example.test/ticket.png"
    detail.play_instructions = "Match numbers."
    detail.raw_fields = {"Game Number": "9999"}

    result = import_instant_ticket_detail_metadata(session, [detail])
    session.commit()

    messages = [issue.message for issue in result.issues]
    assert any("unsupported parsed fields" in message for message in messages)
    unsupported = next(message for message in messages if "unsupported parsed fields" in message)
    assert "image_url" in unsupported
    assert "play_instructions" in unsupported
    assert "overall_odds_text" in unsupported
    assert "consolidated_odds_present" in unsupported
    assert "raw_fields" in unsupported
