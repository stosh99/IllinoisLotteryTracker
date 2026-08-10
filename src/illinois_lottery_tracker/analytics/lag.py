"""Pure adaptive-band, horizontal-shift, and equal-game lag estimators."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from .types import TierInput

PRIMARY_ORIGINAL_TARGET = 500
EXPLORATORY_ORIGINAL_TARGET = 250
MIN_SNAPSHOTS = 30
MIN_SPAN_DAYS = Decimal("30")
MIN_OVERLAP = Decimal("0.075")
INTERNAL_QUANTILES = 9
MAX_INTERPOLATION_GAP_DAYS = Decimal("3")
MIN_VALID_QUANTILES = 7
MIN_GLOBAL_GAMES = 8
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_808


@dataclass(frozen=True)
class AdaptiveBand:
    target_original_count: int
    eligible: bool
    ceiling: Decimal | None
    original_count: int
    prize_amounts: tuple[Decimal, ...]
    top_prize_amount: Decimal
    exclusion_reason: str | None


@dataclass(frozen=True)
class ProgressObservation:
    observed_at: datetime
    low_progress: Decimal
    high_progress: Decimal


@dataclass(frozen=True)
class GameLagEstimate:
    status: str
    exclusion_reason: str | None
    snapshot_count: int
    history_span_days: Decimal
    common_progress_lower: Decimal | None
    common_progress_upper: Decimal | None
    common_progress_width: Decimal | None
    valid_quantile_count: int
    median_lag_days: Decimal | None
    q1_lag_days: Decimal | None
    q3_lag_days: Decimal | None
    quantile_lag_days: tuple[Decimal, ...]


@dataclass(frozen=True)
class GlobalLagEstimate:
    status: str
    reason_code: str | None
    candidate_game_count: int
    qualified_game_count: int
    positive_game_count: int
    median_lag_days: Decimal | None
    q1_lag_days: Decimal | None
    q3_lag_days: Decimal | None
    bootstrap_lower_lag_days: Decimal | None
    bootstrap_upper_lag_days: Decimal | None


def select_adaptive_band(
    tiers: list[TierInput], *, target_original_count: int = PRIMARY_ORIGINAL_TARGET
) -> AdaptiveBand:
    if not tiers:
        raise ValueError("at least one tier is required")
    top_amount = max(tier.prize_amount for tier in tiers)
    candidates = sorted(
        (
            tier
            for tier in tiers
            if tier.prize_amount > 600 and tier.prize_amount != top_amount
        ),
        key=lambda tier: tier.prize_amount,
    )
    selected: list[TierInput] = []
    total = 0
    for tier in candidates:
        selected.append(tier)
        total += tier.original_count
        if total >= target_original_count:
            break
    eligible = total >= target_original_count
    return AdaptiveBand(
        target_original_count=target_original_count,
        eligible=eligible,
        ceiling=selected[-1].prize_amount if eligible else None,
        original_count=total,
        prize_amounts=tuple(tier.prize_amount for tier in selected) if eligible else (),
        top_prize_amount=top_amount,
        exclusion_reason=None if eligible else "INSUFFICIENT_HIGH_BAND_ORIGINALS",
    )


def fit_game_lag(
    observations: list[ProgressObservation],
    *,
    minimum_snapshots: int = MIN_SNAPSHOTS,
    minimum_span_days: Decimal = MIN_SPAN_DAYS,
    minimum_overlap: Decimal = MIN_OVERLAP,
    internal_quantiles: int = INTERNAL_QUANTILES,
    maximum_gap_days: Decimal = MAX_INTERPOLATION_GAP_DAYS,
    minimum_valid_quantiles: int = MIN_VALID_QUANTILES,
) -> GameLagEstimate:
    ordered = sorted(observations, key=lambda item: item.observed_at)
    snapshot_count = len({item.observed_at for item in ordered})
    span = (
        _duration_days(ordered[-1].observed_at - ordered[0].observed_at)
        if len(ordered) >= 2
        else Decimal(0)
    )
    if snapshot_count < minimum_snapshots:
        return _excluded(snapshot_count, span, "INSUFFICIENT_SNAPSHOTS")
    if span < minimum_span_days:
        return _excluded(snapshot_count, span, "INSUFFICIENT_HISTORY_SPAN")
    low = [(item.observed_at, item.low_progress) for item in ordered]
    high = [(item.observed_at, item.high_progress) for item in ordered]
    if _has_reversal(low) or _has_reversal(high):
        return _excluded(snapshot_count, span, "PROGRESS_REVERSAL")
    q_low = max(low[0][1], high[0][1])
    q_high = min(low[-1][1], high[-1][1])
    width = q_high - q_low
    if width < minimum_overlap:
        return _excluded(
            snapshot_count,
            span,
            "INSUFFICIENT_COMMON_PROGRESS",
            q_low=q_low,
            q_high=q_high,
        )
    lag_values: list[Decimal] = []
    for index in range(1, internal_quantiles + 1):
        q = q_low + Decimal(index) * width / Decimal(internal_quantiles + 1)
        low_time = _first_crossing_days(low, q, maximum_gap_days)
        high_time = _first_crossing_days(high, q, maximum_gap_days)
        if low_time is not None and high_time is not None:
            lag_values.append(high_time - low_time)
    if len(lag_values) < minimum_valid_quantiles:
        return _excluded(
            snapshot_count,
            span,
            "INSUFFICIENT_VALID_QUANTILES",
            q_low=q_low,
            q_high=q_high,
            valid=len(lag_values),
        )
    return GameLagEstimate(
        status="available",
        exclusion_reason=None,
        snapshot_count=snapshot_count,
        history_span_days=span,
        common_progress_lower=q_low,
        common_progress_upper=q_high,
        common_progress_width=width,
        valid_quantile_count=len(lag_values),
        median_lag_days=_median(lag_values),
        q1_lag_days=_percentile(lag_values, Decimal("0.25")),
        q3_lag_days=_percentile(lag_values, Decimal("0.75")),
        quantile_lag_days=tuple(lag_values),
    )


def aggregate_global_lag(
    game_lag_days: list[Decimal],
    *,
    candidate_game_count: int | None = None,
    minimum_games: int = MIN_GLOBAL_GAMES,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> GlobalLagEstimate:
    qualified = len(game_lag_days)
    candidates = candidate_game_count if candidate_game_count is not None else qualified
    positive = sum(value > 0 for value in game_lag_days)
    if qualified < minimum_games:
        return _global_excluded(candidates, qualified, positive, "INSUFFICIENT_GAMES")
    if Decimal(positive) / Decimal(qualified) < Decimal("0.8"):
        return _global_excluded(candidates, qualified, positive, "INSUFFICIENT_POSITIVE_SHARE")
    rng = random.Random(bootstrap_seed)
    bootstrap_medians = [
        _median([rng.choice(game_lag_days) for _ in game_lag_days])
        for _ in range(bootstrap_samples)
    ]
    lower = _percentile(bootstrap_medians, Decimal("0.025"))
    upper = _percentile(bootstrap_medians, Decimal("0.975"))
    if lower <= 0:
        return GlobalLagEstimate(
            status="insufficient",
            reason_code="BOOTSTRAP_LOWER_NOT_POSITIVE",
            candidate_game_count=candidates,
            qualified_game_count=qualified,
            positive_game_count=positive,
            median_lag_days=_median(game_lag_days),
            q1_lag_days=_percentile(game_lag_days, Decimal("0.25")),
            q3_lag_days=_percentile(game_lag_days, Decimal("0.75")),
            bootstrap_lower_lag_days=lower,
            bootstrap_upper_lag_days=upper,
        )
    return GlobalLagEstimate(
        status="available",
        reason_code=None,
        candidate_game_count=candidates,
        qualified_game_count=qualified,
        positive_game_count=positive,
        median_lag_days=_median(game_lag_days),
        q1_lag_days=_percentile(game_lag_days, Decimal("0.25")),
        q3_lag_days=_percentile(game_lag_days, Decimal("0.75")),
        bootstrap_lower_lag_days=lower,
        bootstrap_upper_lag_days=upper,
    )


def leave_one_game_out_lag(
    game_lags: dict[int, Decimal], game_id: int, *, minimum_games: int = MIN_GLOBAL_GAMES
) -> tuple[Decimal | None, bool]:
    without = [lag for candidate_id, lag in game_lags.items() if candidate_id != game_id]
    if len(without) >= minimum_games:
        return _median(without), False
    if len(game_lags) >= minimum_games:
        return _median(list(game_lags.values())), True
    return None, False


def interpolate_progress_crossing(
    curve: list[tuple[datetime, Decimal]],
    progress: Decimal,
    *,
    maximum_gap_days: Decimal = MAX_INTERPOLATION_GAP_DAYS,
) -> Decimal | None:
    """Return an absolute Decimal day, refusing extrapolation and wide gaps."""
    return _first_crossing_days(curve, progress, maximum_gap_days)


def interpolate_curve_at_time(
    curve: list[tuple[datetime, Decimal]],
    target: datetime,
    *,
    maximum_gap_days: Decimal = MAX_INTERPOLATION_GAP_DAYS,
) -> Decimal | None:
    """Linearly interpolate a value at time without extrapolating or wide gaps."""
    ordered = sorted(curve, key=lambda item: item[0])
    for index, (observed_at, value) in enumerate(ordered):
        if observed_at == target:
            return value
        if index == 0:
            continue
        previous_at, previous_value = ordered[index - 1]
        if previous_at < target < observed_at:
            gap = _duration_days(observed_at - previous_at)
            if gap > maximum_gap_days:
                return None
            elapsed = _duration_days(target - previous_at)
            return previous_value + elapsed / gap * (value - previous_value)
    return None


def subtract_decimal_days(observed_at: datetime, lag_days: Decimal) -> datetime:
    """Subtract Decimal calendar days at microsecond precision without float math."""
    from datetime import timedelta

    microseconds = int(lag_days * Decimal(86_400_000_000))
    return observed_at - timedelta(microseconds=microseconds)


def _first_crossing_days(
    curve: list[tuple[datetime, Decimal]], q: Decimal, maximum_gap_days: Decimal
) -> Decimal | None:
    for index, (observed_at, progress) in enumerate(curve):
        if progress == q:
            return _datetime_days(observed_at)
        if index == 0:
            continue
        previous_time, previous_progress = curve[index - 1]
        if previous_progress < q < progress:
            gap = _duration_days(observed_at - previous_time)
            if gap > maximum_gap_days:
                return None
            proportion = (q - previous_progress) / (progress - previous_progress)
            return _datetime_days(previous_time) + proportion * gap
    return None


def _has_reversal(curve: list[tuple[datetime, Decimal]]) -> bool:
    return any(
        current[1] < previous[1]
        for previous, current in zip(curve, curve[1:], strict=False)
    )


def _datetime_days(value: datetime) -> Decimal:
    ordinal_days = value.toordinal() - 1
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    microseconds = (
        (ordinal_days * 86_400 + seconds) * 1_000_000 + value.microsecond
    )
    offset = value.utcoffset()
    if offset is not None:
        microseconds -= (
            (offset.days * 86_400 + offset.seconds) * 1_000_000 + offset.microseconds
        )
    return Decimal(microseconds) / Decimal(86_400_000_000)


def _duration_days(value) -> Decimal:
    microseconds = (
        (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
    )
    return Decimal(microseconds) / Decimal(86_400_000_000)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _percentile(values: list[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    with localcontext() as context:
        context.prec = 50
        position = Decimal(len(ordered) - 1) * quantile
        lower_index = int(position)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = position - Decimal(lower_index)
        return ordered[lower_index] + weight * (
            ordered[upper_index] - ordered[lower_index]
        )


def _excluded(
    snapshot_count: int,
    span: Decimal,
    reason: str,
    *,
    q_low: Decimal | None = None,
    q_high: Decimal | None = None,
    valid: int = 0,
) -> GameLagEstimate:
    return GameLagEstimate(
        status="insufficient",
        exclusion_reason=reason,
        snapshot_count=snapshot_count,
        history_span_days=span,
        common_progress_lower=q_low,
        common_progress_upper=q_high,
        common_progress_width=(
            q_high - q_low if q_low is not None and q_high is not None else None
        ),
        valid_quantile_count=valid,
        median_lag_days=None,
        q1_lag_days=None,
        q3_lag_days=None,
        quantile_lag_days=(),
    )


def _global_excluded(
    candidates: int, qualified: int, positive: int, reason: str
) -> GlobalLagEstimate:
    return GlobalLagEstimate(
        status="insufficient",
        reason_code=reason,
        candidate_game_count=candidates,
        qualified_game_count=qualified,
        positive_game_count=positive,
        median_lag_days=None,
        q1_lag_days=None,
        q3_lag_days=None,
        bootstrap_lower_lag_days=None,
        bootstrap_upper_lag_days=None,
    )
