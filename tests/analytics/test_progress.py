from decimal import Decimal

from illinois_lottery_tracker.analytics.progress import (
    compute_game_progress,
    estimated_original_ticket_count,
)
from illinois_lottery_tracker.analytics.types import TierInput


def tier(amount: str, original: int, remaining: int) -> TierInput:
    return TierInput(Decimal(amount), original, remaining)


def test_progress_is_count_weighted_not_mean_of_tier_percentages():
    result = compute_game_progress(
        [tier("5", 10_000, 5_000), tier("500", 30_000, 3_000)]
    )

    assert result.status == "available"
    assert result.remaining_fraction == Decimal("0.2")
    assert result.progress_fraction == Decimal("0.8")


def test_baseline_boundary_includes_exactly_600_but_not_above():
    result = compute_game_progress(
        [tier("600", 10_000, 8_000), tier("600.01", 100_000, 0)],
        minimum_tiers=1,
    )
    assert result.original_count == 10_000
    assert result.remaining_fraction == Decimal("0.8")


def test_baseline_requires_two_tiers_and_ten_thousand_originals():
    too_few_tiers = compute_game_progress([tier("10", 20_000, 10_000)])
    too_few_counts = compute_game_progress(
        [tier("5", 4_000, 2_000), tier("10", 5_999, 3_000)]
    )
    assert too_few_tiers.unavailable_reason == "INSUFFICIENT_BASELINE_TIERS"
    assert too_few_counts.unavailable_reason == "INSUFFICIENT_BASELINE_ORIGINALS"


def test_estimated_original_ticket_count_uses_all_winners_and_odds():
    tiers = [tier("5", 700, 500), tier("1000", 300, 200)]
    estimate, reason = estimated_original_ticket_count(tiers, Decimal("4"))
    assert estimate == Decimal("4000")
    assert reason is None
    assert estimated_original_ticket_count(tiers, None) == (
        None,
        "MISSING_OVERALL_ODDS",
    )
