"""Count-weighted baseline progress and ticket-total estimates."""

from __future__ import annotations

from decimal import Decimal

from .types import BaselineMetrics, TierInput

BASELINE_MAX_PRIZE = Decimal("500")
MIN_BASELINE_ORIGINALS = 10_000
MIN_BASELINE_TIERS = 2


def estimated_original_ticket_count(
    tiers: list[TierInput], overall_odds_one_in: Decimal | None
) -> tuple[Decimal | None, str | None]:
    """Return ``sum(original winners) * published overall odds``."""
    if overall_odds_one_in is None:
        return None, "MISSING_OVERALL_ODDS"
    if overall_odds_one_in <= 1:
        return None, "INVALID_OVERALL_ODDS"
    if any(not _valid_counts(tier) for tier in tiers):
        return None, "INVALID_TIER_COUNTS"
    return Decimal(sum(tier.original_count for tier in tiers)) * overall_odds_one_in, None


def compute_game_progress(
    tiers: list[TierInput],
    *,
    minimum_originals: int = MIN_BASELINE_ORIGINALS,
    minimum_tiers: int = MIN_BASELINE_TIERS,
) -> BaselineMetrics:
    baseline = [tier for tier in tiers if tier.prize_amount <= BASELINE_MAX_PRIZE]
    if any(not _valid_counts(tier) for tier in baseline):
        return _unavailable(baseline, "INVALID_TIER_COUNTS")
    original = sum(tier.original_count for tier in baseline)
    remaining = sum(tier.remaining_count for tier in baseline)
    if len(baseline) < minimum_tiers:
        return _unavailable(baseline, "INSUFFICIENT_BASELINE_TIERS")
    if original < minimum_originals:
        return _unavailable(baseline, "INSUFFICIENT_BASELINE_ORIGINALS")
    fraction = Decimal(remaining) / Decimal(original)
    return BaselineMetrics(
        status="available",
        original_count=original,
        remaining_count=remaining,
        tier_count=len(baseline),
        remaining_fraction=fraction,
        progress_fraction=Decimal(1) - fraction,
    )


def _valid_counts(tier: TierInput) -> bool:
    return (
        tier.prize_amount > 0
        and tier.original_count > 0
        and 0 <= tier.remaining_count <= tier.original_count
    )


def _unavailable(tiers: list[TierInput], reason: str) -> BaselineMetrics:
    return BaselineMetrics(
        status="unavailable",
        original_count=sum(max(tier.original_count, 0) for tier in tiers),
        remaining_count=sum(max(tier.remaining_count, 0) for tier in tiers),
        tier_count=len(tiers),
        remaining_fraction=None,
        progress_fraction=None,
        unavailable_reason=reason,
    )
