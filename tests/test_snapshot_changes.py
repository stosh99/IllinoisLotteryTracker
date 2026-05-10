"""Tests for illinois_lottery_tracker.snapshot_changes.

All tests use an in-memory SQLite database. No network access. No filesystem
access. Read-only functions only — no DB writes are performed by the module
under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    PrizeTierSnapshot,
    RawSourceSnapshot,
    ScrapeRun,
)
from illinois_lottery_tracker.snapshot_changes import (
    InsufficientDataError,
    SnapshotChangeReport,
    compare_scrape_runs,
    find_comparable_run_ids,
    find_latest_two_comparable_runs,
)

# ---------------------------------------------------------------------------
# Fixtures and seeders
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
_T2 = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


def _run(session: Session, started_at: datetime = _T0) -> ScrapeRun:
    run = ScrapeRun(
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=1),
        status="success",
        source_url="https://example.test/unpaid",
        raw_file_path="/tmp/test.html",
    )
    session.add(run)
    session.flush()
    return run


def _game(
    session: Session,
    *,
    game_number: str = "1001",
    name: str = "TEST GAME",
    ticket_price: Decimal | None = Decimal("5"),
    odds: Decimal | None = None,
    source_url: str | None = None,
    est_total_tickets: int | None = None,
    is_active: bool = True,
) -> Game:
    g = Game(
        game_number=game_number,
        name=name,
        ticket_price=ticket_price,
        overall_odds_one_in=odds,
        source_url=source_url,
        est_total_tickets=est_total_tickets,
        is_active=is_active,
    )
    session.add(g)
    session.flush()
    return g


def _snapshot(
    session: Session,
    game: Game,
    run: ScrapeRun,
    *,
    orig_value: Decimal | None = None,
    orig_tickets: int | None = None,
    top_orig: int | None = None,
    captured_at: datetime = _T0,
) -> GameSnapshot:
    snap = GameSnapshot(
        game=game,
        scrape_run=run,
        captured_at=captured_at,
        total_original_prize_value=orig_value,
        total_original_winning_tickets=orig_tickets,
        top_prizes_original=top_orig,
    )
    session.add(snap)
    session.flush()
    return snap


def _tier(
    session: Session,
    snapshot: GameSnapshot,
    *,
    prize_amount: Decimal,
    original_count: int | None,
    remaining_count: int | None = 0,
) -> PrizeTierSnapshot:
    tier = PrizeTierSnapshot(
        game_snapshot=snapshot,
        prize_amount=prize_amount,
        original_count=original_count,
        remaining_count=remaining_count,
    )
    session.add(tier)
    session.flush()
    return tier


def _raw_snap(
    session: Session,
    run: ScrapeRun,
    *,
    captured_at: datetime,
) -> RawSourceSnapshot:
    rss = RawSourceSnapshot(
        scrape_run_id=run.id,
        source_url="https://example.test/unpaid",
        file_path="/tmp/test.html",
        sha256=f"sha256-run{run.id}-{captured_at.isoformat()}",
        captured_at=captured_at,
    )
    session.add(rss)
    session.flush()
    return rss


# ---------------------------------------------------------------------------
# find_comparable_run_ids
# ---------------------------------------------------------------------------


def test_find_comparable_run_ids_empty_db(session: Session):
    assert find_comparable_run_ids(session) == []


def test_find_comparable_run_ids_run_without_snapshots_excluded(session: Session):
    _run(session)  # run with no game_snapshots
    assert find_comparable_run_ids(session) == []


def test_find_comparable_run_ids_returns_runs_with_snapshots(session: Session):
    run = _run(session)
    game = _game(session)
    _snapshot(session, game, run)
    ids = find_comparable_run_ids(session)
    assert ids == [run.id]


def test_find_comparable_run_ids_falls_back_to_started_at_when_no_raw_snapshot(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T2)
    run3 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _snapshot(session, game, run3)
    ids = find_comparable_run_ids(session)
    assert ids == [run1.id, run3.id, run2.id]


# ---------------------------------------------------------------------------
# find_latest_two_comparable_runs
# ---------------------------------------------------------------------------


def test_insufficient_data_empty_db(session: Session):
    with pytest.raises(InsufficientDataError, match="found 0"):
        find_latest_two_comparable_runs(session)


def test_insufficient_data_one_run(session: Session):
    run = _run(session)
    game = _game(session)
    _snapshot(session, game, run)
    with pytest.raises(InsufficientDataError, match="found 1"):
        find_latest_two_comparable_runs(session)


def test_finds_latest_two_from_three_runs(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    run3 = _run(session, started_at=_T2)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _snapshot(session, game, run3)
    older_id, newer_id = find_latest_two_comparable_runs(session)
    assert older_id == run2.id
    assert newer_id == run3.id


def test_finds_latest_two_from_two_runs(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    older_id, newer_id = find_latest_two_comparable_runs(session)
    assert older_id == run1.id
    assert newer_id == run2.id


# ---------------------------------------------------------------------------
# compare_scrape_runs — no changes
# ---------------------------------------------------------------------------


def test_no_changes_all_zeros(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1, orig_value=Decimal("500"), orig_tickets=100, top_orig=5)
    _snapshot(session, game, run2, orig_value=Decimal("500"), orig_tickets=100, top_orig=5)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_game_count == 0
    assert report.missing_game_count == 0
    assert report.structure_change_count == 0


def test_report_run_ids_match_arguments(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.older_scrape_run_id == run1.id
    assert report.newer_scrape_run_id == run2.id


def test_report_game_counts(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    g1 = _game(session, game_number="1001")
    g2 = _game(session, game_number="1002")
    g3 = _game(session, game_number="1003")
    _snapshot(session, g1, run1)
    _snapshot(session, g2, run1)
    _snapshot(session, g1, run2)
    _snapshot(session, g2, run2)
    _snapshot(session, g3, run2)  # new game only in newer

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.older_game_count == 2
    assert report.newer_game_count == 3


def test_report_is_snapshot_change_report_type(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert isinstance(report, SnapshotChangeReport)


# ---------------------------------------------------------------------------
# compare_scrape_runs — new games
# ---------------------------------------------------------------------------


def test_new_game_detected(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    existing = _game(session, game_number="1001")
    brand_new = _game(session, game_number="9999", name="BRAND NEW GAME")
    _snapshot(session, existing, run1)
    _snapshot(session, existing, run2)
    _snapshot(session, brand_new, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_game_count == 1
    assert report.new_games[0].game_number == "9999"
    assert report.new_games[0].game_name == "BRAND NEW GAME"


def test_new_game_row_ticket_price(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    new_game = _game(session, game_number="9999", ticket_price=Decimal("10"))
    _snapshot(session, new_game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_games[0].ticket_price == Decimal("10")


def test_new_game_has_detail_metadata_true(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    new_game = _game(session, game_number="9999", source_url="https://example.test/game")
    _snapshot(session, new_game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_games[0].has_detail_metadata is True


def test_new_game_has_detail_metadata_false(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    new_game = _game(session, game_number="9999", source_url=None)
    _snapshot(session, new_game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_games[0].has_detail_metadata is False


def test_new_game_has_odds_and_metrics(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    new_game = _game(
        session,
        game_number="9999",
        odds=Decimal("4.0"),
        est_total_tickets=4000,
    )
    _snapshot(session, new_game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_games[0].has_odds is True
    assert report.new_games[0].has_metrics is True


def test_new_game_no_odds_no_metrics(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    new_game = _game(session, game_number="9999", odds=None, est_total_tickets=None)
    _snapshot(session, new_game, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.new_games[0].has_odds is False
    assert report.new_games[0].has_metrics is False


# ---------------------------------------------------------------------------
# compare_scrape_runs — missing games
# ---------------------------------------------------------------------------


def test_missing_game_detected(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    gone = _game(session, game_number="1001", name="GONE GAME")
    still_here = _game(session, game_number="1002")
    _snapshot(session, gone, run1)
    _snapshot(session, still_here, run1)
    _snapshot(session, still_here, run2)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.missing_game_count == 1
    assert report.missing_games[0].game_number == "1001"
    assert report.missing_games[0].game_name == "GONE GAME"


def test_missing_game_last_seen_run_id(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    _snapshot(session, game, run1)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.missing_games[0].last_seen_scrape_run_id == run1.id


def test_missing_game_is_active_reflects_game_table(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", is_active=True)
    _snapshot(session, game, run1)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.missing_games[0].is_active is True


def test_missing_game_inactive_flag(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", is_active=False)
    _snapshot(session, game, run1)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.missing_games[0].is_active is False


# ---------------------------------------------------------------------------
# compare_scrape_runs — prize structure changes
# ---------------------------------------------------------------------------


def test_total_original_prize_value_changed(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    _snapshot(session, game, run1, orig_value=Decimal("500000"))
    _snapshot(session, game, run2, orig_value=Decimal("600000"))

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    change = report.structure_changes[0]
    assert "total_original_prize_value" in change.changed_fields
    assert change.old_total_original_prize_value == Decimal("500000")
    assert change.new_total_original_prize_value == Decimal("600000")


def test_total_original_winning_tickets_changed(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    _snapshot(session, game, run1, orig_tickets=1000)
    _snapshot(session, game, run2, orig_tickets=1200)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    change = report.structure_changes[0]
    assert "total_original_winning_tickets" in change.changed_fields
    assert change.old_total_original_winning_tickets == 1000
    assert change.new_total_original_winning_tickets == 1200


def test_top_prizes_original_changed(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    _snapshot(session, game, run1, top_orig=5)
    _snapshot(session, game, run2, top_orig=6)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    assert "top_prizes_original" in report.structure_changes[0].changed_fields


def test_prize_tier_original_count_changed(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    snap1 = _snapshot(session, game, run1)
    snap2 = _snapshot(session, game, run2)
    _tier(session, snap1, prize_amount=Decimal("50"), original_count=100)
    _tier(session, snap2, prize_amount=Decimal("50"), original_count=120)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    change = report.structure_changes[0]
    assert "prize_tier_original_counts" in change.changed_fields
    assert len(change.prize_tier_changes) == 1
    tc = change.prize_tier_changes[0]
    assert tc.prize_amount == Decimal("50")
    assert tc.old_original_count == 100
    assert tc.new_original_count == 120


def test_prize_tier_added_in_newer_snapshot(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    snap1 = _snapshot(session, game, run1)
    snap2 = _snapshot(session, game, run2)
    _tier(session, snap1, prize_amount=Decimal("50"), original_count=100)
    _tier(session, snap2, prize_amount=Decimal("50"), original_count=100)
    _tier(session, snap2, prize_amount=Decimal("10"), original_count=500)  # added

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    tier_changes = report.structure_changes[0].prize_tier_changes
    tc_amounts = [tc.prize_amount for tc in tier_changes]
    assert Decimal("10") in tc_amounts
    added = next(tc for tc in tier_changes if tc.prize_amount == Decimal("10"))
    assert added.old_original_count is None
    assert added.new_original_count == 500


def test_prize_tier_removed_in_newer_snapshot(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    snap1 = _snapshot(session, game, run1)
    snap2 = _snapshot(session, game, run2)
    _tier(session, snap1, prize_amount=Decimal("50"), original_count=100)
    _tier(session, snap1, prize_amount=Decimal("10"), original_count=500)  # removed
    _tier(session, snap2, prize_amount=Decimal("50"), original_count=100)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    removed = next(
        tc for tc in report.structure_changes[0].prize_tier_changes
        if tc.prize_amount == Decimal("10")
    )
    assert removed.old_original_count == 500
    assert removed.new_original_count is None


def test_est_total_tickets_changed_when_odds_exist(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", odds=Decimal("4.0"))
    _snapshot(session, game, run1, orig_tickets=1000)  # est = 4000
    _snapshot(session, game, run2, orig_tickets=1200)  # est = 4800

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    change = report.structure_changes[0]
    assert "est_total_tickets" in change.changed_fields
    assert change.old_est_total_tickets == 4000
    assert change.new_est_total_tickets == 4800


def test_missing_odds_does_not_crash_or_flag_est_total_tickets(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", odds=None)
    _snapshot(session, game, run1, orig_tickets=1000)
    _snapshot(session, game, run2, orig_tickets=1200)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    change = report.structure_changes[0]
    assert "est_total_tickets" not in change.changed_fields
    assert change.old_est_total_tickets is None
    assert change.new_est_total_tickets is None


def test_no_structure_change_when_values_identical(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", odds=Decimal("4.0"))
    kw = dict(orig_value=Decimal("500000"), orig_tickets=1000, top_orig=5)
    snap1 = _snapshot(session, game, run1, **kw)
    snap2 = _snapshot(session, game, run2, **kw)
    _tier(session, snap1, prize_amount=Decimal("50"), original_count=100)
    _tier(session, snap2, prize_amount=Decimal("50"), original_count=100)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 0


def test_structure_change_row_game_number_and_name(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", name="PRIZE GAME")
    _snapshot(session, game, run1, orig_tickets=1000)
    _snapshot(session, game, run2, orig_tickets=2000)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    change = report.structure_changes[0]
    assert change.game_number == "1001"
    assert change.game_name == "PRIZE GAME"


def test_changed_fields_has_no_false_positives(session: Session):
    """Only fields that actually differ appear in changed_fields."""
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001", odds=Decimal("4.0"))
    # Only top_prizes_original differs; tickets and prize value are identical.
    _snapshot(session, game, run1, orig_value=Decimal("5000"), orig_tickets=100, top_orig=5)
    _snapshot(session, game, run2, orig_value=Decimal("5000"), orig_tickets=100, top_orig=6)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    changed = report.structure_changes[0].changed_fields
    assert "top_prizes_original" in changed
    assert "total_original_prize_value" not in changed
    assert "total_original_winning_tickets" not in changed
    assert "est_total_tickets" not in changed


def test_no_remaining_prize_movement_in_structure_changes(session: Session):
    """Remaining-prize changes (remaining_count) must not appear in changed_fields."""
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session, game_number="1001")
    snap1 = _snapshot(session, game, run1)
    snap2 = _snapshot(session, game, run2)
    # Same original_count in both; only remaining_count differs (normal daily movement).
    _tier(session, snap1, prize_amount=Decimal("50"), original_count=100, remaining_count=80)
    _tier(session, snap2, prize_amount=Decimal("50"), original_count=100, remaining_count=60)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 0


def test_multiple_games_some_changed_some_not(session: Session):
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    g1 = _game(session, game_number="1001")
    g2 = _game(session, game_number="1002")
    _snapshot(session, g1, run1, orig_tickets=1000)
    _snapshot(session, g1, run2, orig_tickets=1000)  # unchanged
    _snapshot(session, g2, run1, orig_tickets=500)
    _snapshot(session, g2, run2, orig_tickets=600)  # changed

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.structure_change_count == 1
    assert report.structure_changes[0].game_number == "1002"


# ---------------------------------------------------------------------------
# Ordering by source captured_at (RawSourceSnapshot.captured_at)
# ---------------------------------------------------------------------------


def test_find_comparable_run_ids_orders_by_source_captured_at(session: Session):
    # run1 has a later started_at but an earlier source capture.
    # run2 has an earlier started_at but a later source capture.
    # Ordering must follow source captured_at, not started_at.
    run1 = _run(session, started_at=_T2)  # pipeline ran at T2
    run2 = _run(session, started_at=_T1)  # pipeline ran at T1
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _raw_snap(session, run1, captured_at=_T0)  # source content from T0 (oldest)
    _raw_snap(session, run2, captured_at=_T2)  # source content from T2 (newest)

    ids = find_comparable_run_ids(session)

    assert ids == [run1.id, run2.id]  # T0 source before T2 source


def test_find_latest_two_uses_source_captured_at_not_started_at(session: Session):
    # Three runs. run3 started last but has the oldest source content.
    # The two most-recent source captures are run1 and run2.
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    run3 = _run(session, started_at=_T2)  # most recent started_at
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _snapshot(session, game, run3)
    _raw_snap(session, run1, captured_at=_T1)  # source from T1
    _raw_snap(session, run2, captured_at=_T2)  # source from T2 (newest content)
    _raw_snap(session, run3, captured_at=_T0)  # source from T0 (oldest content)

    older_id, newer_id = find_latest_two_comparable_runs(session)

    # Ordered by source capture: T0 (run3), T1 (run1), T2 (run2).
    # Latest two are run1 (T1) and run2 (T2).
    assert older_id == run1.id
    assert newer_id == run2.id


def test_reimport_older_file_not_selected_as_newest(session: Session):
    # Simulate nightly workflow: run1 = May 10 content, run2 = May 11 content.
    # Then run3 re-imports April 25 content via --force (started after both).
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    run3 = _run(session, started_at=_T2)  # re-import, started last
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _snapshot(session, game, run3)

    # Source capture times: run1=May10, run2=May11, run3=April25 (older content)
    _may10 = datetime(2026, 5, 10, 0, 5, tzinfo=UTC)
    _may11 = datetime(2026, 5, 11, 0, 7, tzinfo=UTC)
    _apr25 = datetime(2026, 4, 25, 3, 49, tzinfo=UTC)
    _raw_snap(session, run1, captured_at=_may10)
    _raw_snap(session, run2, captured_at=_may11)
    _raw_snap(session, run3, captured_at=_apr25)  # old content, re-imported late

    ids = find_comparable_run_ids(session)

    # Correct order by source date: Apr25 (run3), May10 (run1), May11 (run2)
    assert ids == [run3.id, run1.id, run2.id]

    # find_latest_two should pick the two most recent SOURCE captures
    older_id, newer_id = find_latest_two_comparable_runs(session)
    assert older_id == run1.id   # May 10 content
    assert newer_id == run2.id   # May 11 content (not the re-imported Apr 25)


def test_report_exposes_source_and_run_timestamps_separately(session: Session):
    # source captured at T0, pipeline ran at T1 (50 min later — normal nightly gap)
    run1 = _run(session, started_at=_T1)
    run2 = _run(session, started_at=_T2)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    _raw_snap(session, run1, captured_at=_T0)  # source earlier than pipeline run
    _raw_snap(session, run2, captured_at=_T1)

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    # Normalize both sides to naive UTC: older_source_captured_at comes from a DB
    # SELECT (naive in SQLite) while older_run_started_at may be the in-memory ORM
    # object (tz-aware). Strip tzinfo from both to compare portably.
    def _naive(dt: datetime) -> datetime:
        return dt.replace(tzinfo=None)

    assert _naive(report.older_source_captured_at) == _naive(_T0)
    assert _naive(report.older_run_started_at) == _naive(_T1)
    assert _naive(report.newer_source_captured_at) == _naive(_T1)
    assert _naive(report.newer_run_started_at) == _naive(_T2)


def test_report_source_captured_at_none_when_no_raw_snapshot(session: Session):
    # A run with no RawSourceSnapshot (e.g. legacy import script).
    run1 = _run(session, started_at=_T0)
    run2 = _run(session, started_at=_T1)
    game = _game(session)
    _snapshot(session, game, run1)
    _snapshot(session, game, run2)
    # No _raw_snap for either run.

    report = compare_scrape_runs(session, older_run_id=run1.id, newer_run_id=run2.id)

    assert report.older_source_captured_at is None
    assert report.newer_source_captured_at is None
    assert report.older_run_started_at == _T0 + timedelta(minutes=0)
    assert report.newer_run_started_at == _T1 + timedelta(minutes=0)
