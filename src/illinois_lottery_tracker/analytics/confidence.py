"""Wilson uncertainty and descriptive confidence/evidence labels."""

from __future__ import annotations

from decimal import Decimal, localcontext

from .types import (
    ConfidenceLabel,
    EvidenceLabel,
    WilsonAvailabilityInterval,
)

WILSON_Z = Decimal("1.959963984540054")


def wilson_availability_interval(
    *, claimed_count: int | Decimal, original_count: int, reference_remaining_fraction: Decimal
) -> WilsonAvailabilityInterval | None:
    if (
        original_count <= 0
        or not 0 <= claimed_count <= original_count
        or not Decimal(0) < reference_remaining_fraction <= Decimal(1)
    ):
        return None
    with localcontext() as context:
        context.prec = 50
        n = Decimal(original_count)
        phat = Decimal(claimed_count) / n
        z_squared = WILSON_Z * WILSON_Z
        denominator = Decimal(1) + z_squared / n
        center = (phat + z_squared / (Decimal(2) * n)) / denominator
        radicand = (
            phat * (Decimal(1) - phat) / n
            + z_squared / (Decimal(4) * n * n)
        )
        half_width = WILSON_Z / denominator * radicand.sqrt()
        claimed_lower = max(Decimal(0), center - half_width)
        claimed_upper = min(Decimal(1), center + half_width)
        remaining_lower = Decimal(1) - claimed_upper
        remaining_upper = Decimal(1) - claimed_lower
        return WilsonAvailabilityInterval(
            claimed_lower=claimed_lower,
            claimed_upper=claimed_upper,
            remaining_lower=remaining_lower,
            remaining_upper=remaining_upper,
            availability_lower=remaining_lower / reference_remaining_fraction,
            availability_upper=remaining_upper / reference_remaining_fraction,
        )


def information_count(
    original_count: int, reference_remaining_fraction: Decimal
) -> Decimal | None:
    if original_count <= 0 or not Decimal(0) <= reference_remaining_fraction <= Decimal(1):
        return None
    expected_remaining = Decimal(original_count) * reference_remaining_fraction
    expected_claimed = Decimal(original_count) * (
        Decimal(1) - reference_remaining_fraction
    )
    return min(expected_remaining, expected_claimed)


def classify_confidence(
    original_count: int, reference_remaining_fraction: Decimal
) -> ConfidenceLabel | None:
    information = information_count(original_count, reference_remaining_fraction)
    if information is None:
        return None
    if original_count < 20 or information < 5:
        return "lumpy"
    if information < 10:
        return "low"
    if information < 25:
        return "moderate"
    return "high"


def classify_evidence(
    *,
    interval: WilsonAvailabilityInterval | None,
    sensitivity_availabilities: list[Decimal],
    confidence: ConfidenceLabel | None,
) -> EvidenceLabel:
    if interval is None or confidence is None or not sensitivity_availabilities:
        return "unavailable"
    if confidence == "lumpy":
        return "indeterminate"
    if interval.availability_lower > 1 and all(
        value > 1 for value in sensitivity_availabilities
    ):
        return "favorable"
    if interval.availability_upper < 1 and all(
        value < 1 for value in sensitivity_availabilities
    ):
        return "unfavorable"
    return "indeterminate"
