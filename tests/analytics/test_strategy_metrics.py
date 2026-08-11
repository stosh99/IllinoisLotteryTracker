from decimal import Decimal

from illinois_lottery_tracker.analytics.strategies import aggregate_tiers
from illinois_lottery_tracker.analytics.types import TierScore


def test_excluding_top_equals_full_minus_exactly_the_top_tier():
    scores = [_score("5", "0.10"), _score("100", "0.02"), _score("1000", "0.001", top=True)]
    full = aggregate_tiers(scores, lambda score: True)
    ex_top = aggregate_tiers(scores, lambda score: not score.is_top_prize)
    top = aggregate_tiers(scores, lambda score: score.is_top_prize)
    assert full.status == ex_top.status == top.status == "complete"
    assert full.current_probability == ex_top.current_probability + top.current_probability
    assert full.current_expected_value == (
        ex_top.current_expected_value + top.current_expected_value
    )


def test_multiplier_and_fixed_dollar_predicates_include_boundaries():
    scores = [
        _score("49.99", "0.1"),
        _score("50", "0.2"),
        _score("100", "0.3"),
        _score("1000", "0.4"),
        _score("1000.01", "0.5"),
    ]
    ten_x = aggregate_tiers(scores, lambda score: score.prize_amount >= Decimal("5") * 10)
    fixed = aggregate_tiers(
        scores, lambda score: Decimal("100") <= score.prize_amount <= Decimal("1000")
    )
    assert ten_x.current_probability == Decimal("1.4")
    assert fixed.current_probability == Decimal("0.7")


def _score(amount: str, probability: str, *, top: bool = False) -> TierScore:
    value = Decimal(probability)
    return TierScore(
        prize_amount=Decimal(amount),
        original_count=100,
        remaining_count=50,
        effective_remaining_count=Decimal(50),
        is_top_prize=top,
        prize_group="high" if Decimal(amount) > 600 else "baseline",
        reference_kind=(
            "current_full_baseline" if Decimal(amount) > 600 else "leave_one_tier_out"
        ),
        status="available",
        unavailable_reason=None,
        absolute_unavailable_reason=None,
        reference_remaining_fraction=Decimal("0.5"),
        reported_survival=Decimal("0.5"),
        availability_index=Decimal("1"),
        launch_probability=value,
        current_probability=value,
        launch_one_in=Decimal(1) / value,
        current_one_in=Decimal(1) / value,
    )
