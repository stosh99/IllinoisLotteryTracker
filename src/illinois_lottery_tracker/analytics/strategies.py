"""Transparent sums over independently scored tier probabilities."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .types import AggregateMetric, TierScore


def aggregate_tiers(
    scores: list[TierScore], predicate: Callable[[TierScore], bool]
) -> AggregateMetric:
    targets = [score for score in scores if predicate(score)]
    if not targets:
        return AggregateMetric(
            status="not_applicable",
            target_tier_count=0,
            valid_tier_count=0,
            count_coverage=None,
            value_coverage=None,
            current_probability=None,
            launch_probability=None,
            current_expected_value=None,
            launch_expected_value=None,
            current_one_in=None,
        )
    valid = [
        score
        for score in targets
        if score.current_probability is not None and score.launch_probability is not None
    ]
    target_count = sum(score.original_count for score in targets)
    valid_count = sum(score.original_count for score in valid)
    target_value = sum(
        score.prize_amount * Decimal(score.original_count) for score in targets
    )
    valid_value = sum(
        score.prize_amount * Decimal(score.original_count) for score in valid
    )
    count_coverage = Decimal(valid_count) / Decimal(target_count) if target_count else None
    value_coverage = valid_value / target_value if target_value else None
    if not valid:
        status = "unavailable"
    elif len(valid) == len(targets):
        status = "complete"
    else:
        status = "partial"
    current_probability = sum(
        (score.current_probability for score in valid), start=Decimal(0)
    )
    launch_probability = sum(
        (score.launch_probability for score in valid), start=Decimal(0)
    )
    current_ev = sum(
        (
            score.prize_amount * score.current_probability
            for score in valid
            if score.current_probability is not None
        ),
        start=Decimal(0),
    )
    launch_ev = sum(
        (
            score.prize_amount * score.launch_probability
            for score in valid
            if score.launch_probability is not None
        ),
        start=Decimal(0),
    )
    return AggregateMetric(
        status=status,  # type: ignore[arg-type]
        target_tier_count=len(targets),
        valid_tier_count=len(valid),
        count_coverage=count_coverage,
        value_coverage=value_coverage,
        current_probability=current_probability if valid else None,
        launch_probability=launch_probability if valid else None,
        current_expected_value=current_ev if valid else None,
        launch_expected_value=launch_ev if valid else None,
        current_one_in=(
            Decimal(1) / current_probability if current_probability > 0 else None
        ) if valid else None,
    )
