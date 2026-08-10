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
    approval_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="experimental", server_default="experimental"
    )
    approval_backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_backtest_runs.id", ondelete="RESTRICT"), nullable=True
    )
    approval_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_reason: Mapped[str | None] = mapped_column(Text)
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
        CheckConstraint(
            "approval_status IN ('experimental', 'approved', 'rejected')",
            name="ck_analytics_model_versions_approval_status",
        ),
        CheckConstraint(
            "approval_status <> 'approved' OR "
            "(approval_backtest_run_id IS NOT NULL AND approval_decided_at IS NOT NULL "
            "AND approval_reason IS NOT NULL)",
            name="ck_analytics_model_versions_approved_evidence",
        ),
        Index(
            "uq_analytics_model_versions_one_approved",
            "model_name",
            unique=True,
            postgresql_where=(approval_status == "approved"),
            sqlite_where=(approval_status == "approved"),
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
    publishable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
            "publishable",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_analytics_runs_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_analytics_runs_finished_after_started",
        ),
        CheckConstraint(
            "NOT publishable OR status = 'success'",
            name="ck_analytics_runs_publishable_success",
        ),
    )


class AnalyticsLagCalibration(Base):
    __tablename__ = "analytics_lag_calibrations"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_original_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exploratory_original_count: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_snapshots: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_span_days: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_overlap_fraction: Mapped[Decimal] = mapped_column(FRACTION, nullable=False)
    internal_quantile_count: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_interpolation_gap_days: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_qualified_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exploratory_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    global_median_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    global_q1_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    global_q3_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    bootstrap_lower_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    bootstrap_upper_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(
            "status IN ('available', 'insufficient', 'failed')",
            name="ck_analytics_lag_calibrations_status",
        ),
        CheckConstraint(
            "candidate_game_count >= 0 AND primary_qualified_game_count >= 0 "
            "AND exploratory_game_count >= 0 AND positive_game_count >= 0 "
            "AND excluded_game_count >= 0",
            name="ck_analytics_lag_calibrations_counts",
        ),
    )


class AnalyticsLagGameEstimate(Base):
    __tablename__ = "analytics_lag_game_estimates"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    analytics_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    eligible_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligible_exploratory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_code: Mapped[str | None] = mapped_column(String(64))
    top_prize_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    adaptive_high_band_ceiling: Mapped[Decimal | None] = mapped_column(AMOUNT)
    selected_high_band_original_count: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_count: Mapped[int | None] = mapped_column(Integer)
    history_span_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    common_progress_lower: Mapped[Decimal | None] = mapped_column(FRACTION)
    common_progress_upper: Mapped[Decimal | None] = mapped_column(FRACTION)
    common_progress_width: Mapped[Decimal | None] = mapped_column(FRACTION)
    valid_quantile_count: Mapped[int | None] = mapped_column(Integer)
    median_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    q1_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    q3_lag_days: Mapped[Decimal | None] = mapped_column(FRACTION)
    used_in_global: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_lag_game_run_game"
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
    publishable: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_game_metrics_run_game"
        ),
        Index(
            "ix_analytics_game_metrics_run_status",
            "analytics_run_id",
            "data_status",
            "publishable",
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
    lag_days_used: Mapped[Decimal | None] = mapped_column(FRACTION)
    lag_includes_scored_game: Mapped[bool | None] = mapped_column(Boolean)
    current_baseline_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    reference_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    observed_survival_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    expected_reported_remaining: Mapped[Decimal | None] = mapped_column(AMOUNT)
    availability_index: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_wilson_lower: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_wilson_upper: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_sensitivity_min: Mapped[Decimal | None] = mapped_column(FRACTION)
    availability_sensitivity_max: Mapped[Decimal | None] = mapped_column(FRACTION)
    one_in_sensitivity_min: Mapped[Decimal | None] = mapped_column(ONE_IN)
    one_in_sensitivity_max: Mapped[Decimal | None] = mapped_column(ONE_IN)
    lag_sensitivity_direction_changes: Mapped[bool | None] = mapped_column(Boolean)
    launch_probability: Mapped[Decimal | None] = mapped_column(FRACTION)
    launch_one_in: Mapped[Decimal | None] = mapped_column(ONE_IN)
    current_probability: Mapped[Decimal | None] = mapped_column(FRACTION)
    current_one_in: Mapped[Decimal | None] = mapped_column(ONE_IN)
    equivalent_current_remaining: Mapped[Decimal | None] = mapped_column(AMOUNT)
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
            "process_group IN ('baseline', 'retail_gap', 'high')",
            name="ck_analytics_tier_metrics_process_group",
        ),
        CheckConstraint(
            "reference_method IN ('leave_one_tier_out', 'current_baseline', "
            "'lagged_baseline', 'unavailable')",
            name="ck_analytics_tier_metrics_reference_method",
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


class AnalyticsBacktestRun(Base):
    __tablename__ = "analytics_backtest_runs"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    cutoff_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cutoff_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    horizons: Mapped[list[int]] = mapped_column(JSON_DOCUMENT, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    aggregate_results: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    promotion_status: Mapped[str] = mapped_column(String(16), nullable=False)
    promotion_report: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "parameters_sha256",
            name="uq_analytics_backtest_model_parameters",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_analytics_backtest_runs_status",
        ),
        CheckConstraint(
            "promotion_status IN ('pending', 'passed', 'failed')",
            name="ck_analytics_backtest_runs_promotion_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_analytics_backtest_runs_finished_after_started",
        ),
    )


class AnalyticsBacktestPrediction(Base):
    __tablename__ = "analytics_backtest_predictions"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_backtest_runs.id", ondelete="CASCADE"), nullable=False
    )
    cutoff_scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="RESTRICT"), nullable=False
    )
    target_scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="RESTRICT")
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    cutoff_game_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    target_game_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="RESTRICT")
    )
    prize_amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    original_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cutoff_remaining_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    model_variant: Mapped[str] = mapped_column(String(16), nullable=False)
    process_group: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_label: Mapped[str | None] = mapped_column(String(16))
    ticket_price_group: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_cohort: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff_inputs: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    predicted_remaining_count: Mapped[Decimal | None] = mapped_column(AMOUNT)
    predicted_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    prediction_lower_count: Mapped[Decimal | None] = mapped_column(AMOUNT)
    prediction_upper_count: Mapped[Decimal | None] = mapped_column(AMOUNT)
    observed_remaining_count: Mapped[int | None] = mapped_column(BigInteger)
    observed_remaining_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    signed_count_error: Mapped[Decimal | None] = mapped_column(AMOUNT)
    absolute_count_error: Mapped[Decimal | None] = mapped_column(AMOUNT)
    signed_fraction_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    absolute_fraction_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    standardized_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    interval_contains_observed: Mapped[bool | None] = mapped_column(Boolean)
    eligibility_code: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id",
            "cutoff_scrape_run_id",
            "game_id",
            "prize_amount",
            "horizon_days",
            "model_variant",
            name="uq_analytics_backtest_prediction_identity",
        ),
        Index(
            "ix_analytics_backtest_prediction_summary",
            "backtest_run_id",
            "horizon_days",
            "model_variant",
        ),
        Index(
            "ix_analytics_backtest_prediction_tier",
            "game_id",
            "prize_amount",
            "cutoff_scrape_run_id",
        ),
        CheckConstraint(
            "model_variant IN ('aligned', 'no_lag', 'legacy')",
            name="ck_analytics_backtest_predictions_variant",
        ),
        CheckConstraint(
            "process_group IN ('baseline', 'retail_gap', 'high')",
            name="ck_analytics_backtest_predictions_process_group",
        ),
        CheckConstraint(
            "horizon_days IN (7, 14, 30)",
            name="ck_analytics_backtest_predictions_horizon",
        ),
    )


class AnalyticsBacktestSummary(Base):
    __tablename__ = "analytics_backtest_summaries"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_backtest_runs.id", ondelete="CASCADE"), nullable=False
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    model_variant: Mapped[str] = mapped_column(String(16), nullable=False)
    grouping_dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    group_value: Mapped[str] = mapped_column(String(64), nullable=False)
    eligible_prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_tier_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_absolute_count_error: Mapped[Decimal | None] = mapped_column(AMOUNT)
    median_absolute_count_error: Mapped[Decimal | None] = mapped_column(AMOUNT)
    median_bias_count: Mapped[Decimal | None] = mapped_column(AMOUNT)
    mean_absolute_fraction_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    median_absolute_fraction_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    median_bias_fraction: Mapped[Decimal | None] = mapped_column(FRACTION)
    median_absolute_standardized_error: Mapped[Decimal | None] = mapped_column(FRACTION)
    interval_coverage: Mapped[Decimal | None] = mapped_column(FRACTION)
    improvement_vs_no_lag: Mapped[Decimal | None] = mapped_column(FRACTION)

    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id",
            "horizon_days",
            "model_variant",
            "grouping_dimension",
            "group_value",
            name="uq_analytics_backtest_summary_group",
        ),
    )
