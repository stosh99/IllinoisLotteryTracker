from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from illinois_lottery_tracker.analytics.high_prize_adjustment import (
    CLAIM_REPORTING_LAG_DAYS,
    ProgressPoint,
    adjust_high_prize_tier,
    is_adjustment_eligible,
    lagged_target,
    progress_at,
)
from illinois_lottery_tracker.analytics.types import TierInput


def tier(amount: str, original: int = 300, remaining: int = 100) -> TierInput:
    return TierInput(Decimal(amount), original, remaining)


def test_eligibility_is_strictly_above_600_and_at_least_300_originals():
    assert is_adjustment_eligible(tier("600.01"))
    assert not is_adjustment_eligible(tier("600"))
    assert not is_adjustment_eligible(tier("1000", original=299))


def test_fixed_lag_subtracts_estimated_unreported_claims():
    result = adjust_high_prize_tier(
        tier("1000", original=300, remaining=120),
        current_progress_fraction=Decimal("0.70"),
        lagged_progress_fraction=Decimal("0.65"),
    )

    assert result.eligible
    assert result.status == "applied"
    assert result.estimated_pending_count == Decimal("15.00")
    assert result.adjusted_remaining_count == Decimal("105.00")
    assert result.lag_days_used == 24


def test_estimate_is_clamped_and_cannot_make_remaining_negative():
    result = adjust_high_prize_tier(
        tier("1000", original=300, remaining=2),
        current_progress_fraction=Decimal("0.8"),
        lagged_progress_fraction=Decimal("0.7"),
    )
    assert result.estimated_pending_count == 2
    assert result.adjusted_remaining_count == 0


def test_progress_reversal_never_adds_pending_claims():
    result = adjust_high_prize_tier(
        tier("1000"),
        current_progress_fraction=Decimal("0.5"),
        lagged_progress_fraction=Decimal("0.6"),
    )
    assert result.estimated_pending_count == 0
    assert result.adjusted_remaining_count == 100


def test_noneligible_and_missing_reference_keep_official_count_available():
    small = adjust_high_prize_tier(
        tier("1000", original=299),
        current_progress_fraction=Decimal("0.7"),
        lagged_progress_fraction=Decimal("0.6"),
    )
    missing = adjust_high_prize_tier(
        tier("1000"),
        current_progress_fraction=Decimal("0.7"),
        lagged_progress_fraction=None,
    )
    assert (small.status, small.adjusted_remaining_count) == ("reported_only", 100)
    assert (missing.status, missing.adjusted_remaining_count) == (
        "reference_unavailable",
        100,
    )


def test_progress_is_interpolated_at_exactly_24_days_before_observation():
    observed = datetime(2026, 8, 10, tzinfo=UTC)
    target = lagged_target(observed)
    points = [
        ProgressPoint(target - timedelta(days=2), Decimal("0.50")),
        ProgressPoint(target + timedelta(days=2), Decimal("0.60")),
        ProgressPoint(observed, Decimal("0.75")),
    ]
    assert CLAIM_REPORTING_LAG_DAYS == 24
    assert progress_at(points, target) == Decimal("0.550")


def test_before_launch_is_zero_but_an_unobserved_post_launch_span_is_unknown():
    launched = datetime(2026, 1, 10, tzinfo=UTC)
    first = launched + timedelta(days=10)
    points = [ProgressPoint(first, Decimal("0.1"))]
    assert progress_at(points, launched, game_started_at=launched) == 0
    assert progress_at(
        points, launched + timedelta(days=5), game_started_at=launched
    ) is None


def test_invalid_progress_is_rejected():
    with pytest.raises(ValueError):
        adjust_high_prize_tier(
            tier("1000"),
            current_progress_fraction=Decimal("1.1"),
            lagged_progress_fraction=Decimal("0.5"),
        )
