from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from illinois_lottery_tracker.analytics.lag import (
    ProgressObservation,
    aggregate_global_lag,
    fit_game_lag,
    interpolate_progress_crossing,
    leave_one_game_out_lag,
    select_adaptive_band,
)
from illinois_lottery_tracker.analytics.types import TierInput


def test_adaptive_band_vector_excludes_top_and_stops_at_500_originals():
    tiers = [
        TierInput(Decimal("700"), 100, 100),
        TierInput(Decimal("1000"), 450, 450),
        TierInput(Decimal("5000"), 20, 20),
        TierInput(Decimal("100000"), 5, 5, is_top_prize=True),
    ]
    band = select_adaptive_band(tiers)
    assert band.eligible is True
    assert band.ceiling == Decimal("1000")
    assert band.original_count == 550
    assert band.prize_amounts == (Decimal("700"), Decimal("1000"))
    assert Decimal("5000") not in band.prize_amounts
    assert band.top_prize_amount == Decimal("100000")


def test_synthetic_five_day_horizontal_shift_returns_five_days():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = [
        ProgressObservation(
            observed_at=start + timedelta(days=index),
            low_progress=Decimal(index) / Decimal(100),
            high_progress=Decimal(max(index - 5, 0)) / Decimal(100),
        )
        for index in range(40)
    ]
    result = fit_game_lag(observations)
    assert result.status == "available"
    assert result.valid_quantile_count == 9
    assert abs(result.median_lag_days - Decimal("5")) < Decimal("1e-20")


def test_four_day_gap_rejects_interpolated_crossing():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    curve = [
        (start, Decimal("0")),
        (start + timedelta(days=4), Decimal("0.2")),
    ]
    assert interpolate_progress_crossing(curve, Decimal("0.1")) is None


def test_crossing_never_extrapolates_before_first_or_after_last_observation():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    curve = [
        (start, Decimal("0.2")),
        (start + timedelta(days=1), Decimal("0.3")),
    ]
    assert interpolate_progress_crossing(curve, Decimal("0.1")) is None
    assert interpolate_progress_crossing(curve, Decimal("0.4")) is None


def test_progress_reversal_excludes_game():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = [
        ProgressObservation(
            observed_at=start + timedelta(days=index),
            low_progress=(Decimal(index) / 100 if index != 20 else Decimal("0.10")),
            high_progress=Decimal(max(index - 5, 0)) / 100,
        )
        for index in range(40)
    ]
    assert fit_game_lag(observations).exclusion_reason == "PROGRESS_REVERSAL"


def test_global_lag_is_equal_game_median_with_deterministic_bootstrap():
    values = [Decimal(value) for value in (18, 19, 20, 21, 24, 27, 29, 30, 31)]
    first = aggregate_global_lag(values, bootstrap_samples=1000)
    second = aggregate_global_lag(values, bootstrap_samples=1000)
    assert first.status == "available"
    assert first.median_lag_days == Decimal("24")
    assert first.bootstrap_lower_lag_days == second.bootstrap_lower_lag_days
    assert first.bootstrap_upper_lag_days == second.bootstrap_upper_lag_days


def test_leave_one_game_out_requires_eight_other_games():
    lags = {index: Decimal(index + 20) for index in range(9)}
    lag, includes = leave_one_game_out_lag(lags, 0)
    assert lag == Decimal("24.5")
    assert includes is False
    lag, includes = leave_one_game_out_lag(dict(list(lags.items())[:8]), 0)
    assert lag == Decimal("23.5")
    assert includes is True
