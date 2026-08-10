"""Add auditable walk-forward predictions, summaries, and promotion reports."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_backtesting"
down_revision: str | None = "0005_analytics_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    fraction = sa.Numeric(18, 12)
    amount = sa.Numeric(24, 6)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "analytics_backtest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_version_id", sa.BigInteger(), nullable=False),
        sa.Column("cutoff_start_at", sa.DateTime(timezone=True)),
        sa.Column("cutoff_end_at", sa.DateTime(timezone=True)),
        sa.Column("horizons", jsonb, nullable=False),
        sa.Column("parameters", jsonb, nullable=False),
        sa.Column("parameters_sha256", sa.CHAR(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("aggregate_results", jsonb, nullable=False),
        sa.Column("promotion_status", sa.String(16), nullable=False),
        sa.Column("promotion_report", jsonb, nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_analytics_backtest_runs_status",
        ),
        sa.CheckConstraint(
            "promotion_status IN ('pending', 'passed', 'failed')",
            name="ck_analytics_backtest_runs_promotion_status",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_analytics_backtest_runs_finished_after_started",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["analytics_model_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "parameters_sha256",
            name="uq_analytics_backtest_model_parameters",
        ),
    )
    op.create_table(
        "analytics_backtest_predictions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("cutoff_scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("target_scrape_run_id", sa.Integer()),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("cutoff_game_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("target_game_snapshot_id", sa.Integer()),
        sa.Column("prize_amount", amount, nullable=False),
        sa.Column("original_count", sa.BigInteger(), nullable=False),
        sa.Column("cutoff_remaining_count", sa.BigInteger(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("model_variant", sa.String(16), nullable=False),
        sa.Column("process_group", sa.String(16), nullable=False),
        sa.Column("confidence_label", sa.String(16)),
        sa.Column("ticket_price_group", sa.String(32), nullable=False),
        sa.Column("evidence_cohort", sa.String(16), nullable=False),
        sa.Column("cutoff_inputs", jsonb, nullable=False),
        sa.Column("predicted_remaining_count", amount),
        sa.Column("predicted_remaining_fraction", fraction),
        sa.Column("prediction_lower_count", amount),
        sa.Column("prediction_upper_count", amount),
        sa.Column("observed_remaining_count", sa.BigInteger()),
        sa.Column("observed_remaining_fraction", fraction),
        sa.Column("signed_count_error", amount),
        sa.Column("absolute_count_error", amount),
        sa.Column("signed_fraction_error", fraction),
        sa.Column("absolute_fraction_error", fraction),
        sa.Column("standardized_error", fraction),
        sa.Column("interval_contains_observed", sa.Boolean()),
        sa.Column("eligibility_code", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "model_variant IN ('aligned', 'no_lag', 'legacy')",
            name="ck_analytics_backtest_predictions_variant",
        ),
        sa.CheckConstraint(
            "process_group IN ('baseline', 'retail_gap', 'high')",
            name="ck_analytics_backtest_predictions_process_group",
        ),
        sa.CheckConstraint(
            "horizon_days IN (7, 14, 30)",
            name="ck_analytics_backtest_predictions_horizon",
        ),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"], ["analytics_backtest_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["cutoff_scrape_run_id"], ["scrape_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_scrape_run_id"], ["scrape_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["cutoff_game_snapshot_id"], ["game_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_game_snapshot_id"], ["game_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "backtest_run_id",
            "cutoff_scrape_run_id",
            "game_id",
            "prize_amount",
            "horizon_days",
            "model_variant",
            name="uq_analytics_backtest_prediction_identity",
        ),
    )
    op.create_index(
        "ix_analytics_backtest_prediction_summary",
        "analytics_backtest_predictions",
        ["backtest_run_id", "horizon_days", "model_variant"],
    )
    op.create_index(
        "ix_analytics_backtest_prediction_tier",
        "analytics_backtest_predictions",
        ["game_id", "prize_amount", "cutoff_scrape_run_id"],
    )
    op.create_table(
        "analytics_backtest_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("model_variant", sa.String(16), nullable=False),
        sa.Column("grouping_dimension", sa.String(32), nullable=False),
        sa.Column("group_value", sa.String(64), nullable=False),
        sa.Column("eligible_prediction_count", sa.Integer(), nullable=False),
        sa.Column("unique_game_count", sa.Integer(), nullable=False),
        sa.Column("unique_tier_count", sa.Integer(), nullable=False),
        sa.Column("mean_absolute_count_error", amount),
        sa.Column("median_absolute_count_error", amount),
        sa.Column("median_bias_count", amount),
        sa.Column("mean_absolute_fraction_error", fraction),
        sa.Column("median_absolute_fraction_error", fraction),
        sa.Column("median_bias_fraction", fraction),
        sa.Column("median_absolute_standardized_error", fraction),
        sa.Column("interval_coverage", fraction),
        sa.Column("improvement_vs_no_lag", fraction),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"], ["analytics_backtest_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "backtest_run_id",
            "horizon_days",
            "model_variant",
            "grouping_dimension",
            "group_value",
            name="uq_analytics_backtest_summary_group",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_successful_backtest_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'success' THEN
                RAISE EXCEPTION 'successful backtest runs are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER analytics_backtest_runs_immutable
        BEFORE UPDATE OR DELETE ON analytics_backtest_runs
        FOR EACH ROW EXECUTE FUNCTION prevent_successful_backtest_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS analytics_backtest_runs_immutable "
        "ON analytics_backtest_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_successful_backtest_mutation()")
    op.drop_table("analytics_backtest_summaries")
    op.drop_index(
        "ix_analytics_backtest_prediction_tier",
        table_name="analytics_backtest_predictions",
    )
    op.drop_index(
        "ix_analytics_backtest_prediction_summary",
        table_name="analytics_backtest_predictions",
    )
    op.drop_table("analytics_backtest_predictions")
    op.drop_table("analytics_backtest_runs")
