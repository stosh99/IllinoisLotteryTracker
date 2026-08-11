"""Non-circular regular-tier and supplied-reference high-tier scoring."""

from __future__ import annotations

from decimal import Decimal

from .progress import MIN_BASELINE_ORIGINALS
from .types import BaselineMetrics, PrizeGroup, TierInput, TierScore

BASELINE_MAX_PRIZE = Decimal("600")
HIGH_MIN_EXCLUSIVE = Decimal("600")


def classify_prize_group(prize_amount: Decimal) -> PrizeGroup:
    if prize_amount <= BASELINE_MAX_PRIZE:
        return "baseline"
    return "high"


def score_regular_tier(
    tier: TierInput,
    *,
    baseline: BaselineMetrics,
    total_original_winners: int,
    overall_odds_one_in: Decimal | None,
    minimum_reference_originals: int = MIN_BASELINE_ORIGINALS,
) -> TierScore:
    group = classify_prize_group(tier.prize_amount)
    if group == "high":
        return _unavailable(tier, group, "HIGH_TIER_ADJUSTMENT_REQUIRED")
    invalid_reason = _tier_invalid_reason(tier)
    if invalid_reason:
        return _unavailable(tier, group, invalid_reason)
    if baseline.status != "available" or baseline.remaining_fraction is None:
        return _unavailable(
            tier, group, baseline.unavailable_reason or "BASELINE_NOT_AVAILABLE"
        )
    reference_original = baseline.original_count - tier.original_count
    reference_remaining = baseline.remaining_count - tier.remaining_count
    if baseline.tier_count - 1 < 1:
        return _unavailable(tier, group, "INSUFFICIENT_REFERENCE_TIERS")
    if reference_original < minimum_reference_originals:
        return _unavailable(tier, group, "INSUFFICIENT_REFERENCE_ORIGINALS")
    reference_fraction = Decimal(reference_remaining) / Decimal(reference_original)
    reference_kind = "leave_one_tier_out"
    return _score(
        tier,
        group=group,
        reference_kind=reference_kind,
        reference_fraction=reference_fraction,
        total_original_winners=total_original_winners,
        overall_odds_one_in=overall_odds_one_in,
    )


def score_high_tier(
    tier: TierInput,
    *,
    effective_remaining_count: Decimal,
    current_baseline_remaining_fraction: Decimal | None,
    total_original_winners: int,
    overall_odds_one_in: Decimal | None,
) -> TierScore:
    group = classify_prize_group(tier.prize_amount)
    if group != "high":
        return _unavailable(tier, group, "HIGH_TIER_SCORE_REQUIRES_PRIZE_ABOVE_600")
    invalid_reason = _tier_invalid_reason(tier)
    if invalid_reason:
        return _unavailable(tier, group, invalid_reason)
    if current_baseline_remaining_fraction is None:
        return _unavailable(tier, group, "CURRENT_BASELINE_NOT_AVAILABLE")
    if not Decimal(0) <= effective_remaining_count <= Decimal(tier.original_count):
        return _unavailable(tier, group, "INVALID_EFFECTIVE_REMAINING_COUNT")
    return _score(
        tier,
        group="high",
        reference_kind="current_full_baseline",
        reference_fraction=current_baseline_remaining_fraction,
        total_original_winners=total_original_winners,
        overall_odds_one_in=overall_odds_one_in,
        effective_remaining_count=effective_remaining_count,
    )


def _score(
    tier: TierInput,
    *,
    group: PrizeGroup,
    reference_kind: str,
    reference_fraction: Decimal,
    total_original_winners: int,
    overall_odds_one_in: Decimal | None,
    effective_remaining_count: Decimal | None = None,
) -> TierScore:
    if not (Decimal(0) < reference_fraction <= Decimal(1)):
        return _unavailable(tier, group, "INVALID_REFERENCE_REMAINING_FRACTION")
    effective = (
        Decimal(tier.remaining_count)
        if effective_remaining_count is None
        else effective_remaining_count
    )
    survival = effective / Decimal(tier.original_count)
    availability = survival / reference_fraction
    absolute_reason = None
    ticket_total: Decimal | None = None
    if overall_odds_one_in is None:
        absolute_reason = "MISSING_OVERALL_ODDS"
    elif overall_odds_one_in <= 1 or total_original_winners <= 0:
        absolute_reason = "INVALID_OVERALL_ODDS"
    else:
        ticket_total = Decimal(total_original_winners) * overall_odds_one_in
    launch_probability = (
        Decimal(tier.original_count) / ticket_total if ticket_total is not None else None
    )
    current_probability = (
        effective / (ticket_total * reference_fraction)
        if ticket_total is not None
        else None
    )
    launch_one_in = (
        ticket_total / Decimal(tier.original_count) if ticket_total is not None else None
    )
    current_one_in = (
        ticket_total * reference_fraction / effective
        if ticket_total is not None and effective > 0
        else None
    )
    return TierScore(
        prize_amount=tier.prize_amount,
        original_count=tier.original_count,
        remaining_count=tier.remaining_count,
        effective_remaining_count=effective,
        is_top_prize=tier.is_top_prize,
        prize_group=group,
        reference_kind=reference_kind,  # type: ignore[arg-type]
        status="depleted" if effective == 0 else "available",
        unavailable_reason=None,
        absolute_unavailable_reason=absolute_reason,
        reference_remaining_fraction=reference_fraction,
        reported_survival=survival,
        availability_index=availability,
        launch_probability=launch_probability,
        current_probability=current_probability,
        launch_one_in=launch_one_in,
        current_one_in=current_one_in,
    )


def _tier_invalid_reason(tier: TierInput) -> str | None:
    if tier.prize_amount <= 0:
        return "INVALID_PRIZE_AMOUNT"
    if tier.original_count <= 0 or not 0 <= tier.remaining_count <= tier.original_count:
        return "INVALID_TIER_COUNTS"
    return None


def _unavailable(tier: TierInput, group: PrizeGroup, reason: str) -> TierScore:
    return TierScore(
        prize_amount=tier.prize_amount,
        original_count=tier.original_count,
        remaining_count=tier.remaining_count,
        effective_remaining_count=Decimal(tier.remaining_count),
        is_top_prize=tier.is_top_prize,
        prize_group=group,
        reference_kind="unavailable",
        status="unavailable",
        unavailable_reason=reason,
        absolute_unavailable_reason=reason,
        reference_remaining_fraction=None,
        reported_survival=None,
        availability_index=None,
        launch_probability=None,
        current_probability=None,
        launch_one_in=None,
        current_one_in=None,
    )
