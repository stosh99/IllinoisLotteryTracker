"""Simple mail-in claim adjustment for statistically stable high-prize tiers.

Illinois prizes above $600 are reported later than ordinary retailer-redemptions.
For sufficiently large tiers, this module removes the estimated claims that are
still in that reporting pipeline.  It deliberately contains no calibration,
model selection, promotion, or game-specific lag logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from .types import TierInput

ORDINARY_PRIZE_MAX = Decimal("600")
HIGH_PRIZE_MIN_EXCLUSIVE = Decimal("600")
MIN_HIGH_PRIZE_ORIGINALS = 300
CLAIM_REPORTING_LAG_DAYS = 24

AdjustmentStatus = Literal["applied", "reported_only", "reference_unavailable"]


@dataclass(frozen=True)
class ProgressPoint:
    observed_at: datetime
    progress_fraction: Decimal


@dataclass(frozen=True)
class HighPrizeAdjustment:
    eligible: bool
    status: AdjustmentStatus
    reported_remaining_count: int
    estimated_pending_count: Decimal
    adjusted_remaining_count: Decimal
    lag_days_used: int | None


def is_adjustment_eligible(tier: TierInput) -> bool:
    """Return whether a tier is large enough for the fixed-lag adjustment."""
    return (
        tier.prize_amount > HIGH_PRIZE_MIN_EXCLUSIVE
        and tier.original_count >= MIN_HIGH_PRIZE_ORIGINALS
    )


def adjust_high_prize_tier(
    tier: TierInput,
    *,
    current_progress_fraction: Decimal | None,
    lagged_progress_fraction: Decimal | None,
) -> HighPrizeAdjustment:
    """Estimate true remaining prizes after subtracting unreported claims.

    Non-eligible tiers and eligible tiers without a usable historical reference
    retain their official remaining count.  Missing adjustment data therefore
    never makes a tier, game, card, or ranking unavailable.
    """
    reported = Decimal(tier.remaining_count)
    if not is_adjustment_eligible(tier):
        return HighPrizeAdjustment(
            eligible=False,
            status="reported_only",
            reported_remaining_count=tier.remaining_count,
            estimated_pending_count=Decimal(0),
            adjusted_remaining_count=reported,
            lag_days_used=None,
        )
    if current_progress_fraction is None or lagged_progress_fraction is None:
        return HighPrizeAdjustment(
            eligible=True,
            status="reference_unavailable",
            reported_remaining_count=tier.remaining_count,
            estimated_pending_count=Decimal(0),
            adjusted_remaining_count=reported,
            lag_days_used=None,
        )
    _validate_progress(current_progress_fraction)
    _validate_progress(lagged_progress_fraction)
    newly_claimed_fraction = max(
        current_progress_fraction - lagged_progress_fraction, Decimal(0)
    )
    pending = min(Decimal(tier.original_count) * newly_claimed_fraction, reported)
    return HighPrizeAdjustment(
        eligible=True,
        status="applied",
        reported_remaining_count=tier.remaining_count,
        estimated_pending_count=pending,
        adjusted_remaining_count=reported - pending,
        lag_days_used=CLAIM_REPORTING_LAG_DAYS,
    )


def progress_at(
    points: Sequence[ProgressPoint],
    target: datetime,
    *,
    game_started_at: datetime | None = None,
) -> Decimal | None:
    """Linearly interpolate ordinary-tier progress at ``target``.

    A target on or before game launch is known to have zero progress.  A target
    in an unobserved span after launch is unknown and returns ``None``.
    """
    if game_started_at is not None and target <= game_started_at:
        return Decimal(0)
    ordered = sorted(points, key=lambda point: point.observed_at)
    if not ordered or target < ordered[0].observed_at or target > ordered[-1].observed_at:
        return None
    for point in ordered:
        _validate_progress(point.progress_fraction)
        if point.observed_at == target:
            return point.progress_fraction
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.observed_at < target < right.observed_at:
            span = Decimal(str((right.observed_at - left.observed_at).total_seconds()))
            elapsed = Decimal(str((target - left.observed_at).total_seconds()))
            weight = elapsed / span
            return left.progress_fraction + weight * (
                right.progress_fraction - left.progress_fraction
            )
    return None


def lagged_target(observed_at: datetime) -> datetime:
    return observed_at - timedelta(days=CLAIM_REPORTING_LAG_DAYS)


def _validate_progress(value: Decimal) -> None:
    if not Decimal(0) <= value <= Decimal(1):
        raise ValueError("progress fraction must be between zero and one")
