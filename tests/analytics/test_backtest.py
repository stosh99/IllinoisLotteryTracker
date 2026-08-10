from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from illinois_lottery_tracker.analytics.backtest import (
    assert_no_lookahead,
    choose_target_run,
    conditional_depletion_prediction,
    score_observation,
)


def test_conditional_depletion_equation_and_errors_are_decimal_exact():
    prediction = conditional_depletion_prediction(
        cutoff_remaining_count=100,
        original_count=200,
        cutoff_reference_fraction=Decimal("0.5"),
        target_reference_fraction=Decimal("0.4"),
    )
    scored = score_observation(prediction, 80, original_count=200)

    assert prediction.predicted_count == Decimal("80")
    assert prediction.predicted_fraction == Decimal("0.4")
    assert scored.signed_count_error == 0
    assert scored.absolute_fraction_error == 0
    assert scored.interval_contains_observed is True


def test_aligned_data_favors_aligned_over_zero_lag():
    aligned = conditional_depletion_prediction(
        cutoff_remaining_count=100,
        original_count=200,
        cutoff_reference_fraction=Decimal("0.8"),
        target_reference_fraction=Decimal("0.6"),
    )
    no_lag = conditional_depletion_prediction(
        cutoff_remaining_count=100,
        original_count=200,
        cutoff_reference_fraction=Decimal("0.7"),
        target_reference_fraction=Decimal("0.6"),
    )
    aligned_score = score_observation(aligned, 75, original_count=200)
    no_lag_score = score_observation(no_lag, 75, original_count=200)

    assert aligned_score.absolute_count_error == 0
    assert no_lag_score.absolute_count_error > 0


def test_zero_lag_data_does_not_falsely_favor_lag():
    aligned = conditional_depletion_prediction(
        cutoff_remaining_count=100,
        original_count=200,
        cutoff_reference_fraction=Decimal("0.8"),
        target_reference_fraction=Decimal("0.6"),
    )
    no_lag = conditional_depletion_prediction(
        cutoff_remaining_count=100,
        original_count=200,
        cutoff_reference_fraction=Decimal("0.75"),
        target_reference_fraction=Decimal("0.6"),
    )
    aligned_score = score_observation(aligned, 80, original_count=200)
    no_lag_score = score_observation(no_lag, 80, original_count=200)

    assert no_lag_score.absolute_count_error == 0
    assert aligned_score.absolute_count_error > 0


def test_no_lookahead_guard_rejects_deliberate_future_feature():
    cutoff = datetime(2026, 8, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="NO_LOOKAHEAD_VIOLATION"):
        assert_no_lookahead(cutoff, [cutoff, cutoff + timedelta(seconds=1)])


def test_target_selection_uses_nearest_complete_date_within_one_day():
    cutoff_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    cutoff = SimpleNamespace(id=1, source_observed_at=cutoff_at)
    runs = [
        cutoff,
        SimpleNamespace(id=2, source_observed_at=cutoff_at + timedelta(days=12, hours=23)),
        SimpleNamespace(id=3, source_observed_at=cutoff_at + timedelta(days=14, hours=12)),
    ]
    assert choose_target_run(cutoff, runs, 14).id == 3
    assert choose_target_run(cutoff, runs, 7) is None


def test_reference_reversal_is_excluded_instead_of_extrapolated():
    result = conditional_depletion_prediction(
        cutoff_remaining_count=50,
        original_count=100,
        cutoff_reference_fraction=Decimal("0.4"),
        target_reference_fraction=Decimal("0.41"),
    )
    assert result.eligibility_code == "REFERENCE_REVERSAL"
    assert result.predicted_count is None
