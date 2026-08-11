"""Replace adaptive lag/backtesting with the fixed 24-day high-prize adjustment."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_simplified_high_prize_adjustment"
down_revision: str | None = "0009_authentication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_PARAMETERS = {
    "baseline_max_prize": 600,
    "confidence_information_high_boundary": 25,
    "confidence_information_low_boundary": 5,
    "confidence_information_moderate_boundary": 10,
    "confidence_min_tier_n": 20,
    "high_prize_minimum_original_count": 300,
    "high_prize_strictly_greater_than": 600,
    "mail_claim_reporting_lag_days": 24,
    "reference_min_original_count": 10000,
    "source_fresh_hours": 36,
    "source_stale_error_hours": 72,
    "wilson_z": 1.959963984540054,
}
MODEL_PARAMETERS_SHA256 = (
    "cae3a524b601ac0191c988bb672c375c4af0fe488f64fb60f9f67773f5fd46ca"
)


def upgrade() -> None:
    _drop_views()
    op.execute(
        "DROP TRIGGER IF EXISTS analytics_model_versions_immutable "
        "ON analytics_model_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_analytics_model_version_mutation()")
    op.execute("DROP TRIGGER IF EXISTS successful_analytics_runs_immutable ON analytics_runs")
    op.execute("DROP FUNCTION IF EXISTS prevent_successful_analytics_run_mutation()")

    op.drop_index(
        "uq_analytics_model_versions_one_approved",
        table_name="analytics_model_versions",
    )
    op.drop_constraint(
        "ck_analytics_model_versions_approved_evidence",
        "analytics_model_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_analytics_model_versions_approval_status",
        "analytics_model_versions",
        type_="check",
    )
    op.drop_constraint(
        "fk_analytics_model_versions_approval_backtest",
        "analytics_model_versions",
        type_="foreignkey",
    )
    op.drop_table("analytics_backtest_summaries")
    op.drop_table("analytics_backtest_predictions")
    op.drop_table("analytics_backtest_runs")

    # All analytics rows are derived and are recomputed under model 2.0.0.
    op.execute("DELETE FROM analytics_runs")
    op.execute("DELETE FROM analytics_model_versions")
    op.drop_table("analytics_lag_game_estimates")
    op.drop_table("analytics_lag_calibrations")

    op.drop_column("analytics_model_versions", "approval_reason")
    op.drop_column("analytics_model_versions", "approval_decided_at")
    op.drop_column("analytics_model_versions", "approval_backtest_run_id")
    op.drop_column("analytics_model_versions", "approval_status")

    op.drop_index("ix_analytics_runs_cutoff_status", table_name="analytics_runs")
    op.drop_constraint(
        "ck_analytics_runs_publishable_success", "analytics_runs", type_="check"
    )
    op.drop_column("analytics_runs", "publishable")
    op.create_index(
        "ix_analytics_runs_cutoff_status",
        "analytics_runs",
        ["as_of_scrape_run_id", "status"],
    )

    op.drop_index(
        "ix_analytics_game_metrics_run_status", table_name="analytics_game_metrics"
    )
    op.drop_column("analytics_game_metrics", "publishable")
    op.create_index(
        "ix_analytics_game_metrics_run_status",
        "analytics_game_metrics",
        ["analytics_run_id", "data_status"],
    )

    op.drop_constraint(
        "ck_analytics_tier_metrics_process_group",
        "analytics_tier_metrics",
        type_="check",
    )
    op.drop_constraint(
        "ck_analytics_tier_metrics_reference_method",
        "analytics_tier_metrics",
        type_="check",
    )
    for column in (
        "lag_includes_scored_game",
        "expected_reported_remaining",
        "availability_sensitivity_min",
        "availability_sensitivity_max",
        "one_in_sensitivity_min",
        "one_in_sensitivity_max",
        "lag_sensitivity_direction_changes",
        "equivalent_current_remaining",
    ):
        op.drop_column("analytics_tier_metrics", column)
    op.alter_column(
        "analytics_tier_metrics",
        "lag_days_used",
        existing_type=sa.Numeric(18, 12),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    amount = sa.Numeric(24, 6)
    op.add_column(
        "analytics_tier_metrics",
        sa.Column("adjustment_eligible", sa.Boolean(), nullable=False),
    )
    op.add_column(
        "analytics_tier_metrics",
        sa.Column("adjustment_status", sa.String(32), nullable=False),
    )
    op.add_column(
        "analytics_tier_metrics",
        sa.Column("reported_remaining_count", sa.BigInteger(), nullable=False),
    )
    op.add_column(
        "analytics_tier_metrics",
        sa.Column("estimated_pending_count", amount, nullable=False),
    )
    op.add_column(
        "analytics_tier_metrics",
        sa.Column("adjusted_remaining_count", amount, nullable=False),
    )
    op.create_check_constraint(
        "ck_analytics_tier_metrics_process_group",
        "analytics_tier_metrics",
        "process_group IN ('baseline', 'high')",
    )
    op.create_check_constraint(
        "ck_analytics_tier_metrics_reference_method",
        "analytics_tier_metrics",
        "reference_method IN ('leave_one_tier_out', 'current_baseline', 'unavailable')",
    )
    op.create_check_constraint(
        "ck_analytics_tier_metrics_adjustment_status",
        "analytics_tier_metrics",
        "adjustment_status IN ('applied', 'reported_only', 'reference_unavailable')",
    )
    op.create_check_constraint(
        "ck_analytics_tier_metrics_adjustment_counts",
        "analytics_tier_metrics",
        "reported_remaining_count >= 0 AND estimated_pending_count >= 0 "
        "AND adjusted_remaining_count >= 0",
    )

    model_table = sa.table(
        "analytics_model_versions",
        sa.column("model_name", sa.String),
        sa.column("semantic_version", sa.String),
        sa.column("parameters", postgresql.JSONB),
        sa.column("parameters_sha256", sa.String),
        sa.column("code_version", sa.String),
    )
    op.bulk_insert(
        model_table,
        [
            {
                "model_name": "core_ticket_model",
                "semantic_version": "2.0.0",
                "parameters": MODEL_PARAMETERS,
                "parameters_sha256": MODEL_PARAMETERS_SHA256,
                "code_version": "fixed-high-prize-adjustment-2.0",
            }
        ],
    )
    _create_immutability_triggers()
    _create_views()


def _drop_views() -> None:
    op.execute("DROP VIEW IF EXISTS games_to_review_carefully_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_rankings_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_ranking_status_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_tier_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_game_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_analytics_run_v")


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
          IF OLD.status = 'success' THEN
            RAISE EXCEPTION 'successful analytics runs are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
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


def _create_views() -> None:
    op.execute(
        """
        CREATE VIEW current_analytics_run_v AS
        SELECT analytics.*
        FROM analytics_runs analytics
        JOIN analytics_model_versions model ON model.id = analytics.model_version_id
        JOIN current_complete_scrape_run_v source
          ON source.id = analytics.as_of_scrape_run_id
        WHERE analytics.status = 'success'
          AND model.model_name = 'core_ticket_model'
          AND model.semantic_version = '2.0.0'
        """
    )
    for name, table in (
        ("current_game_metrics_v", "analytics_game_metrics"),
        ("current_tier_metrics_v", "analytics_tier_metrics"),
        ("current_strategy_metrics_v", "analytics_strategy_metrics"),
    ):
        op.execute(
            f"CREATE VIEW {name} AS SELECT metrics.* FROM {table} metrics "
            "JOIN current_analytics_run_v current_run "
            "ON current_run.id = metrics.analytics_run_id"
        )
    op.execute(
        """
        CREATE VIEW current_strategy_ranking_status_v AS
        WITH model AS (
          SELECT * FROM analytics_model_versions
          WHERE model_name = 'core_ticket_model' AND semantic_version = '2.0.0'
        ), source AS (
          SELECT * FROM current_complete_scrape_run_v
        ), catalog AS (
          SELECT * FROM current_complete_catalog_run_v
        ), analytics AS (
          SELECT * FROM current_analytics_run_v
        ), state AS (
          SELECT source.id AS source_run_id,
            source.source_observed_at, catalog.id AS catalog_run_id,
            catalog.source_observed_at AS catalog_observed_at,
            model.id AS model_version_id, model.semantic_version,
            analytics.id AS analytics_run_id,
            COALESCE((model.parameters ->> 'source_stale_error_hours')::integer, 72)
              AS stale_error_hours
          FROM (SELECT 1) anchor
          LEFT JOIN source ON true LEFT JOIN catalog ON true
          LEFT JOIN model ON true LEFT JOIN analytics ON true
        )
        SELECT state.*,
          CASE WHEN model_version_id IS NULL OR source_run_id IS NULL
            OR catalog_run_id IS NULL OR analytics_run_id IS NULL THEN false
            WHEN source_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN false
            WHEN catalog_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN false ELSE true END AS available,
          CASE WHEN model_version_id IS NULL THEN 'ANALYTICS_MODEL_UNAVAILABLE'
            WHEN source_run_id IS NULL THEN 'SOURCE_UNAVAILABLE'
            WHEN catalog_run_id IS NULL THEN 'CATALOG_UNAVAILABLE'
            WHEN source_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN 'SOURCE_STALE'
            WHEN catalog_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN 'CATALOG_STALE'
            WHEN analytics_run_id IS NULL THEN 'ANALYTICS_UNAVAILABLE'
            ELSE 'AVAILABLE' END AS reason_code
        FROM state
        """
    )
    op.execute(
        """
        CREATE VIEW current_strategy_rankings_v AS
        WITH expanded AS (
          SELECT metrics.analytics_run_id, metrics.game_id, games.game_number,
            metrics.ticket_price, strategy.strategy_key, strategy.metric_value,
            strategy.one_in_value,
            (metrics.metric_details -> strategy.strategy_key ->> 'launch_metric_value')::numeric
              AS launch_metric_value,
            (metrics.metric_details -> strategy.strategy_key ->> 'target_tier_count')::integer
              AS target_tier_count,
            COALESCE(
              (metrics.metric_details -> strategy.strategy_key ->> 'count_coverage')::numeric,
              strategy.fallback_count_coverage) AS target_count_coverage,
            COALESCE(
              (metrics.metric_details -> strategy.strategy_key ->> 'value_coverage')::numeric,
              strategy.fallback_value_coverage) AS target_value_coverage,
            metrics.metric_statuses ->> strategy.strategy_key AS metric_status,
            COALESCE(metrics.metric_details -> strategy.strategy_key ->> 'lowest_confidence',
              metrics.lowest_confidence) AS lowest_confidence,
            COALESCE((metrics.metric_details -> strategy.strategy_key
              ->> 'contains_lumpy_tier')::boolean,
              metrics.contains_lumpy_tier) AS contains_lumpy_tier,
            current_run.as_of_observed_at AS source_observed_at,
            catalog.source_observed_at AS catalog_observed_at,
            model.semantic_version AS model_version,
            model.created_at AS model_created_at
          FROM current_strategy_metrics_v metrics
          JOIN current_analytics_run_v current_run
            ON current_run.id = metrics.analytics_run_id
          JOIN analytics_model_versions model ON model.id = current_run.model_version_id
          JOIN games ON games.id = metrics.game_id
          JOIN recommendation_current_games_v recommended ON recommended.id = metrics.game_id
          JOIN current_strategy_ranking_status_v ranking_status ON ranking_status.available
          JOIN current_complete_catalog_run_v catalog ON true
          CROSS JOIN LATERAL (VALUES
            ('money_back_exact', metrics.p_break_even_exact,
             metrics.one_in_break_even_exact, metrics.full_count_coverage,
             metrics.full_value_coverage),
            ('profit_ex_top', metrics.p_strict_profit_ex_top,
             metrics.one_in_strict_profit_ex_top, metrics.ex_top_count_coverage,
             metrics.ex_top_value_coverage),
            ('value_full', metrics.estimated_payout_ratio_full,
             NULL::numeric, metrics.full_count_coverage, metrics.full_value_coverage),
            ('value_ex_top', metrics.estimated_payout_ratio_ex_top,
             NULL::numeric, metrics.ex_top_count_coverage, metrics.ex_top_value_coverage),
            ('moderate_5x', metrics.p_5x_or_better_ex_top,
             metrics.one_in_5x_or_better_ex_top, metrics.ex_top_count_coverage,
             metrics.ex_top_value_coverage),
            ('moderate_10x', metrics.p_10x_or_better_ex_top,
             metrics.one_in_10x_or_better_ex_top, metrics.ex_top_count_coverage,
             metrics.ex_top_value_coverage),
            ('jackpot_top_odds', metrics.p_top_prize_estimated,
             metrics.one_in_top_prize_estimated, metrics.full_count_coverage,
             metrics.full_value_coverage),
            ('large_1000', metrics.p_1000_or_better,
             metrics.one_in_1000_or_better, metrics.full_count_coverage,
             metrics.full_value_coverage),
            ('large_100000', metrics.p_100000_or_better,
             metrics.one_in_100000_or_better, metrics.full_count_coverage,
             metrics.full_value_coverage)
          ) AS strategy(strategy_key, metric_value, one_in_value,
            fallback_count_coverage, fallback_value_coverage)
        ), eligible AS (
          SELECT expanded.*,
            CASE WHEN launch_metric_value IS NOT NULL AND launch_metric_value <> 0
              THEN metric_value / launch_metric_value END AS relative_to_launch,
            target_count_coverage AS coverage, true AS eligible_all_confidence,
            COALESCE(lowest_confidence IN ('moderate', 'high'), false)
              AS eligible_moderate_or_high
          FROM expanded WHERE metric_status = 'complete' AND metric_value IS NOT NULL
        )
        SELECT eligible.*,
          dense_rank() OVER (PARTITION BY strategy_key ORDER BY metric_value DESC)
            AS rank_overall,
          dense_rank() OVER (
            PARTITION BY strategy_key, ticket_price ORDER BY metric_value DESC)
            AS rank_within_ticket_price
        FROM eligible
        """
    )
    op.execute(
        """
        CREATE VIEW games_to_review_carefully_v AS
        SELECT reconciliation.game_id, reconciliation.game_number,
          NOT reconciliation.prize_source_current AS absent_from_current_source,
          ranking_status.reason_code IN ('SOURCE_STALE', 'SOURCE_UNAVAILABLE')
            AS source_stale,
          games.overall_odds_one_in IS NULL AS missing_overall_odds,
          COALESCE(strategy.top_prizes_remaining_reported = 0, false)
            AS no_top_prizes_remaining,
          EXISTS (SELECT 1 FROM current_tier_metrics_v tier
            WHERE tier.game_id = reconciliation.game_id
              AND tier.adjustment_status = 'reference_unavailable')
            AS high_prize_adjustment_reference_unavailable,
          COALESCE(strategy.metric_statuses ->> 'value_full' <> 'complete', true)
            OR COALESCE(strategy.metric_statuses ->> 'value_ex_top' <> 'complete', true)
            AS full_or_ex_top_metric_partial,
          COALESCE(strategy.contains_lumpy_tier, false)
            AS contains_lumpy_tier,
          current_run.as_of_scrape_run_id IS DISTINCT FROM source.id
            AS analytics_source_cutoff_mismatch
        FROM current_game_source_reconciliation_v reconciliation
        JOIN games ON games.id = reconciliation.game_id
        LEFT JOIN current_strategy_metrics_v strategy
          ON strategy.game_id = reconciliation.game_id
        LEFT JOIN current_analytics_run_v current_run ON true
        LEFT JOIN current_complete_scrape_run_v source ON true
        JOIN current_strategy_ranking_status_v ranking_status ON true
        WHERE reconciliation.prize_source_current OR reconciliation.catalog_current
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0010 intentionally removes derived adaptive-lag/backtest data and is not reversible"
    )
