"""Create versioned analytics storage, immutability guards, and current views."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_analytics_core"
down_revision: str | None = "0004_catalog_and_metadata_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_PARAMETERS = {
    "baseline_max_prize": 500,
    "bootstrap_samples": 10000,
    "bootstrap_seed": 20260808,
    "confidence_information_high_boundary": 25,
    "confidence_information_low_boundary": 5,
    "confidence_information_moderate_boundary": 10,
    "confidence_min_tier_n": 20,
    "high_prize_strictly_greater_than": 600,
    "lag_exploratory_original_count": 250,
    "lag_internal_quantiles": 9,
    "lag_max_interpolation_gap_days": 3,
    "lag_min_global_games": 8,
    "lag_min_overlap_fraction": 0.075,
    "lag_min_snapshots": 30,
    "lag_min_span_days": 30,
    "lag_primary_original_count": 500,
    "reference_min_original_count": 10000,
    "source_fresh_hours": 36,
    "source_stale_error_hours": 72,
    "wilson_z": 1.959963984540054,
}


def _canonical_parameters() -> str:
    return json.dumps(MODEL_PARAMETERS, sort_keys=True, separators=(",", ":"))


def upgrade() -> None:
    fraction = sa.Numeric(18, 12)
    amount = sa.Numeric(24, 6)
    odds = sa.Numeric(30, 6)
    op.create_table(
        "analytics_model_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("semantic_version", sa.String(32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_sha256", sa.CHAR(64), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parameters_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_analytics_model_versions_sha256",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_name", "semantic_version", name="uq_analytics_model_name_version"
        ),
    )
    op.create_table(
        "analytics_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_version_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of_scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("as_of_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status", sa.String(16), server_default="running", nullable=False
        ),
        sa.Column("publishable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_analytics_runs_status",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_analytics_runs_finished_after_started",
        ),
        sa.CheckConstraint(
            "NOT publishable OR status = 'success'",
            name="ck_analytics_runs_publishable_success",
        ),
        sa.ForeignKeyConstraint(
            ["as_of_scrape_run_id"], ["scrape_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["analytics_model_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "as_of_scrape_run_id",
            name="uq_analytics_runs_model_cutoff",
        ),
    )
    op.create_index(
        "ix_analytics_runs_cutoff_status",
        "analytics_runs",
        ["as_of_scrape_run_id", "status", "publishable"],
    )
    op.create_table(
        "analytics_lag_calibrations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("primary_original_count", sa.Integer(), nullable=False),
        sa.Column("exploratory_original_count", sa.Integer(), nullable=False),
        sa.Column("minimum_snapshots", sa.Integer(), nullable=False),
        sa.Column("minimum_span_days", sa.Integer(), nullable=False),
        sa.Column("minimum_overlap_fraction", fraction, nullable=False),
        sa.Column("internal_quantile_count", sa.Integer(), nullable=False),
        sa.Column("maximum_interpolation_gap_days", sa.Integer(), nullable=False),
        sa.Column("candidate_game_count", sa.Integer(), nullable=False),
        sa.Column("primary_qualified_game_count", sa.Integer(), nullable=False),
        sa.Column("exploratory_game_count", sa.Integer(), nullable=False),
        sa.Column("positive_game_count", sa.Integer(), nullable=False),
        sa.Column("excluded_game_count", sa.Integer(), nullable=False),
        sa.Column("global_median_lag_days", fraction),
        sa.Column("global_q1_lag_days", fraction),
        sa.Column("global_q3_lag_days", fraction),
        sa.Column("bootstrap_lower_lag_days", fraction),
        sa.Column("bootstrap_upper_lag_days", fraction),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.CheckConstraint(
            "status IN ('available', 'insufficient', 'failed')",
            name="ck_analytics_lag_calibrations_status",
        ),
        sa.CheckConstraint(
            "candidate_game_count >= 0 AND primary_qualified_game_count >= 0 "
            "AND exploratory_game_count >= 0 AND positive_game_count >= 0 "
            "AND excluded_game_count >= 0",
            name="ck_analytics_lag_calibrations_counts",
        ),
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analytics_run_id", name="uq_analytics_lag_calibration_run"
        ),
    )
    op.create_table(
        "analytics_lag_game_estimates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("eligible_primary", sa.Boolean(), nullable=False),
        sa.Column("eligible_exploratory", sa.Boolean(), nullable=False),
        sa.Column("exclusion_code", sa.String(64)),
        sa.Column("top_prize_amount", amount),
        sa.Column("adaptive_high_band_ceiling", amount),
        sa.Column("selected_high_band_original_count", sa.BigInteger()),
        sa.Column("snapshot_count", sa.Integer()),
        sa.Column("history_span_days", fraction),
        sa.Column("common_progress_lower", fraction),
        sa.Column("common_progress_upper", fraction),
        sa.Column("common_progress_width", fraction),
        sa.Column("valid_quantile_count", sa.Integer()),
        sa.Column("median_lag_days", fraction),
        sa.Column("q1_lag_days", fraction),
        sa.Column("q3_lag_days", fraction),
        sa.Column("used_in_global", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_lag_game_run_game"
        ),
    )
    op.create_table(
        "analytics_game_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("structure_fingerprint", sa.CHAR(64)),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_tier_count", sa.Integer()),
        sa.Column("baseline_original_count", sa.BigInteger()),
        sa.Column("baseline_remaining_count", sa.BigInteger()),
        sa.Column("baseline_claimed_count", sa.BigInteger()),
        sa.Column("baseline_remaining_fraction", fraction),
        sa.Column("progress_fraction", fraction),
        sa.Column("estimated_original_tickets", amount),
        sa.Column("estimated_sold_tickets", amount),
        sa.Column("estimated_remaining_tickets", amount),
        sa.Column("published_overall_odds_one_in", odds),
        sa.Column("full_score_count_coverage", fraction),
        sa.Column("full_score_value_coverage", fraction),
        sa.Column("high_score_count_coverage", fraction),
        sa.Column("high_score_value_coverage", fraction),
        sa.Column("prize_source_current", sa.Boolean(), nullable=False),
        sa.Column("catalog_current", sa.Boolean(), nullable=False),
        sa.Column("recommendation_current", sa.Boolean(), nullable=False),
        sa.Column("catalog_observed_at", sa.DateTime(timezone=True)),
        sa.Column("data_status", sa.String(32), nullable=False),
        sa.Column("publishable", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "data_status IN ('complete', 'partial', 'unavailable')",
            name="ck_analytics_game_metrics_data_status",
        ),
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["game_snapshot_id"], ["game_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_game_metrics_run_game"
        ),
    )
    op.create_index(
        "ix_analytics_game_metrics_run_status",
        "analytics_game_metrics",
        ["analytics_run_id", "data_status", "publishable"],
    )
    op.create_table(
        "analytics_tier_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("prize_tier_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("is_top_prize", sa.Boolean(), nullable=False),
        sa.Column("process_group", sa.String(16), nullable=False),
        sa.Column("reference_method", sa.String(32), nullable=False),
        sa.Column("reference_observed_at", sa.DateTime(timezone=True)),
        sa.Column("lag_days_used", fraction),
        sa.Column("lag_includes_scored_game", sa.Boolean()),
        sa.Column("current_baseline_remaining_fraction", fraction),
        sa.Column("reference_remaining_fraction", fraction),
        sa.Column("observed_survival_fraction", fraction),
        sa.Column("expected_reported_remaining", amount),
        sa.Column("availability_index", fraction),
        sa.Column("availability_wilson_lower", fraction),
        sa.Column("availability_wilson_upper", fraction),
        sa.Column("availability_sensitivity_min", fraction),
        sa.Column("availability_sensitivity_max", fraction),
        sa.Column("one_in_sensitivity_min", odds),
        sa.Column("one_in_sensitivity_max", odds),
        sa.Column("lag_sensitivity_direction_changes", sa.Boolean()),
        sa.Column("launch_probability", fraction),
        sa.Column("launch_one_in", odds),
        sa.Column("current_probability", fraction),
        sa.Column("current_one_in", odds),
        sa.Column("equivalent_current_remaining", amount),
        sa.Column("confidence_label", sa.String(16)),
        sa.Column("information_count", amount),
        sa.Column("evidence_classification", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("exclusion_reason", sa.String(64)),
        sa.CheckConstraint(
            "process_group IN ('baseline', 'retail_gap', 'high')",
            name="ck_analytics_tier_metrics_process_group",
        ),
        sa.CheckConstraint(
            "reference_method IN ('leave_one_tier_out', 'current_baseline', "
            "'lagged_baseline', 'unavailable')",
            name="ck_analytics_tier_metrics_reference_method",
        ),
        sa.CheckConstraint(
            "status IN ('available', 'depleted', 'unavailable')",
            name="ck_analytics_tier_metrics_status",
        ),
        sa.CheckConstraint(
            "confidence_label IS NULL OR confidence_label IN "
            "('lumpy', 'low', 'moderate', 'high')",
            name="ck_analytics_tier_metrics_confidence",
        ),
        sa.CheckConstraint(
            "evidence_classification IS NULL OR evidence_classification IN "
            "('favorable', 'unfavorable', 'indeterminate', 'unavailable')",
            name="ck_analytics_tier_metrics_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["game_snapshot_id"], ["game_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["prize_tier_snapshot_id"],
            ["prize_tier_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analytics_run_id",
            "prize_tier_snapshot_id",
            name="uq_analytics_tier_metrics_run_tier",
        ),
    )
    op.create_index(
        "ix_analytics_tier_metrics_run_game",
        "analytics_tier_metrics",
        ["analytics_run_id", "game_id"],
    )
    _create_strategy_metrics(fraction, amount, odds)
    op.create_table(
        "analytics_quality_issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("game_id", sa.Integer()),
        sa.Column("game_snapshot_id", sa.Integer()),
        sa.Column("prize_tier_snapshot_id", sa.Integer()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_analytics_quality_issues_severity",
        ),
        sa.CheckConstraint(
            "entity_type IN ('run', 'game', 'snapshot', 'tier')",
            name="ck_analytics_quality_issues_entity_type",
        ),
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["game_snapshot_id"], ["game_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["prize_tier_snapshot_id"],
            ["prize_tier_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_quality_issues_run_severity_code",
        "analytics_quality_issues",
        ["analytics_run_id", "severity", "code"],
    )
    op.create_index(
        "ix_analytics_quality_issues_game_code",
        "analytics_quality_issues",
        ["game_id", "code"],
    )
    _seed_model_version()
    _create_immutability_triggers()
    _create_current_views()


def _create_strategy_metrics(fraction: sa.Numeric, amount: sa.Numeric, odds: sa.Numeric) -> None:
    probability_columns = [
        "p_any_win",
        "p_break_even_exact",
        "p_break_even_or_better",
        "p_2x_or_better",
        "p_strict_profit",
        "p_strict_profit_ex_top",
        "profit_probability_vs_launch",
        "p_5x_or_better_ex_top",
        "p_10x_or_better_ex_top",
        "p_20x_or_better_ex_top",
        "p_50x_or_better_ex_top",
        "p_100_to_1000_ex_top",
        "p_top_prize_estimated",
        "p_1000_or_better",
        "p_10000_or_better",
        "p_100000_or_better",
        "p_1000000_or_better",
    ]
    one_in_columns = [
        "one_in_any_win",
        "one_in_break_even_exact",
        "one_in_strict_profit_ex_top",
        "one_in_5x_or_better_ex_top",
        "one_in_10x_or_better_ex_top",
        "one_in_top_prize_estimated",
        "one_in_1000_or_better",
        "one_in_10000_or_better",
        "one_in_100000_or_better",
    ]
    value_columns = [
        "ev_5x_or_better_ex_top",
        "ev_10x_or_better_ex_top",
        "estimated_ev_full",
        "estimated_ev_ex_top",
        "launch_ev_full",
        "launch_ev_ex_top",
    ]
    ratio_columns = [
        "estimated_payout_ratio_full",
        "estimated_payout_ratio_ex_top",
        "estimated_house_edge_full",
        "estimated_house_edge_ex_top",
        "ev_full_vs_launch",
        "ev_ex_top_vs_launch",
        "top_availability_index",
        "full_count_coverage",
        "full_value_coverage",
        "ex_top_count_coverage",
        "ex_top_value_coverage",
    ]
    columns: list[sa.Column] = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analytics_run_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("ticket_price", sa.Numeric(10, 2), nullable=False),
        *[sa.Column(name, fraction) for name in probability_columns],
        *[sa.Column(name, odds) for name in one_in_columns],
        *[sa.Column(name, amount) for name in value_columns],
        *[sa.Column(name, fraction) for name in ratio_columns],
        sa.Column("top_prize_amount", amount),
        sa.Column("top_prizes_original_reported", sa.BigInteger()),
        sa.Column("top_prizes_remaining_reported", sa.BigInteger()),
        sa.Column("top_confidence", sa.String(16)),
        sa.Column("metric_statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lowest_confidence", sa.String(16)),
        sa.Column("contains_lumpy_tier", sa.Boolean(), nullable=False),
    ]
    op.create_table(
        "analytics_strategy_metrics",
        *columns,
        sa.ForeignKeyConstraint(
            ["analytics_run_id"], ["analytics_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analytics_run_id", "game_id", name="uq_analytics_strategy_run_game"
        ),
    )


def _seed_model_version() -> None:
    canonical = _canonical_parameters()
    table = sa.table(
        "analytics_model_versions",
        sa.column("model_name", sa.String),
        sa.column("semantic_version", sa.String),
        sa.column("parameters", postgresql.JSONB),
        sa.column("parameters_sha256", sa.String),
        sa.column("code_version", sa.String),
    )
    op.bulk_insert(
        table,
        [
            {
                "model_name": "core_ticket_model",
                "semantic_version": "1.0.0",
                "parameters": MODEL_PARAMETERS,
                "parameters_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                "code_version": "database-blueprint-1.0",
            }
        ],
    )


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_analytics_model_version_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'analytics model versions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER analytics_model_versions_immutable
        BEFORE UPDATE OR DELETE ON analytics_model_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_analytics_model_version_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_successful_analytics_run_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'success' AND OLD.publishable THEN
            RAISE EXCEPTION 'published successful analytics runs are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER successful_analytics_runs_immutable
        BEFORE UPDATE OR DELETE ON analytics_runs
        FOR EACH ROW EXECUTE FUNCTION prevent_successful_analytics_run_mutation()
        """
    )


def _create_current_views() -> None:
    op.execute(
        """
        CREATE VIEW current_analytics_run_v AS
        SELECT ar.*
        FROM analytics_runs ar
        JOIN analytics_model_versions mv ON mv.id = ar.model_version_id
        JOIN current_complete_scrape_run_v source ON source.id = ar.as_of_scrape_run_id
        WHERE ar.status = 'success'
          AND ar.publishable
          AND mv.model_name = 'core_ticket_model'
          AND mv.id = (
            SELECT max(latest.id) FROM analytics_model_versions latest
            WHERE latest.model_name = 'core_ticket_model'
          )
        """
    )
    op.execute(
        """
        CREATE VIEW current_game_metrics_v AS
        SELECT metrics.* FROM analytics_game_metrics metrics
        JOIN current_analytics_run_v current_run
          ON current_run.id = metrics.analytics_run_id
        """
    )
    op.execute(
        """
        CREATE VIEW current_tier_metrics_v AS
        SELECT metrics.* FROM analytics_tier_metrics metrics
        JOIN current_analytics_run_v current_run
          ON current_run.id = metrics.analytics_run_id
        """
    )
    op.execute(
        """
        CREATE VIEW current_strategy_metrics_v AS
        SELECT metrics.* FROM analytics_strategy_metrics metrics
        JOIN current_analytics_run_v current_run
          ON current_run.id = metrics.analytics_run_id
        """
    )
    op.execute(
        """
        CREATE VIEW current_strategy_rankings_v AS
        WITH expanded AS (
          SELECT
            metrics.analytics_run_id,
            metrics.game_id,
            games.game_number,
            metrics.ticket_price,
            strategy.strategy_key,
            strategy.metric_value,
            metrics.metric_statuses ->> strategy.strategy_key AS metric_status,
            metrics.lowest_confidence,
            strategy.coverage
          FROM current_strategy_metrics_v metrics
          JOIN games ON games.id = metrics.game_id
          JOIN recommendation_current_games_v recommended
            ON recommended.id = metrics.game_id
          CROSS JOIN LATERAL (VALUES
            ('money_back_exact', metrics.p_break_even_exact,
             metrics.full_count_coverage),
            ('profit_ex_top', metrics.p_strict_profit_ex_top,
             metrics.ex_top_count_coverage),
            ('value_full', metrics.estimated_payout_ratio_full,
             metrics.full_value_coverage),
            ('value_ex_top', metrics.estimated_payout_ratio_ex_top,
             metrics.ex_top_value_coverage),
            ('moderate_5x', metrics.p_5x_or_better_ex_top,
             metrics.ex_top_count_coverage),
            ('moderate_10x', metrics.p_10x_or_better_ex_top,
             metrics.ex_top_count_coverage),
            ('jackpot_top_odds', metrics.p_top_prize_estimated,
             metrics.full_count_coverage),
            ('large_1000', metrics.p_1000_or_better,
             metrics.full_count_coverage),
            ('large_100000', metrics.p_100000_or_better,
             metrics.full_count_coverage)
          ) AS strategy(strategy_key, metric_value, coverage)
        ), eligible AS (
          SELECT * FROM expanded
          WHERE metric_status = 'complete' AND metric_value IS NOT NULL
        )
        SELECT
          eligible.*,
          dense_rank() OVER (
            PARTITION BY strategy_key ORDER BY metric_value DESC
          ) AS rank_overall,
          dense_rank() OVER (
            PARTITION BY strategy_key, ticket_price ORDER BY metric_value DESC
          ) AS rank_within_ticket_price
        FROM eligible
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW current_strategy_rankings_v")
    op.execute("DROP VIEW current_strategy_metrics_v")
    op.execute("DROP VIEW current_tier_metrics_v")
    op.execute("DROP VIEW current_game_metrics_v")
    op.execute("DROP VIEW current_analytics_run_v")
    op.execute("DROP TRIGGER successful_analytics_runs_immutable ON analytics_runs")
    op.execute("DROP FUNCTION prevent_successful_analytics_run_mutation")
    op.execute("DROP TRIGGER analytics_model_versions_immutable ON analytics_model_versions")
    op.execute("DROP FUNCTION prevent_analytics_model_version_mutation")
    op.drop_index(
        "ix_analytics_quality_issues_game_code", table_name="analytics_quality_issues"
    )
    op.drop_index(
        "ix_analytics_quality_issues_run_severity_code",
        table_name="analytics_quality_issues",
    )
    op.drop_table("analytics_quality_issues")
    op.drop_table("analytics_strategy_metrics")
    op.drop_index(
        "ix_analytics_tier_metrics_run_game", table_name="analytics_tier_metrics"
    )
    op.drop_table("analytics_tier_metrics")
    op.drop_index(
        "ix_analytics_game_metrics_run_status", table_name="analytics_game_metrics"
    )
    op.drop_table("analytics_game_metrics")
    op.drop_table("analytics_lag_game_estimates")
    op.drop_table("analytics_lag_calibrations")
    op.drop_index("ix_analytics_runs_cutoff_status", table_name="analytics_runs")
    op.drop_table("analytics_runs")
    op.drop_table("analytics_model_versions")
