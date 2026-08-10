"""Tests for read-only stored metrics reporting."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.metrics_report import (
    MetricsReportSection,
    build_metrics_report,
    caution_rows,
    depleted_top_prize_rows,
    format_money,
    format_odds,
    format_overall_odds,
    format_percent,
    missing_odds_rows,
    render_text_report,
    top_estimated_payout_rows,
    top_ev_vs_launch_rows,
    top_excluding_top_prize_rows,
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
T0 = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


def test_latest_snapshot_selection_uses_source_capture_ordering(session: Session):
    game = _game(session, game_number="1001", name="SOURCE ORDER")
    older_source_run = _run(session, started_at=T2)
    newer_source_run = _run(session, started_at=T1)
    _raw_snap(session, older_source_run, captured_at=T0)
    _raw_snap(session, newer_source_run, captured_at=T2)

    _snapshot(
        session,
        game,
        older_source_run,
        estimated_payout_ratio=Decimal("0.40"),
        captured_at=T2,
    )
    _snapshot(
        session,
        game,
        newer_source_run,
        estimated_payout_ratio=Decimal("0.80"),
        captured_at=T1,
    )

    report = build_metrics_report(session)

    assert len(report.rows) == 1
    assert report.rows[0].scrape_run_id == newer_source_run.id
    assert report.rows[0].estimated_payout_ratio == Decimal("0.800000")
    assert report.latest_source_captured_at == T2


def test_rankings_sort_by_metric_descending(session: Session):
    _seed_ranking_games(session)

    report = build_metrics_report(session)

    assert [r.game_number for r in top_estimated_payout_rows(report, limit=2)] == [
        "1002",
        "1001",
    ]
    assert [r.game_number for r in top_excluding_top_prize_rows(report, limit=2)] == [
        "1001",
        "1002",
    ]
    assert [r.game_number for r in top_ev_vs_launch_rows(report, limit=2)] == [
        "1003",
        "1001",
    ]


def test_missing_odds_and_depleted_sections(session: Session):
    _seed_ranking_games(session)
    report = build_metrics_report(session)

    assert [row.game_number for row in missing_odds_rows(report)] == ["7587"]
    assert [row.game_number for row in depleted_top_prize_rows(report)] == ["1003"]

    text = render_text_report(
        report, section=MetricsReportSection.MISSING_ODDS, limit=10
    )
    assert "EV and odds-dependent metrics cannot be computed without odds metadata." in text
    assert "[7587] NO ODDS" in text

    text = render_text_report(report, section=MetricsReportSection.DEPLETED, limit=10)
    assert "Games With Depleted Top Prizes" in text
    assert "[1003] DEPLETED TOP" in text


def test_formatting_percent_money_and_na():
    assert format_percent(Decimal("0.749")) == "74.9%"
    assert format_percent(Decimal("1.0")) == "100.0%"
    assert format_percent(None) == "N/A"
    assert format_money(Decimal("7.49")) == "$7.49"
    assert format_money(None) == "N/A"
    assert format_odds(Decimal("1234.4")) == "1 in 1,234"
    assert format_odds(None) == "N/A"
    assert format_overall_odds(Decimal("2.9700")) == "1 in 2.97"


def test_game_detail_section_renders_original_and_current_tier_odds(session: Session):
    run = _run(session, started_at=T1)
    _raw_snap(session, run, captured_at=T1)
    game = _game(session, game_number="7639", name="$1,000,000 CROSSWORD 50X")
    game.overall_odds_one_in = Decimal("4.0")
    game.est_total_tickets = 400
    snap = _snapshot(
        session,
        game,
        run,
        estimated_ev=Decimal("8.00"),
        estimated_payout_ratio=Decimal("0.80"),
        total_original_winning_tickets=100,
        total_remaining_winning_tickets=50,
        estimated_tickets_remaining=200,
    )
    session.add_all(
        [
            PrizeTierSnapshot(
                game_snapshot=snap,
                prize_amount=Decimal("1000"),
                original_count=2,
                remaining_count=1,
                claimed_count=1,
            ),
            PrizeTierSnapshot(
                game_snapshot=snap,
                prize_amount=Decimal("50"),
                original_count=20,
                remaining_count=10,
                claimed_count=10,
            ),
        ]
    )
    session.flush()

    report = build_metrics_report(session)
    text = render_text_report(
        report,
        section=MetricsReportSection.GAME,
        game_number="7639",
    )

    assert "Game Detail" in text
    assert "Orig odds" in text
    assert "Est odds now" in text
    assert "$1,000.00" in text
    assert "1 in 200" in text
    assert "$50.00" in text
    assert "1 in 20" in text
    assert "Totals" in text
    assert "100" in text
    assert "50" in text
    assert "1 in 4" in text


def test_caution_rows_are_descriptive_candidates(session: Session):
    _seed_ranking_games(session)
    report = build_metrics_report(session)

    rows = caution_rows(report, limit=10)

    assert {row.game_number for row in rows} == {"1003"}
    text = render_text_report(report, section=MetricsReportSection.CAUTION, limit=10)
    assert "Games To Review Carefully" in text
    assert "Bad games" not in text
    assert "best ticket to buy" not in text.lower()
    assert "unsold" not in text.lower()


def test_help_exits_without_requiring_database():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_metrics.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "DATABASE_URL is not set" not in result.stderr


def test_legacy_report_is_disabled_with_explicit_replacement():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_metrics.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "DEPRECATED" in result.stderr
    assert "report_analytics.py --nightly-status" in result.stderr


def test_report_generation_is_read_only(session: Session):
    _seed_ranking_games(session)
    statements: list[str] = []

    @event.listens_for(session.bind, "before_cursor_execute")
    def record_statement(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement.strip().upper())

    report = build_metrics_report(session)
    text = render_text_report(report)

    assert "Estimated Metrics Report" in text
    assert not session.dirty
    assert not session.new
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def _run(session: Session, *, started_at: datetime = T0) -> ScrapeRun:
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


def _game(
    session: Session,
    *,
    game_number: str,
    name: str,
    ticket_price: Decimal | None = Decimal("10"),
    is_active: bool = True,
) -> Game:
    game = Game(
        game_number=game_number,
        name=name,
        ticket_price=ticket_price,
        is_active=is_active,
    )
    session.add(game)
    session.flush()
    return game


def _snapshot(
    session: Session,
    game: Game,
    run: ScrapeRun,
    *,
    captured_at: datetime = T1,
    estimated_ev: Decimal | None = Decimal("7.00"),
    estimated_ev_excluding_top_prize: Decimal | None = Decimal("6.50"),
    estimated_payout_ratio: Decimal | None = Decimal("0.70"),
    estimated_house_edge: Decimal | None = Decimal("0.30"),
    estimated_payout_ratio_excluding_top_prize: Decimal | None = Decimal("0.65"),
    launch_ev: Decimal | None = Decimal("6.00"),
    launch_payout_ratio: Decimal | None = Decimal("0.60"),
    ev_vs_launch_ratio: Decimal | None = Decimal("1.166667"),
    remaining_prize_value_pct: Decimal | None = Decimal("0.50"),
    remaining_winning_tickets_pct: Decimal | None = Decimal("0.40"),
    top_prize_remaining_pct: Decimal | None = Decimal("0.50"),
    top_prize_depleted: bool | None = False,
    top_prizes_original: int | None = 2,
    top_prizes_remaining: int | None = 1,
    total_original_winning_tickets: int | None = None,
    total_remaining_winning_tickets: int | None = None,
    estimated_tickets_remaining: int | None = None,
) -> GameSnapshot:
    snap = GameSnapshot(
        game=game,
        scrape_run=run,
        captured_at=captured_at,
        estimated_ev=estimated_ev,
        estimated_ev_excluding_top_prize=estimated_ev_excluding_top_prize,
        estimated_payout_ratio=estimated_payout_ratio,
        estimated_house_edge=estimated_house_edge,
        estimated_payout_ratio_excluding_top_prize=(
            estimated_payout_ratio_excluding_top_prize
        ),
        launch_ev=launch_ev,
        launch_payout_ratio=launch_payout_ratio,
        ev_vs_launch_ratio=ev_vs_launch_ratio,
        remaining_prize_value_pct=remaining_prize_value_pct,
        remaining_winning_tickets_pct=remaining_winning_tickets_pct,
        top_prize_remaining_pct=top_prize_remaining_pct,
        top_prize_depleted=top_prize_depleted,
        top_prizes_original=top_prizes_original,
        top_prizes_remaining=top_prizes_remaining,
        total_original_winning_tickets=total_original_winning_tickets,
        total_remaining_winning_tickets=total_remaining_winning_tickets,
        estimated_tickets_remaining=estimated_tickets_remaining,
    )
    session.add(snap)
    session.flush()
    return snap


def _seed_ranking_games(session: Session) -> None:
    run = _run(session, started_at=T1)
    _raw_snap(session, run, captured_at=T1)

    _snapshot(
        session,
        _game(session, game_number="1001", name="BALANCED"),
        run,
        estimated_ev=Decimal("8.00"),
        estimated_ev_excluding_top_prize=Decimal("7.00"),
        estimated_payout_ratio=Decimal("0.80"),
        estimated_payout_ratio_excluding_top_prize=Decimal("0.70"),
        ev_vs_launch_ratio=Decimal("1.10"),
    )
    _snapshot(
        session,
        _game(session, game_number="1002", name="HIGH PAYOUT"),
        run,
        estimated_ev=Decimal("9.00"),
        estimated_ev_excluding_top_prize=Decimal("5.00"),
        estimated_payout_ratio=Decimal("0.90"),
        estimated_payout_ratio_excluding_top_prize=Decimal("0.50"),
        ev_vs_launch_ratio=Decimal("1.00"),
    )
    _snapshot(
        session,
        _game(session, game_number="1003", name="DEPLETED TOP"),
        run,
        estimated_ev=Decimal("4.00"),
        estimated_ev_excluding_top_prize=Decimal("4.00"),
        estimated_payout_ratio=Decimal("0.40"),
        estimated_payout_ratio_excluding_top_prize=Decimal("0.40"),
        ev_vs_launch_ratio=Decimal("1.20"),
        top_prize_depleted=True,
        top_prizes_original=3,
        top_prizes_remaining=0,
    )
    _snapshot(
        session,
        _game(session, game_number="7587", name="NO ODDS"),
        run,
        estimated_ev=None,
        estimated_ev_excluding_top_prize=None,
        estimated_payout_ratio=None,
        estimated_house_edge=None,
        estimated_payout_ratio_excluding_top_prize=None,
        launch_ev=None,
        launch_payout_ratio=None,
        ev_vs_launch_ratio=None,
        remaining_prize_value_pct=Decimal("0.75"),
        remaining_winning_tickets_pct=Decimal("0.65"),
        top_prize_remaining_pct=None,
        top_prize_depleted=None,
        top_prizes_original=None,
        top_prizes_remaining=None,
    )
