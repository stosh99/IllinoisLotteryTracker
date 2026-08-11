from decimal import Decimal

from illinois_lottery_tracker.analytics.progress import compute_game_progress
from illinois_lottery_tracker.analytics.tiers import (
    classify_prize_group,
    score_high_tier,
    score_regular_tier,
)
from illinois_lottery_tracker.analytics.types import TierInput


def test_regular_vector_uses_leave_one_tier_out_reference():
    target = TierInput(Decimal("100"), 100, 55)
    other = TierInput(Decimal("10"), 900, 360)
    baseline = compute_game_progress(
        [target, other], minimum_originals=0, minimum_tiers=2
    )

    score = score_regular_tier(
        target,
        baseline=baseline,
        total_original_winners=1000,
        overall_odds_one_in=Decimal("4"),
        minimum_reference_originals=0,
    )

    assert score.reference_kind == "leave_one_tier_out"
    assert score.reference_remaining_fraction == Decimal("0.4")
    assert score.availability_index == Decimal("1.375")
    assert score.launch_probability == Decimal("0.025")
    assert score.current_probability == Decimal("0.034375")
    assert score.launch_one_in == Decimal("40")
    assert score.current_one_in.quantize(Decimal("0.000001")) == Decimal("29.090909")


def test_600_boundary_is_ordinary_and_above_600_is_high():
    baseline_tiers = [
        TierInput(Decimal("5"), 10_000, 5_000),
        TierInput(Decimal("500"), 10_000, 4_000),
    ]
    baseline = compute_game_progress(baseline_tiers)
    over_600 = score_regular_tier(
        TierInput(Decimal("600.01"), 1_000, 500),
        baseline=baseline,
        total_original_winners=30_000,
        overall_odds_one_in=Decimal("4"),
    )
    assert classify_prize_group(Decimal("500")) == "baseline"
    assert baseline.status == "available"
    assert classify_prize_group(Decimal("600")) == "baseline"
    assert classify_prize_group(Decimal("600.01")) == "high"
    assert over_600.unavailable_reason == "HIGH_TIER_ADJUSTMENT_REQUIRED"


def test_missing_odds_retains_relative_score_but_nulls_absolute_outputs():
    target = TierInput(Decimal("10"), 20_000, 10_000)
    baseline = compute_game_progress(
        [target, TierInput(Decimal("20"), 20_000, 8_000)]
    )
    score = score_regular_tier(
        target,
        baseline=baseline,
        total_original_winners=40_000,
        overall_odds_one_in=None,
    )
    assert score.availability_index == Decimal("1.25")
    assert score.absolute_unavailable_reason == "MISSING_OVERALL_ODDS"
    assert score.current_probability is None
    assert score.current_one_in is None


def test_depleted_tier_has_zero_probability_and_no_infinite_odds():
    target = TierInput(Decimal("10"), 20_000, 0)
    baseline = compute_game_progress(
        [target, TierInput(Decimal("20"), 20_000, 8_000)]
    )
    score = score_regular_tier(
        target,
        baseline=baseline,
        total_original_winners=40_000,
        overall_odds_one_in=Decimal("4"),
    )
    assert score.status == "depleted"
    assert score.availability_index == 0
    assert score.current_probability == 0
    assert score.current_one_in is None


def test_high_tier_uses_adjusted_count_against_current_ordinary_progress():
    score = score_high_tier(
        TierInput(Decimal("1000"), 200, 100),
        effective_remaining_count=Decimal("75"),
        current_baseline_remaining_fraction=Decimal("0.30"),
        total_original_winners=1_000_000,
        overall_odds_one_in=Decimal("4"),
    )
    assert score.availability_index == Decimal("1.25")
    assert score.current_probability == Decimal("0.0000625")
    assert score.current_one_in == Decimal("16000.00")
    assert score.effective_remaining_count == Decimal("75")


def test_high_tier_without_current_ordinary_progress_is_unavailable():
    score = score_high_tier(
        TierInput(Decimal("1000"), 200, 100),
        effective_remaining_count=Decimal("100"),
        current_baseline_remaining_fraction=None,
        total_original_winners=1_000_000,
        overall_odds_one_in=Decimal("4"),
    )
    assert score.status == "unavailable"
    assert score.unavailable_reason == "CURRENT_BASELINE_NOT_AVAILABLE"
