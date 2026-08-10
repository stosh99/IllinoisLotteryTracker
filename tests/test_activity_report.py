"""Tests for read-only implied prize activity reporting."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.activity_report import (
    ActivityReportSection,
    build_activity_report,
    latest_activity_rows,
    render_text_report,
    rolling_activity_rows,
    tier_activity_rows_for_game,
)
from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    PrizeTierSnapshot,
    RawSourceSnapshot,
    ScrapeRun,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)
T1 = datetime(2026, 5, 11, 7, 0, tzinfo=UTC)
T2 = datetime(2026, 5, 12, 7, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


def test_activity_compares_consecutive_snapshots_by_source_time(session: Session):
    game = _game(session, game_number="1001", name="ORDERED")
    run0 = _run(session, started_at=T2)
    run1 = _run(session, started_at=T0)
    _raw_snap(session, run0, captured_at=T0)
    _raw_snap(session, run1, captured_at=T1)
    _snapshot(session, game, run0, remaining_by_prize={Decimal("100"): 10})
    _snapshot(session, game, run1, remaining_by_prize={Decimal("100"): 7})

    report = build_activity_report(session)

    assert len(report.game_rows) == 1
    row = report.game_rows[0]
    assert row.previous_observed_at == T0
    assert row.observed_at == T1
    assert row.implied_claimed_count == 3
    assert row.implied_claimed_value == Decimal("300.00")


def test_latest_activity_rows_rank_by_implied_value(session: Session):
    _seed_activity(session)

    report = build_activity_report(session)
    rows = latest_activity_rows(report, limit=2)

    assert [row.game_number for row in rows] == ["1002", "1001"]
    assert rows[0].implied_claimed_value == Decimal("1000.00")


def test_rolling_activity_rows_sum_window(session: Session):
    _seed_activity(session)

    report = build_activity_report(session)
    rows = rolling_activity_rows(report, window_days=7, limit=10)
    by_number = {row.game_number: row for row in rows}

    assert by_number["1001"].interval_count == 2
    assert by_number["1001"].implied_claimed_count == 5
    assert by_number["1001"].implied_claimed_value == Decimal("500.00")


def test_tier_activity_rows_for_game_and_pivot_render(session: Session):
    _seed_activity(session)
    report = build_activity_report(session)

    rows = tier_activity_rows_for_game(report, game_number="1001")

    assert len(rows) == 2
    assert [row.implied_claimed_count for row in rows] == [3, 2]

    text = render_text_report(
        report,
        section=ActivityReportSection.TIERS,
        game_number="1001",
    )
    assert "Prize-Tier Implied Activity" in text
    assert "Game 1001: STEADY" in text
    assert "$100.00" in text
    assert "2" in text
    assert "3" in text


def test_tier_pivot_shows_missing_calendar_dates(session: Session):
    game = _game(session, game_number="7657", name="DOUBLE THE LUCK")
    run0 = _run(session, started_at=T0)
    run1 = _run(session, started_at=T1)
    run3 = _run(session, started_at=datetime(2026, 5, 13, 7, 0, tzinfo=UTC))
    _raw_snap(session, run0, captured_at=T0)
    _raw_snap(session, run1, captured_at=T1)
    _raw_snap(session, run3, captured_at=datetime(2026, 5, 13, 7, 0, tzinfo=UTC))
    _snapshot(session, game, run0, remaining_by_prize={Decimal("50"): 10})
    _snapshot(session, game, run1, remaining_by_prize={Decimal("50"): 8})
    _snapshot(session, game, run3, remaining_by_prize={Decimal("50"): 5})

    text = render_text_report(
        build_activity_report(session),
        section=ActivityReportSection.TIERS,
        game_number="7657",
    )

    assert "5/11" in text
    assert "5/12" in text
    assert "5/13" in text
    assert "N/A" in text


def test_report_wording_is_cautious(session: Session):
    _seed_activity(session)
    text = render_text_report(build_activity_report(session), limit=2)

    assert "implied" in text.lower()
    assert "public unclaimed-prize counts" in text
    assert "unsold" not in text.lower()
    assert "popular" not in text.lower()


def test_help_exits_without_requiring_database():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_activity.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "DATABASE_URL is not set" not in result.stderr


def test_report_generation_is_read_only(session: Session):
    _seed_activity(session)
    statements: list[str] = []

    @event.listens_for(session.bind, "before_cursor_execute")
    def record_statement(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement.strip().upper())

    text = render_text_report(build_activity_report(session))

    assert "Prize Activity Report" in text
    assert not session.dirty
    assert not session.new
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def _run(session: Session, *, started_at: datetime) -> ScrapeRun:
    run = ScrapeRun(
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=1),
        status="success",
        source_url="https://example.test/unpaid",
    )
    session.add(run)
    session.flush()
    return run


def _raw_snap(session: Session, run: ScrapeRun, *, captured_at: datetime) -> None:
    session.add(
        RawSourceSnapshot(
            scrape_run_id=run.id,
            source_url="https://example.test/unpaid",
            file_path="/tmp/test.html",
            sha256=f"sha-{run.id}-{captured_at.isoformat()}",
            captured_at=captured_at,
        )
    )
    session.flush()


def _game(session: Session, *, game_number: str, name: str) -> Game:
    game = Game(game_number=game_number, name=name, ticket_price=Decimal("10"))
    session.add(game)
    session.flush()
    return game


def _snapshot(
    session: Session,
    game: Game,
    run: ScrapeRun,
    *,
    remaining_by_prize: dict[Decimal, int],
) -> GameSnapshot:
    snapshot = GameSnapshot(
        game=game,
        scrape_run=run,
        total_original_prize_value=Decimal("1000"),
        total_remaining_prize_value=sum(
            prize * Decimal(count) for prize, count in remaining_by_prize.items()
        ),
        total_original_winning_tickets=100,
        total_remaining_winning_tickets=sum(remaining_by_prize.values()),
    )
    session.add(snapshot)
    session.flush()
    for prize, remaining in remaining_by_prize.items():
        session.add(
            PrizeTierSnapshot(
                game_snapshot=snapshot,
                prize_amount=prize,
                original_count=100,
                remaining_count=remaining,
                claimed_count=100 - remaining,
            )
        )
    session.flush()
    return snapshot


def _seed_activity(session: Session) -> None:
    run0 = _run(session, started_at=T0)
    run1 = _run(session, started_at=T1)
    run2 = _run(session, started_at=T2)
    _raw_snap(session, run0, captured_at=T0)
    _raw_snap(session, run1, captured_at=T1)
    _raw_snap(session, run2, captured_at=T2)

    game1 = _game(session, game_number="1001", name="STEADY")
    _snapshot(session, game1, run0, remaining_by_prize={Decimal("100"): 10})
    _snapshot(session, game1, run1, remaining_by_prize={Decimal("100"): 8})
    _snapshot(session, game1, run2, remaining_by_prize={Decimal("100"): 5})

    game2 = _game(session, game_number="1002", name="BIGGER VALUE")
    _snapshot(session, game2, run0, remaining_by_prize={Decimal("500"): 5})
    _snapshot(session, game2, run1, remaining_by_prize={Decimal("500"): 4})
    _snapshot(session, game2, run2, remaining_by_prize={Decimal("500"): 2})
