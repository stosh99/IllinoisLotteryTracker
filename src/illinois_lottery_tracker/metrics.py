"""Metrics calculations for Illinois Lottery instant-ticket snapshots.

Pure calculation functions are free of any database access. The updater
function ``compute_snapshot_metrics`` remains for transition audits. Nightly
imports call it with ``include_legacy=False`` and therefore write only direct
descriptive ratios, never the superseded all-winner-denominator estimates.

Fraction vs. percentage convention
-----------------------------------
All fields whose names end in ``_pct`` and all payout-ratio fields are stored
as **decimal fractions**, not percentages.  For example:

- ``remaining_prize_value_pct = 0.749`` means 74.9 % of the original prize
  value is still unclaimed.
- ``estimated_payout_ratio = 0.748`` means the game returns ~74.8 cents per
  dollar wagered at the current snapshot.

Ratios are never clamped — a value above 1.0 is preserved as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Game, GameSnapshot


def estimate_total_tickets(
    total_original_winning_tickets: int | None,
    overall_odds_one_in: Decimal | None,
) -> int | None:
    """Estimated total tickets in the print run.

    Formula: total_original_winning_tickets * overall_odds_one_in
    """
    if total_original_winning_tickets is None or overall_odds_one_in is None:
        return None
    return round(Decimal(total_original_winning_tickets) * overall_odds_one_in)


def estimate_remaining_tickets(
    total_remaining_winning_tickets: int | None,
    overall_odds_one_in: Decimal | None,
) -> int | None:
    """Estimated remaining ticket denominator for EV calculations.

    Formula: total_remaining_winning_tickets * overall_odds_one_in

    Derived from unclaimed-prize counts and published odds; not a direct count
    of unsold or physically in-circulation tickets.
    """
    if total_remaining_winning_tickets is None or overall_odds_one_in is None:
        return None
    return round(Decimal(total_remaining_winning_tickets) * overall_odds_one_in)


def estimate_ev(
    total_remaining_prize_value: Decimal | None,
    estimated_remaining_tickets: int | None,
) -> Decimal | None:
    """Estimated expected value per ticket at snapshot time.

    Formula: total_remaining_prize_value / estimated_remaining_tickets
    """
    if total_remaining_prize_value is None or not estimated_remaining_tickets:
        return None
    return total_remaining_prize_value / Decimal(estimated_remaining_tickets)


def estimate_ev_excluding_top_prize(
    prize_tiers: list[tuple[Decimal, int | None]],
    estimated_remaining_tickets: int | None,
) -> Decimal | None:
    """Estimated EV per ticket excluding the top prize tier.

    Args:
        prize_tiers: list of (prize_amount, remaining_count) for all tiers.
        estimated_remaining_tickets: denominator (all tickets, not just winning).

    Returns None when remaining tickets is zero/None, prize_tiers is empty,
    or no non-top tiers with a known remaining_count exist.
    """
    if not estimated_remaining_tickets or not prize_tiers:
        return None
    top_amount = max(pa for pa, _ in prize_tiers)
    non_top = [
        (pa, rc)
        for pa, rc in prize_tiers
        if pa != top_amount and rc is not None
    ]
    if not non_top:
        return None
    total = sum(pa * Decimal(rc) for pa, rc in non_top)
    return total / Decimal(estimated_remaining_tickets)


def estimate_payout_ratio(
    ev: Decimal | None,
    ticket_price: Decimal | None,
) -> Decimal | None:
    """Ratio of EV to ticket price. None when ev or ticket_price is None/zero."""
    if ev is None or not ticket_price:
        return None
    return ev / ticket_price


def estimate_house_edge(payout_ratio: Decimal | None) -> Decimal | None:
    """1 - payout_ratio. None when payout_ratio is None."""
    if payout_ratio is None:
        return None
    return Decimal("1") - payout_ratio


def estimate_launch_ev(
    total_original_prize_value: Decimal | None,
    est_total_tickets: int | None,
) -> Decimal | None:
    """EV per ticket at the time of launch (original prize pool / total print run)."""
    if total_original_prize_value is None or not est_total_tickets:
        return None
    return total_original_prize_value / Decimal(est_total_tickets)


def estimate_ev_vs_launch(
    estimated_ev: Decimal | None,
    launch_ev: Decimal | None,
) -> Decimal | None:
    """Current EV as a fraction of launch EV. None when either is None/zero."""
    if estimated_ev is None or not launch_ev:
        return None
    return estimated_ev / launch_ev


def estimate_remaining_pct(
    remaining: int | Decimal | None,
    original: int | Decimal | None,
) -> Decimal | None:
    """Return remaining / original as a decimal fraction (e.g. 0.75 means 75% remaining).

    Returns None when original is None or zero (division undefined).
    Returns None when remaining is None (source data absent).
    Ratios are not clamped — a value above 1.0 is preserved.
    """
    if remaining is None or not original:
        return None
    return Decimal(remaining) / Decimal(original)


def is_top_prize_depleted(
    top_prizes_remaining: int | None,
    top_prizes_original: int | None,
) -> bool | None:
    """Return whether all top prizes have been claimed.

    - True  when top_prizes_original > 0 and top_prizes_remaining == 0.
    - False when top_prizes_original > 0 and top_prizes_remaining > 0.
    - None  when top_prizes_original is None, zero, or top_prizes_remaining is None
             (depletion status is undefined when the original count is unknown).
    """
    if top_prizes_remaining is None or top_prizes_original is None or top_prizes_original == 0:
        return None
    return top_prizes_remaining == 0


@dataclass(frozen=True)
class MetricsResult:
    games_updated: int = 0
    snapshots_computed: int = 0
    snapshots_with_nonodds_metrics: int = 0
    snapshots_skipped_no_odds: int = 0
    snapshots_skipped_no_counts: int = 0
    issues: list[str] = field(default_factory=list)


def compute_snapshot_metrics(
    session: Session, *, include_legacy: bool = True
) -> MetricsResult:
    """Compute and persist snapshot metrics for all game snapshots.

    Non-odds metrics (pct fields, top_prize_depleted) are computed for every
    snapshot regardless of whether overall_odds_one_in is set.

    With ``include_legacy=True``, odds-dependent legacy metrics are computed only
    when overall_odds_one_in is present. When odds are absent, those fields are
    explicitly cleared to None so that previously computed values do not persist
    as stale data if game metadata is later retracted.

    ``include_legacy=False`` does not write or clear any legacy column. This is
    the canonical import/nightly mode; historical values remain intact for the
    one-release comparison window.

    Only writes computed metric columns. Never modifies raw observed counts or
    prize-tier data. Idempotent: running twice produces the same state.
    """
    games_updated = 0
    snapshots_computed = 0
    snapshots_with_nonodds_metrics = 0
    snapshots_skipped_no_odds = 0
    snapshots_skipped_no_counts = 0
    issues: list[str] = []

    all_games: dict[int, Game] = {
        g.id: g for g in session.scalars(select(Game))
    }

    snapshots: list[GameSnapshot] = list(
        session.scalars(
            select(GameSnapshot).options(selectinload(GameSnapshot.prize_tiers))
        )
    )

    # Track original winning tickets per game to compute est_total_tickets once.
    game_orig_tickets: dict[int, int] = {}

    for snapshot in snapshots:
        game = all_games.get(snapshot.game_id)

        # Non-odds-dependent metrics — always computed from raw totals.
        snapshot.remaining_prize_value_pct = estimate_remaining_pct(
            snapshot.total_remaining_prize_value, snapshot.total_original_prize_value
        )
        snapshot.remaining_winning_tickets_pct = estimate_remaining_pct(
            snapshot.total_remaining_winning_tickets, snapshot.total_original_winning_tickets
        )
        snapshot.top_prize_remaining_pct = estimate_remaining_pct(
            snapshot.top_prizes_remaining, snapshot.top_prizes_original
        )
        snapshot.top_prize_depleted = is_top_prize_depleted(
            snapshot.top_prizes_remaining, snapshot.top_prizes_original
        )
        snapshots_with_nonodds_metrics += 1

        if not include_legacy:
            if game is None or game.overall_odds_one_in is None:
                snapshots_skipped_no_odds += 1
            continue

        if game is None or game.overall_odds_one_in is None:
            # Explicitly clear all odds-dependent fields so stale values from a
            # previous run do not survive a metadata retraction.
            snapshot.estimated_tickets_remaining = None
            snapshot.estimated_ev = None
            snapshot.estimated_ev_excluding_top_prize = None
            snapshot.estimated_payout_ratio = None
            snapshot.estimated_house_edge = None
            snapshot.estimated_payout_ratio_excluding_top_prize = None
            snapshot.launch_ev = None
            snapshot.launch_payout_ratio = None
            snapshot.ev_vs_launch_ratio = None
            snapshots_skipped_no_odds += 1
            continue

        if snapshot.total_original_winning_tickets is not None:
            game_orig_tickets.setdefault(
                snapshot.game_id, snapshot.total_original_winning_tickets
            )

        est_remaining = estimate_remaining_tickets(
            snapshot.total_remaining_winning_tickets, game.overall_odds_one_in
        )
        if est_remaining is None:
            snapshots_skipped_no_counts += 1

        est_ev = estimate_ev(snapshot.total_remaining_prize_value, est_remaining)
        tier_pairs = [
            (tier.prize_amount, tier.remaining_count)
            for tier in snapshot.prize_tiers
        ]
        est_ev_ex_top = estimate_ev_excluding_top_prize(tier_pairs, est_remaining)

        # Per-snapshot est_total used for launch_ev (not stored; game-level tracked below).
        est_total = estimate_total_tickets(
            snapshot.total_original_winning_tickets, game.overall_odds_one_in
        )
        l_ev = estimate_launch_ev(snapshot.total_original_prize_value, est_total)

        snapshot.estimated_tickets_remaining = est_remaining
        snapshot.estimated_ev = est_ev
        snapshot.estimated_ev_excluding_top_prize = est_ev_ex_top
        snapshot.estimated_payout_ratio = estimate_payout_ratio(est_ev, game.ticket_price)
        snapshot.estimated_house_edge = estimate_house_edge(snapshot.estimated_payout_ratio)
        snapshot.estimated_payout_ratio_excluding_top_prize = estimate_payout_ratio(
            est_ev_ex_top, game.ticket_price
        )
        snapshot.launch_ev = l_ev
        snapshot.launch_payout_ratio = estimate_payout_ratio(l_ev, game.ticket_price)
        snapshot.ev_vs_launch_ratio = estimate_ev_vs_launch(est_ev, l_ev)
        snapshots_computed += 1

    # Update game-level est_total_tickets.  Clear it when odds are absent so
    # a previously computed value cannot outlive its odds metadata.
    for game_id, game in all_games.items() if include_legacy else ():
        if game.overall_odds_one_in is None:
            if game.est_total_tickets is not None:
                game.est_total_tickets = None
                games_updated += 1
        elif game_id in game_orig_tickets:
            est_total = estimate_total_tickets(
                game_orig_tickets[game_id], game.overall_odds_one_in
            )
            if game.est_total_tickets != est_total:
                game.est_total_tickets = est_total
                games_updated += 1

    return MetricsResult(
        games_updated=games_updated,
        snapshots_computed=snapshots_computed,
        snapshots_with_nonodds_metrics=snapshots_with_nonodds_metrics,
        snapshots_skipped_no_odds=snapshots_skipped_no_odds,
        snapshots_skipped_no_counts=snapshots_skipped_no_counts,
        issues=issues,
    )
