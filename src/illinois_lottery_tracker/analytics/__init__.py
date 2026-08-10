"""Pure, Decimal-based analytical primitives for the ticket model."""

from .confidence import (
    classify_confidence,
    classify_evidence,
    compute_lag_sensitivity,
    information_count,
    wilson_availability_interval,
)
from .progress import compute_game_progress, estimated_original_ticket_count
from .strategies import aggregate_tiers
from .tiers import classify_prize_group, score_high_tier, score_regular_tier
from .types import (
    AggregateMetric,
    BaselineMetrics,
    LagSensitivity,
    TierInput,
    TierScore,
    WilsonAvailabilityInterval,
)

__all__ = [
    "AggregateMetric",
    "BaselineMetrics",
    "LagSensitivity",
    "TierInput",
    "TierScore",
    "WilsonAvailabilityInterval",
    "aggregate_tiers",
    "classify_confidence",
    "classify_evidence",
    "classify_prize_group",
    "compute_game_progress",
    "compute_lag_sensitivity",
    "estimated_original_ticket_count",
    "information_count",
    "score_high_tier",
    "score_regular_tier",
    "wilson_availability_interval",
]
