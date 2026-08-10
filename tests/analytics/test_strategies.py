from decimal import Decimal

from illinois_lottery_tracker.analytics.progress import compute_game_progress
from illinois_lottery_tracker.analytics.strategies import aggregate_tiers
from illinois_lottery_tracker.analytics.tiers import score_regular_tier
from illinois_lottery_tracker.analytics.types import TierInput


def _scores(with_missing_odds: bool = False):
    inputs = [
        TierInput(Decimal("5"), 20_000, 10_000),
        TierInput(Decimal("10"), 20_000, 8_000),
    ]
    baseline = compute_game_progress(inputs)
    return [
        score_regular_tier(
            tier,
            baseline=baseline,
            total_original_winners=40_000,
            overall_odds_one_in=(
                None if with_missing_odds and tier.prize_amount == 10 else Decimal("4")
            ),
        )
        for tier in inputs
    ]


def test_strategy_aggregate_sums_independent_tier_probabilities_and_ev():
    scores = _scores()
    aggregate = aggregate_tiers(scores, lambda score: True)
    assert aggregate.status == "complete"
    assert aggregate.current_probability == sum(
        score.current_probability for score in scores if score.current_probability is not None
    )
    assert aggregate.current_expected_value == sum(
        score.prize_amount * score.current_probability
        for score in scores
        if score.current_probability is not None
    )
    assert aggregate.current_one_in == Decimal(1) / aggregate.current_probability
    assert aggregate.count_coverage == Decimal(1)
    assert aggregate.value_coverage == Decimal(1)


def test_partial_aggregate_preserves_valid_sum_and_coverage_but_is_not_complete():
    aggregate = aggregate_tiers(_scores(with_missing_odds=True), lambda score: True)
    assert aggregate.status == "partial"
    assert aggregate.valid_tier_count == 1
    assert aggregate.count_coverage == Decimal("0.5")
    assert aggregate.value_coverage == Decimal("0.3333333333333333333333333333")


def test_empty_target_is_not_applicable():
    aggregate = aggregate_tiers(_scores(), lambda score: score.prize_amount > 1000)
    assert aggregate.status == "not_applicable"
    assert aggregate.current_probability is None
