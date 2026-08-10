"""Shared immutable value types for pure analytics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

PrizeGroup = Literal["baseline", "retail_gap", "high"]
ReferenceKind = Literal[
    "leave_one_tier_out", "current_full_baseline", "lagged_baseline", "unavailable"
]
MetricStatus = Literal["available", "depleted", "unavailable"]
AggregateStatus = Literal["complete", "partial", "unavailable", "not_applicable"]
ConfidenceLabel = Literal["lumpy", "low", "moderate", "high"]
EvidenceLabel = Literal["favorable", "unfavorable", "indeterminate", "unavailable"]


@dataclass(frozen=True)
class TierInput:
    prize_amount: Decimal
    original_count: int
    remaining_count: int
    is_top_prize: bool = False

    @property
    def claimed_count(self) -> int:
        return self.original_count - self.remaining_count


@dataclass(frozen=True)
class BaselineMetrics:
    status: Literal["available", "unavailable"]
    original_count: int
    remaining_count: int
    tier_count: int
    remaining_fraction: Decimal | None
    progress_fraction: Decimal | None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class TierScore:
    prize_amount: Decimal
    original_count: int
    remaining_count: int
    is_top_prize: bool
    prize_group: PrizeGroup
    reference_kind: ReferenceKind
    status: MetricStatus
    unavailable_reason: str | None
    absolute_unavailable_reason: str | None
    reference_remaining_fraction: Decimal | None
    reported_survival: Decimal | None
    availability_index: Decimal | None
    launch_probability: Decimal | None
    current_probability: Decimal | None
    launch_one_in: Decimal | None
    current_one_in: Decimal | None
    expected_reported_remaining: Decimal | None = None
    equivalent_current_remaining: Decimal | None = None


@dataclass(frozen=True)
class WilsonAvailabilityInterval:
    claimed_lower: Decimal
    claimed_upper: Decimal
    remaining_lower: Decimal
    remaining_upper: Decimal
    availability_lower: Decimal
    availability_upper: Decimal


@dataclass(frozen=True)
class LagSensitivity:
    point_availability: Decimal
    minimum_availability: Decimal
    maximum_availability: Decimal
    point_one_in: Decimal | None
    minimum_one_in: Decimal | None
    maximum_one_in: Decimal | None
    direction_changes: bool


@dataclass(frozen=True)
class AggregateMetric:
    status: AggregateStatus
    target_tier_count: int
    valid_tier_count: int
    count_coverage: Decimal | None
    value_coverage: Decimal | None
    current_probability: Decimal | None
    launch_probability: Decimal | None
    current_expected_value: Decimal | None
    launch_expected_value: Decimal | None
    current_one_in: Decimal | None
