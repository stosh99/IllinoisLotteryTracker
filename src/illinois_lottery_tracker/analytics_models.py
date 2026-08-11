"""SQLAlchemy mappings for versioned, reproducible analytics results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .models import BIGINT_PRIMARY_KEY, Base

FRACTION = Numeric(18, 12)
AMOUNT = Numeric(24, 6)
ONE_IN = Numeric(30, 6)
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class AnalyticsModelVersion(Base):
    __tablename__ = "analytics_model_versions"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint(
            "model_name", "semantic_version", name="uq_analytics_model_name_version"
        ),
        CheckConstraint(
            "length(parameters_sha256) = 64",
            name="ck_analytics_model_versions_sha256",
        ),
    )


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    as_of_scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="RESTRICT"), nullable=False
    )
    as_of_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "as_of_scrape_run_id",
            name="uq_analytics_runs_model_cutoff",
        ),
        Index(
            "ix_analytics_runs_cutoff_status",
            "as_of_scrape_run_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_analytics_runs_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_analytics_runs_finished_after_started",
        ),
    )


class AnalyticsGameMetric(Base):
    __tablename__ = "analytics_game_metrics"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    game_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    structure_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    baseline_tier_count: Mapped[int | None] = mapped_column(Integer)
    baseline_original_count: Mapped[int | None] = mapped_column(BigInteger)
    baseline_remaining_count: Mapped[int | None] = mapped_column(BigInteger)
    baseline_claimed_count: Mapped[int | None] = mapped_column(BigInteger)
    baseline_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    progress_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    estimated_original_tickets: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimated_sold_tickets: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimated_remaining_tickets: Mapped[Decimal | None] = mapped_column(AMOUNT)
    published_overall_odds_one_in: Mapped[Decimal | None] = mapped_column(ONE_IN)
    full_score_count_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    full_score_value_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    high_score_count_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    high_score_value_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    prize_source_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    catalog_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recommendation_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    catalog_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_status: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_game_metrics_run_game"
        ),
        Index(
            "ix_analytics_game_metrics_run_status",
            "analytics_run_id",
            "data_status",
        ),
        CheckConstraint(
            "data_status IN ('complete', 'partial', 'unavailable')",
            name="ck_analytics_game_metrics_data_status",
        ),
    )


class AnalyticsTierMetric(Base):
    __tablename__ = "analytics_tier_metrics"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    game_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    prize_tier_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("prize_tier_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    is_top_prize: Mapped[bool] = mapped_column(Boolean, nullable=False)
    process_group: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_method: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjustment_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adjustment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    lag_days_used: Mapped[int | None] = mapped_column(Integer)
    current_baseline_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    reference_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    observed_survival_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    reported_remaining_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_pending_count: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    adjusted_remaining_count: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    availability_index: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_wilson_lower: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_wilson_upper: Mapped[Decimal | None] = mapped_column(FRACTION)
    launch_probability: Mapped[Decimal | None] = mapped_column(FRACTION)
    launch_one_in: Mapped[Decimal | None] = mapped_column(ONE_IN)
    current_probability: Mapped[Decimal | None] = mapped_column(FRACTION)
    current_one_in: Mapped[Decimal | None] = mapped_column(ONE_IN)
    confidence_label: Mapped[str | None] = mapped_column(String(16))
    information_count: Mapped[Decimal | None] = mapped_column(AMOUNT)
    evidence_classification: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint(
            "analytics_run_id",
            "prize_tier_snapshot_id",
            name="uq_analytics_tier_metrics_run_tier",
        ),
        Index("ix_analytics_tier_metrics_run_game", "analytics_run_id", "game_id"),
        CheckConstraint(
            "process_group IN ('baseline', 'high')",
            name="ck_analytics_tier_metrics_process_group",
        ),
        CheckConstraint(
            "reference_method IN ('leave_one_tier_out', 'current_baseline', 'unavailable')",
            name="ck_analytics_tier_metrics_reference_method",
        ),
        CheckConstraint(
            "adjustment_status IN ('applied', 'reported_only', 'reference_unavailable')",
            name="ck_analytics_tier_metrics_adjustment_status",
        ),
        CheckConstraint(
            "reported_remaining_count >= 0 AND estimated_pending_count >= 0 "
            "AND adjusted_remaining_count >= 0",
            name="ck_analytics_tier_metrics_adjustment_counts",
        ),
        CheckConstraint(
            "status IN ('available', 'depleted', 'unavailable')",
            name="ck_analytics_tier_metrics_status",
        ),
        CheckConstraint(
            "confidence_label IS NULL OR confidence_label IN "
            "('lumpy', 'low', 'moderate', 'high')",
            name="ck_analytics_tier_metrics_confidence",
        ),
        CheckConstraint(
            "evidence_classification IS NULL OR evidence_classification IN "
            "('favorable', 'unfavorable', 'indeterminate', 'unavailable')",
            name="ck_analytics_tier_metrics_evidence",
        ),
    )


class AnalyticsStrategyMetric(Base):
    __tablename__ = "analytics_strategy_metrics"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    ticket_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    p_any_win: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_break_even_exact: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_break_even_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_2x_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_strict_profit: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_strict_profit_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    profit_probability_vs_launch: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_5x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_10x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_20x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_50x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_100_to_1000_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_top_prize_estimated: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_1000_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_10000_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_100000_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)
    p_1000000_or_better: Mapped[Decimal | None] = mapped_column(FRACTION)

    one_in_any_win: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_break_even_exact: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_strict_profit_ex_top: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_5x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_10x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_top_prize_estimated: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_1000_or_better: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_10000_or_better: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_100000_or_better: Mapped[Decimal | None] = mapped_column(ONE_IN)

    ev_5x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(AMOUNT)
    ev_10x_or_better_ex_top: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimated_ev_full: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimated_ev_ex_top: Mapped[Decimal | None] = mapped_column(AMOUNT)
    launch_ev_full: Mapped[Decimal | None] = mapped_column(AMOUNT)
    launch_ev_ex_top: Mapped[Decimal | None] = mapped_column(AMOUNT)

    estimated_payout_ratio_full: Mapped[Decimal | None] = mapped_column(FRACTION)
    estimated_payout_ratio_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    estimated_house_edge_full: Mapped[Decimal | None] = mapped_column(FRACTION)
    estimated_house_edge_ex_top: Mapped[Decimal | None] = mapped_column(FRACTION)
    ev_full_vs_launch: Mapped[Decimal | None] = mapped_column(FRACTION)
    ev_ex_top_vs_launch: Mapped[Decimal | None] = mapped_column(FRACTION)
    top_availability_index: Mapped[Decimal | None] = mapped_column(FRACTION)
    full_count_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    full_value_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    ex_top_count_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    ex_top_value_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)

    top_prize_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    top_prizes_original_reported: Mapped[int | None] = mapped_column(BigInteger)
    top_prizes_remaining_reported: Mapped[int | None] = mapped_column(BigInteger)
    top_confidence: Mapped[str | None] = mapped_column(String(16))
    metric_statuses: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    metric_details: Mapped[dict] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict, server_default="{}"
    )
    lowest_confidence: Mapped[str | None] = mapped_column(String(16))
    contains_lumpy_tier: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_strategy_run_game"
        ),
    )


class AnalyticsQualityIssue(Base):
    __tablename__ = "analytics_quality_issues"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL")
    )
    game_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="SET NULL")
    )
    prize_tier_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("prize_tier_snapshots.id", ondelete="SET NULL")
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_analytics_quality_issues_run_severity_code",
            "analytics_run_id",
            "severity",
            "code",
        ),
        Index("ix_analytics_quality_issues_game_code", "game_id", "code"),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_analytics_quality_issues_severity",
        ),
        CheckConstraint(
            "entity_type IN ('run', 'game', 'snapshot', 'tier')",
            name="ck_analytics_quality_issues_entity_type",
        ),
    )
