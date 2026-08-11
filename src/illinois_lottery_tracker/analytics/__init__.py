"""Pure, Decimal-based analytical primitives for the ticket model."""

from .confidence import (
    classify_confidence,
    classify_evidence,
    information_count,
    wilson_availability_interval,
)
from .high_prize_adjustment import adjust_high_prize_tier, is_adjustment_eligible
from .progress import compute_game_progress, estimated_original_ticket_count
from .strategies import aggregate_tiers
from .tiers import classify_prize_group, score_high_tier, score_regular_tier
from .types import (
    AggregateMetric,
    BaselineMetrics,
    TierInput,
    TierScore,
    WilsonAvailabilityInterval,
)

__all__ = [
    "AggregateMetric",
    "BaselineMetrics",
    "TierInput",
    "TierScore",
    "WilsonAvailabilityInterval",
    "aggregate_tiers",
    "classify_confidence",
    "classify_evidence",
    "classify_prize_group",
    "compute_game_progress",
    "adjust_high_prize_tier",
    "estimated_original_ticket_count",
    "information_count",
    "is_adjustment_eligible",
    "score_high_tier",
    "score_regular_tier",
    "wilson_availability_interval",
]
