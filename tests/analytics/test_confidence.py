from decimal import Decimal

from illinois_lottery_tracker.analytics.confidence import (
    classify_confidence,
    classify_evidence,
    information_count,
    wilson_availability_interval,
)


def test_wilson_interval_is_transformed_from_claimed_to_availability():
    interval = wilson_availability_interval(
        claimed_count=40,
        original_count=100,
        reference_remaining_fraction=Decimal("0.4"),
    )
    assert interval is not None
    assert Decimal(0) <= interval.claimed_lower < interval.claimed_upper <= Decimal(1)
    assert abs(
        interval.remaining_lower - (Decimal(1) - interval.claimed_upper)
    ) < Decimal("1e-27")
    assert interval.availability_lower > Decimal("1")


def test_information_and_confidence_boundaries_are_exact():
    assert information_count(100, Decimal("0.05")) == Decimal("5.00")
    assert classify_confidence(19, Decimal("0.5")) == "lumpy"
    assert classify_confidence(20, Decimal("0.25")) == "low"
    assert classify_confidence(40, Decimal("0.25")) == "moderate"
    assert classify_confidence(100, Decimal("0.25")) == "high"


def test_evidence_requires_interval_sensitivity_and_non_lumpy_confidence():
    favorable = wilson_availability_interval(
        claimed_count=40,
        original_count=100,
        reference_remaining_fraction=Decimal("0.4"),
    )
    unfavorable = wilson_availability_interval(
        claimed_count=90,
        original_count=100,
        reference_remaining_fraction=Decimal("0.4"),
    )
    assert classify_evidence(
        interval=favorable,
        sensitivity_availabilities=[Decimal("1.2"), Decimal("1.5"), Decimal("1.8")],
        confidence="high",
    ) == "favorable"
    assert classify_evidence(
        interval=unfavorable,
        sensitivity_availabilities=[Decimal("0.2"), Decimal("0.25"), Decimal("0.3")],
        confidence="high",
    ) == "unfavorable"
    assert classify_evidence(
        interval=favorable,
        sensitivity_availabilities=[Decimal("1.2")],
        confidence="lumpy",
    ) == "indeterminate"
