"""Tests for illinois_lottery_tracker.metrics.

Pure-function tests have no DB dependency. Updater tests use in-memory SQLite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.metrics import (
    MetricsResult,
    compute_snapshot_metrics,
    estimate_ev,
    estimate_ev_excluding_top_prize,
    estimate_ev_vs_launch,
    estimate_house_edge,
    estimate_launch_ev,
    estimate_payout_ratio,
    estimate_remaining_pct,
    estimate_remaining_tickets,
    estimate_total_tickets,
    is_top_prize_depleted,
)
from illinois_lottery_tracker.models import Base, Game, GameSnapshot, PrizeTierSnapshot, ScrapeRun

# ---------------------------------------------------------------------------
# estimate_total_tickets
# ---------------------------------------------------------------------------


def test_estimate_total_tickets_basic():
    assert estimate_total_tickets(1000, Decimal("4.0")) == 4000


def test_estimate_total_tickets_rounds():
    # 1000 * 3.333 = 3333.0
    assert estimate_total_tickets(1000, Decimal("3.333")) == 3333


def test_estimate_total_tickets_none_winning_tickets():
    assert estimate_total_tickets(None, Decimal("4.0")) is None


def test_estimate_total_tickets_none_odds():
    assert estimate_total_tickets(1000, None) is None


def test_estimate_total_tickets_both_none():
    assert estimate_total_tickets(None, None) is None


# ---------------------------------------------------------------------------
# estimate_remaining_tickets
# ---------------------------------------------------------------------------


def test_estimate_remaining_tickets_basic():
    assert estimate_remaining_tickets(500, Decimal("4.0")) == 2000


def test_estimate_remaining_tickets_fractional_odds():
    # 800 * 4.97 = 3976.0
    assert estimate_remaining_tickets(800, Decimal("4.97")) == 3976


def test_estimate_remaining_tickets_none_tickets():
    assert estimate_remaining_tickets(None, Decimal("4.0")) is None


def test_estimate_remaining_tickets_none_odds():
    assert estimate_remaining_tickets(500, None) is None


# ---------------------------------------------------------------------------
# estimate_ev
# ---------------------------------------------------------------------------


def test_estimate_ev_basic():
    # $10,000 remaining / 2,000 remaining tickets = $5.00
    result = estimate_ev(Decimal("10000"), 2000)
    assert result == Decimal("5")


def test_estimate_ev_fractional():
    result = estimate_ev(Decimal("7500"), 3000)
    assert result == Decimal("2.5")


def test_estimate_ev_zero_remaining_tickets():
    assert estimate_ev(Decimal("10000"), 0) is None


def test_estimate_ev_none_prize_value():
    assert estimate_ev(None, 2000) is None


def test_estimate_ev_none_remaining_tickets():
    assert estimate_ev(Decimal("10000"), None) is None


# ---------------------------------------------------------------------------
# estimate_ev_excluding_top_prize
# ---------------------------------------------------------------------------


def test_estimate_ev_excluding_top_basic():
    tiers = [
        (Decimal("1000"), 5),    # top — excluded
        (Decimal("50"), 100),
        (Decimal("10"), 200),
    ]
    # 50*100 + 10*200 = 5000 + 2000 = 7000
    result = estimate_ev_excluding_top_prize(tiers, 2000)
    assert result == Decimal("7000") / Decimal("2000")


def test_estimate_ev_excluding_top_only_top_tier():
    tiers = [(Decimal("1000"), 5)]
    assert estimate_ev_excluding_top_prize(tiers, 2000) is None


def test_estimate_ev_excluding_top_zero_remaining_tickets():
    tiers = [(Decimal("1000"), 5), (Decimal("50"), 100)]
    assert estimate_ev_excluding_top_prize(tiers, 0) is None


def test_estimate_ev_excluding_top_none_remaining_tickets():
    tiers = [(Decimal("1000"), 5), (Decimal("50"), 100)]
    assert estimate_ev_excluding_top_prize(tiers, None) is None


def test_estimate_ev_excluding_top_empty_tiers():
    assert estimate_ev_excluding_top_prize([], 2000) is None


def test_estimate_ev_excluding_top_non_top_count_none():
    # Non-top tier has remaining_count=None — excluded from sum, result is None
    tiers = [(Decimal("1000"), 5), (Decimal("50"), None)]
    assert estimate_ev_excluding_top_prize(tiers, 2000) is None


def test_estimate_ev_excluding_top_non_top_count_zero():
    # Non-top tier with remaining_count=0 means $0 EV from that tier
    tiers = [(Decimal("1000"), 5), (Decimal("50"), 0)]
    result = estimate_ev_excluding_top_prize(tiers, 2000)
    assert result == Decimal("0")


# ---------------------------------------------------------------------------
# Updater: session fixtures
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
        started_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
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
    odds: Decimal | None = Decimal("4.0"),
    ticket_price: Decimal | None = None,
) -> Game:
    g = Game(
        game_number=game_number,
        name=name,
        overall_odds_one_in=odds,
        ticket_price=ticket_price,
        is_active=True,
    )
    session.add(g)
    session.flush()
    return g


def _snapshot(
    session: Session,
    game: Game,
    *,
    total_orig: int | None = 1000,
    total_remaining: int | None = 800,
    total_orig_prize_value: Decimal | None = None,
    top_prizes_original: int | None = None,
    top_prizes_remaining: int | None = None,
    prize_tiers: list[tuple[int, int, int]] | None = None,
) -> GameSnapshot:
    run = _scrape_run(session)
    remaining_value: Decimal | None = None
    if prize_tiers is not None:
        remaining_value = sum(
            Decimal(amt) * Decimal(rem) for amt, _orig, rem in prize_tiers
        )
    snap = GameSnapshot(
        game=game,
        scrape_run=run,
        captured_at=datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
        total_original_winning_tickets=total_orig,
        total_remaining_winning_tickets=total_remaining,
        total_original_prize_value=total_orig_prize_value,
        total_remaining_prize_value=remaining_value,
        top_prizes_original=top_prizes_original,
        top_prizes_remaining=top_prizes_remaining,
    )
    session.add(snap)
    session.flush()
    if prize_tiers is not None:
        for prize_amt, orig_count, rem_count in prize_tiers:
            session.add(
                PrizeTierSnapshot(
                    game_snapshot=snap,
                    prize_amount=Decimal(prize_amt),
                    original_count=orig_count,
                    remaining_count=rem_count,
                    claimed_count=orig_count - rem_count,
                )
            )
        session.flush()
    return snap


# ---------------------------------------------------------------------------
# Updater: return type
# ---------------------------------------------------------------------------


def test_compute_metrics_returns_result_type(session: Session):
    result = compute_snapshot_metrics(session)
    assert isinstance(result, MetricsResult)


def test_empty_db_returns_zero_counts(session: Session):
    result = compute_snapshot_metrics(session)
    assert result.games_updated == 0
    assert result.snapshots_computed == 0


# ---------------------------------------------------------------------------
# Updater: est_total_tickets on games
# ---------------------------------------------------------------------------


def test_compute_metrics_sets_est_total_tickets(session: Session):
    game = _game(session, odds=Decimal("4.0"))
    _snapshot(session, game, total_orig=1000, total_remaining=800)

    compute_snapshot_metrics(session)

    assert game.est_total_tickets == 4000


def test_compute_metrics_does_not_set_est_total_tickets_when_no_odds(session: Session):
    game = _game(session, odds=None)
    _snapshot(session, game, total_orig=1000, total_remaining=800)

    compute_snapshot_metrics(session)

    assert game.est_total_tickets is None


# ---------------------------------------------------------------------------
# Updater: estimated_tickets_remaining on snapshots
# ---------------------------------------------------------------------------


def test_compute_metrics_sets_estimated_tickets_remaining(session: Session):
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800)

    compute_snapshot_metrics(session)

    assert snap.estimated_tickets_remaining == 3200


def test_compute_metrics_skips_remaining_when_no_odds(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800)

    result = compute_snapshot_metrics(session)

    assert snap.estimated_tickets_remaining is None
    assert result.snapshots_skipped_no_odds == 1


def test_compute_metrics_null_remaining_tickets_when_counts_missing(session: Session):
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=1000, total_remaining=None)

    result = compute_snapshot_metrics(session)

    assert snap.estimated_tickets_remaining is None
    assert result.snapshots_skipped_no_counts == 1
    assert result.snapshots_computed == 1


# ---------------------------------------------------------------------------
# Updater: estimated_ev
# ---------------------------------------------------------------------------


def test_compute_metrics_sets_estimated_ev(session: Session):
    tiers = [(50, 100, 80), (10, 200, 150)]
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=300, total_remaining=230, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    # remaining_value = 50*80 + 10*150 = 4000 + 1500 = 5500
    # estimated_remaining = 230 * 4.0 = 920
    # ev = 5500 / 920
    assert snap.estimated_ev is not None
    assert abs(snap.estimated_ev - Decimal("5500") / Decimal("920")) < Decimal("0.000001")


def test_compute_metrics_ev_none_when_remaining_tickets_zero(session: Session):
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=1000, total_remaining=0)
    snap.total_remaining_prize_value = Decimal("10000")
    session.flush()

    compute_snapshot_metrics(session)

    assert snap.estimated_ev is None


# ---------------------------------------------------------------------------
# Updater: estimated_ev_excluding_top_prize
# ---------------------------------------------------------------------------


def test_compute_metrics_sets_ev_excluding_top(session: Session):
    tiers = [(1000, 5, 3), (50, 100, 80), (10, 200, 150)]
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=305, total_remaining=233, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    # estimated_remaining = 233 * 4.0 = 932
    # non-top value = 50*80 + 10*150 = 4000 + 1500 = 5500
    # ev_ex_top = 5500 / 932
    assert snap.estimated_ev_excluding_top_prize is not None
    expected = Decimal("5500") / Decimal("932")
    assert abs(snap.estimated_ev_excluding_top_prize - expected) < Decimal("0.000001")


def test_compute_metrics_ev_ex_top_none_with_single_tier(session: Session):
    tiers = [(1000, 5, 3)]
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=5, total_remaining=3, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    assert snap.estimated_ev_excluding_top_prize is None


# ---------------------------------------------------------------------------
# Updater: idempotency
# ---------------------------------------------------------------------------


def test_compute_metrics_is_idempotent(session: Session):
    tiers = [(50, 100, 80), (10, 200, 150)]
    game = _game(session, odds=Decimal("4.0"))
    snap = _snapshot(session, game, total_orig=300, total_remaining=230, prize_tiers=tiers)

    compute_snapshot_metrics(session)
    ev_after_first = snap.estimated_ev
    remaining_after_first = snap.estimated_tickets_remaining

    compute_snapshot_metrics(session)

    assert snap.estimated_ev == ev_after_first
    assert snap.estimated_tickets_remaining == remaining_after_first


# ---------------------------------------------------------------------------
# Updater: multiple games and snapshots
# ---------------------------------------------------------------------------


def test_compute_metrics_handles_multiple_games(session: Session):
    game_a = _game(session, game_number="1001", odds=Decimal("4.0"))
    game_b = _game(session, game_number="2001", odds=Decimal("3.0"))
    snap_a = _snapshot(session, game_a, total_orig=1000, total_remaining=800)
    snap_b = _snapshot(session, game_b, total_orig=500, total_remaining=400)

    result = compute_snapshot_metrics(session)

    assert result.snapshots_computed == 2
    assert snap_a.estimated_tickets_remaining == 3200
    assert snap_b.estimated_tickets_remaining == 1200


def test_compute_metrics_skips_game_without_odds_leaves_others(session: Session):
    game_a = _game(session, game_number="1001", odds=Decimal("4.0"))
    game_b = _game(session, game_number="2001", odds=None)
    snap_a = _snapshot(session, game_a, total_orig=1000, total_remaining=800)
    snap_b = _snapshot(session, game_b, total_orig=500, total_remaining=400)

    result = compute_snapshot_metrics(session)

    assert snap_a.estimated_tickets_remaining == 3200
    assert snap_b.estimated_tickets_remaining is None
    assert result.snapshots_computed == 1
    assert result.snapshots_skipped_no_odds == 1


# ---------------------------------------------------------------------------
# estimate_payout_ratio
# ---------------------------------------------------------------------------


def test_estimate_payout_ratio_basic():
    # $0.60 EV on a $1 ticket → 60% payout
    assert estimate_payout_ratio(Decimal("0.60"), Decimal("1.00")) == Decimal("0.60")


def test_estimate_payout_ratio_nontrivial():
    # $3.50 EV on a $5 ticket → 0.70
    result = estimate_payout_ratio(Decimal("3.50"), Decimal("5.00"))
    assert result == Decimal("0.70")


def test_estimate_payout_ratio_none_ev():
    assert estimate_payout_ratio(None, Decimal("5.00")) is None


def test_estimate_payout_ratio_none_price():
    assert estimate_payout_ratio(Decimal("3.50"), None) is None


def test_estimate_payout_ratio_zero_price():
    assert estimate_payout_ratio(Decimal("3.50"), Decimal("0")) is None


# ---------------------------------------------------------------------------
# estimate_house_edge
# ---------------------------------------------------------------------------


def test_estimate_house_edge_basic():
    # 70% payout → 30% house edge
    result = estimate_house_edge(Decimal("0.70"))
    assert result == Decimal("0.30")


def test_estimate_house_edge_none():
    assert estimate_house_edge(None) is None


def test_estimate_house_edge_over_one():
    # Edge cases: payout > 1 → negative house edge (EV+ game)
    result = estimate_house_edge(Decimal("1.05"))
    assert result == Decimal("-0.05")


# ---------------------------------------------------------------------------
# estimate_launch_ev
# ---------------------------------------------------------------------------


def test_estimate_launch_ev_basic():
    # $50,000 original prize pool / 100,000 tickets = $0.50 EV
    result = estimate_launch_ev(Decimal("50000"), 100000)
    assert result == Decimal("0.5")


def test_estimate_launch_ev_none_prize_value():
    assert estimate_launch_ev(None, 100000) is None


def test_estimate_launch_ev_none_tickets():
    assert estimate_launch_ev(Decimal("50000"), None) is None


def test_estimate_launch_ev_zero_tickets():
    assert estimate_launch_ev(Decimal("50000"), 0) is None


# ---------------------------------------------------------------------------
# estimate_ev_vs_launch
# ---------------------------------------------------------------------------


def test_estimate_ev_vs_launch_basic():
    # Current EV $0.40, launch EV $0.50 → ratio 0.80
    result = estimate_ev_vs_launch(Decimal("0.40"), Decimal("0.50"))
    assert result == Decimal("0.8")


def test_estimate_ev_vs_launch_none_ev():
    assert estimate_ev_vs_launch(None, Decimal("0.50")) is None


def test_estimate_ev_vs_launch_none_launch():
    assert estimate_ev_vs_launch(Decimal("0.40"), None) is None


def test_estimate_ev_vs_launch_zero_launch():
    assert estimate_ev_vs_launch(Decimal("0.40"), Decimal("0")) is None


# ---------------------------------------------------------------------------
# estimate_remaining_pct
# ---------------------------------------------------------------------------


def test_estimate_remaining_pct_basic_decimal():
    # $75,000 remaining / $100,000 original = 75%
    result = estimate_remaining_pct(Decimal("75000"), Decimal("100000"))
    assert result == Decimal("0.75")


def test_estimate_remaining_pct_basic_int():
    # 800 remaining / 1000 original = 80%
    result = estimate_remaining_pct(800, 1000)
    assert result == Decimal("0.8")


def test_estimate_remaining_pct_zero_remaining():
    result = estimate_remaining_pct(0, 1000)
    assert result == Decimal("0")


def test_estimate_remaining_pct_none_remaining():
    assert estimate_remaining_pct(None, 1000) is None


def test_estimate_remaining_pct_none_original():
    assert estimate_remaining_pct(800, None) is None


def test_estimate_remaining_pct_zero_original():
    assert estimate_remaining_pct(800, 0) is None


def test_estimate_remaining_pct_not_clamped_above_one():
    assert estimate_remaining_pct(1200, 1000) == Decimal("1.2")


# ---------------------------------------------------------------------------
# is_top_prize_depleted
# ---------------------------------------------------------------------------


def test_is_top_prize_depleted_true():
    assert is_top_prize_depleted(0, 5) is True


def test_is_top_prize_depleted_false():
    assert is_top_prize_depleted(3, 5) is False


def test_is_top_prize_depleted_none_remaining():
    assert is_top_prize_depleted(None, 5) is None


def test_is_top_prize_depleted_none_original():
    assert is_top_prize_depleted(0, None) is None


def test_is_top_prize_depleted_zero_original():
    # No prizes to deplete → undefined
    assert is_top_prize_depleted(0, 0) is None


# ---------------------------------------------------------------------------
# Updater: non-odds metrics computed for all snapshots
# ---------------------------------------------------------------------------


def test_nonodds_metrics_computed_when_no_odds(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=Decimal("50000"),
        top_prizes_original=5, top_prizes_remaining=3,
    )
    snap.total_remaining_prize_value = Decimal("37500")
    session.flush()

    result = compute_snapshot_metrics(session)

    # Non-odds metrics should still be set
    assert snap.remaining_prize_value_pct is not None
    assert snap.remaining_winning_tickets_pct is not None
    assert snap.top_prize_remaining_pct is not None
    assert snap.top_prize_depleted is not None
    # Odds metrics should remain None
    assert snap.estimated_ev is None
    assert snap.estimated_payout_ratio is None
    assert result.snapshots_with_nonodds_metrics == 1
    assert result.snapshots_skipped_no_odds == 1
    assert result.snapshots_computed == 0


def test_remaining_prize_value_pct(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=Decimal("100000"),
    )
    snap.total_remaining_prize_value = Decimal("75000")
    session.flush()

    compute_snapshot_metrics(session)

    assert snap.remaining_prize_value_pct == Decimal("75000") / Decimal("100000")


def test_remaining_winning_tickets_pct(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800)

    compute_snapshot_metrics(session)

    assert snap.remaining_winning_tickets_pct == Decimal("800") / Decimal("1000")


def test_top_prize_remaining_pct(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=10, top_prizes_remaining=6,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_remaining_pct == Decimal("6") / Decimal("10")


def test_top_prize_depleted_true(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=5, top_prizes_remaining=0,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_depleted is True


def test_top_prize_depleted_false(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=5, top_prizes_remaining=2,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_depleted is False


def test_top_prize_depleted_none_when_remaining_null(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=5, top_prizes_remaining=None,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_depleted is None


def test_top_prize_depleted_none_when_original_null(session: Session):
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=None, top_prizes_remaining=0,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_depleted is None


def test_top_prize_depleted_none_when_original_zero(session: Session):
    # A game with no top prizes defined — depletion is undefined.
    game = _game(session, odds=None)
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        top_prizes_original=0, top_prizes_remaining=0,
    )

    compute_snapshot_metrics(session)

    assert snap.top_prize_depleted is None


def test_nonodds_metrics_none_when_data_missing(session: Session):
    # Snapshot without original prize value or top prize counts
    game = _game(session, odds=None)
    snap = _snapshot(session, game, total_orig=None, total_remaining=None)

    compute_snapshot_metrics(session)

    assert snap.remaining_prize_value_pct is None
    assert snap.remaining_winning_tickets_pct is None
    assert snap.top_prize_remaining_pct is None
    assert snap.top_prize_depleted is None


# ---------------------------------------------------------------------------
# Updater: odds-dependent Phase 1 metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_sets_estimated_payout_ratio(session: Session):
    # remaining_value = 5*800 = 4000; est_remaining = 800*4 = 3200
    # EV = 4000/3200 = 1.25; payout_ratio = 1.25/5.00 = 0.25
    tiers = [(5, 1000, 800)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    expected_ev = Decimal("4000") / Decimal("3200")
    expected_ratio = expected_ev / Decimal("5.00")
    assert snap.estimated_payout_ratio is not None
    assert abs(snap.estimated_payout_ratio - expected_ratio) < Decimal("0.000001")


def test_compute_metrics_sets_estimated_house_edge(session: Session):
    tiers = [(5, 1000, 800)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    assert snap.estimated_house_edge is not None
    expected_edge = Decimal("1") - snap.estimated_payout_ratio
    assert abs(snap.estimated_house_edge - expected_edge) < Decimal("0.000001")


def test_compute_metrics_payout_ratio_none_when_no_ticket_price(session: Session):
    tiers = [(5, 1000, 800)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=None)
    snap = _snapshot(session, game, total_orig=1000, total_remaining=800, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    assert snap.estimated_payout_ratio is None
    assert snap.estimated_house_edge is None


def test_compute_metrics_sets_launch_ev(session: Session):
    # total_original_prize_value = $50,000; est_total = 1000 * 4 = 4000
    # launch_ev = 50000 / 4000 = 12.50
    tiers = [(10, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=Decimal("50000"),
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)

    expected = Decimal("50000") / Decimal("4000")
    assert snap.launch_ev is not None
    assert abs(snap.launch_ev - expected) < Decimal("0.000001")


def test_compute_metrics_sets_launch_payout_ratio(session: Session):
    # launch_ev = 50000/4000 = 12.50; ticket_price = $5 → launch_payout = 2.50
    tiers = [(10, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=Decimal("50000"),
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)

    expected_launch_ev = Decimal("50000") / Decimal("4000")
    expected_launch_payout = expected_launch_ev / Decimal("5.00")
    assert snap.launch_payout_ratio is not None
    assert abs(snap.launch_payout_ratio - expected_launch_payout) < Decimal("0.000001")


def test_compute_metrics_launch_ev_none_when_no_original_prize_value(session: Session):
    tiers = [(10, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=None,  # not provided
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)

    assert snap.launch_ev is None
    assert snap.launch_payout_ratio is None
    assert snap.ev_vs_launch_ratio is None


def test_compute_metrics_sets_ev_vs_launch_ratio(session: Session):
    tiers = [(50, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    # total_orig=1000, so est_total = 4000
    # total_orig_prize_value = 50*100 = 5000 → launch_ev = 5000/4000 = 1.25
    # remaining_value = 50*80 = 4000; est_remaining = 800*4 = 3200
    # estimated_ev = 4000/3200 = 1.25; ev_vs_launch = 1.25/1.25 = 1.0
    snap = _snapshot(
        session, game,
        total_orig=1000, total_remaining=800,
        total_orig_prize_value=Decimal("5000"),
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)

    assert snap.ev_vs_launch_ratio is not None
    # ratio should be close to 1.0 since proportional claiming
    assert abs(snap.ev_vs_launch_ratio - Decimal("1.0")) < Decimal("0.001")


def test_compute_metrics_sets_payout_ratio_excluding_top_prize(session: Session):
    tiers = [(1000, 5, 3), (10, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(session, game, total_orig=105, total_remaining=83, prize_tiers=tiers)

    compute_snapshot_metrics(session)

    assert snap.estimated_payout_ratio_excluding_top_prize is not None
    # ev_ex_top / ticket_price
    expected = snap.estimated_ev_excluding_top_prize / Decimal("5.00")
    assert abs(snap.estimated_payout_ratio_excluding_top_prize - expected) < Decimal("0.000001")


# ---------------------------------------------------------------------------
# Updater: snapshots_with_nonodds_metrics count
# ---------------------------------------------------------------------------


def test_nonodds_metrics_count_includes_all_snapshots(session: Session):
    game_a = _game(session, game_number="1001", odds=Decimal("4.0"))
    game_b = _game(session, game_number="2001", odds=None)
    _snapshot(session, game_a, total_orig=1000, total_remaining=800)
    _snapshot(session, game_b, total_orig=500, total_remaining=400)

    result = compute_snapshot_metrics(session)

    assert result.snapshots_with_nonodds_metrics == 2
    assert result.snapshots_computed == 1
    assert result.snapshots_skipped_no_odds == 1


# ---------------------------------------------------------------------------
# Updater: idempotency with new metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_new_fields_idempotent(session: Session):
    tiers = [(50, 100, 80), (10, 200, 150)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=300, total_remaining=230,
        total_orig_prize_value=Decimal("6000"),
        top_prizes_original=5, top_prizes_remaining=3,
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)
    ratio_after_first = snap.estimated_payout_ratio
    launch_ev_after_first = snap.launch_ev
    pct_after_first = snap.remaining_prize_value_pct

    compute_snapshot_metrics(session)

    assert snap.estimated_payout_ratio == ratio_after_first
    assert snap.launch_ev == launch_ev_after_first
    assert snap.remaining_prize_value_pct == pct_after_first


def test_compute_metrics_clears_stale_odds_metrics_when_odds_removed(
    session: Session,
):
    tiers = [(1000, 5, 3), (10, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=105, total_remaining=83,
        total_orig_prize_value=Decimal("6000"),
        top_prizes_original=5, top_prizes_remaining=3,
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)
    assert game.est_total_tickets is not None
    assert snap.estimated_tickets_remaining is not None
    assert snap.estimated_ev is not None
    assert snap.estimated_ev_excluding_top_prize is not None
    assert snap.estimated_payout_ratio is not None
    assert snap.estimated_house_edge is not None
    assert snap.estimated_payout_ratio_excluding_top_prize is not None
    assert snap.launch_ev is not None
    assert snap.launch_payout_ratio is not None
    assert snap.ev_vs_launch_ratio is not None

    game.overall_odds_one_in = None
    result = compute_snapshot_metrics(session)

    assert result.snapshots_skipped_no_odds == 1
    assert game.est_total_tickets is None
    assert snap.estimated_tickets_remaining is None
    assert snap.estimated_ev is None
    assert snap.estimated_ev_excluding_top_prize is None
    assert snap.estimated_payout_ratio is None
    assert snap.estimated_house_edge is None
    assert snap.estimated_payout_ratio_excluding_top_prize is None
    assert snap.launch_ev is None
    assert snap.launch_payout_ratio is None
    assert snap.ev_vs_launch_ratio is None

    # Non-odds metrics still compute from raw totals.
    assert snap.remaining_prize_value_pct is not None
    assert snap.remaining_winning_tickets_pct is not None
    assert snap.top_prize_remaining_pct is not None
    assert snap.top_prize_depleted is False


def test_compute_metrics_clearing_stale_odds_metrics_is_idempotent(
    session: Session,
):
    tiers = [(50, 100, 80)]
    game = _game(session, odds=Decimal("4.0"), ticket_price=Decimal("5.00"))
    snap = _snapshot(
        session, game,
        total_orig=100, total_remaining=80,
        total_orig_prize_value=Decimal("5000"),
        top_prizes_original=1, top_prizes_remaining=0,
        prize_tiers=tiers,
    )

    compute_snapshot_metrics(session)
    game.overall_odds_one_in = None
    compute_snapshot_metrics(session)
    state_after_first_clear = (
        game.est_total_tickets,
        snap.estimated_tickets_remaining,
        snap.estimated_ev,
        snap.estimated_payout_ratio,
        snap.launch_ev,
        snap.top_prize_depleted,
    )

    compute_snapshot_metrics(session)

    assert (
        game.est_total_tickets,
        snap.estimated_tickets_remaining,
        snap.estimated_ev,
        snap.estimated_payout_ratio,
        snap.launch_ev,
        snap.top_prize_depleted,
    ) == state_after_first_clear
