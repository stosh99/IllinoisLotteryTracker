"""Fail-closed model publication, ranking freshness, and audit detail surfaces."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_review_remediations"
down_revision: str | None = "0007_legacy_metric_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_model_versions",
        sa.Column(
            "approval_status",
            sa.String(16),
            nullable=False,
            server_default="experimental",
        ),
    )
    op.add_column(
        "analytics_model_versions",
        sa.Column("approval_backtest_run_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "analytics_model_versions",
        sa.Column("approval_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analytics_model_versions",
        sa.Column("approval_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_analytics_model_versions_approval_backtest",
        "analytics_model_versions",
        "analytics_backtest_runs",
        ["approval_backtest_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_analytics_model_versions_approval_status",
        "analytics_model_versions",
        "approval_status IN ('experimental', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_analytics_model_versions_approved_evidence",
        "analytics_model_versions",
        "approval_status <> 'approved' OR "
        "(approval_backtest_run_id IS NOT NULL AND approval_decided_at IS NOT NULL "
        "AND approval_reason IS NOT NULL)",
    )
    op.create_index(
        "uq_analytics_model_versions_one_approved",
        "analytics_model_versions",
        ["model_name"],
        unique=True,
        postgresql_where=sa.text("approval_status = 'approved'"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_analytics_model_version_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'analytics model versions are immutable';
          END IF;
          IF ROW(
            NEW.model_name, NEW.semantic_version, NEW.parameters,
            NEW.parameters_sha256, NEW.code_version, NEW.created_at
          ) IS DISTINCT FROM ROW(
            OLD.model_name, OLD.semantic_version, OLD.parameters,
            OLD.parameters_sha256, OLD.code_version, OLD.created_at
          ) THEN
            RAISE EXCEPTION 'analytics model identity and parameters are immutable';
          END IF;
          IF NEW.approval_status IS DISTINCT FROM OLD.approval_status
             AND (NEW.approval_decided_at IS NULL
                  OR NULLIF(btrim(NEW.approval_reason), '') IS NULL) THEN
            RAISE EXCEPTION 'model approval decisions require a timestamp and reason';
          END IF;
          IF NEW.approval_status = 'approved' AND NOT EXISTS (
            SELECT 1
            FROM analytics_backtest_runs backtest
            WHERE backtest.id = NEW.approval_backtest_run_id
              AND backtest.model_version_id = NEW.id
              AND backtest.status = 'success'
              AND backtest.promotion_status = 'passed'
          ) THEN
            RAISE EXCEPTION 'model approval requires a successful passed promotion backtest';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        WITH latest_failed AS (
          SELECT DISTINCT ON (backtest.model_version_id)
            backtest.model_version_id, backtest.id
          FROM analytics_backtest_runs backtest
          WHERE backtest.status = 'success'
            AND backtest.promotion_status = 'failed'
          ORDER BY backtest.model_version_id,
                   backtest.finished_at DESC NULLS LAST,
                   backtest.id DESC
        )
        UPDATE analytics_model_versions model
        SET approval_status = 'rejected',
            approval_backtest_run_id = failed.id,
            approval_decided_at = now(),
            approval_reason = 'Existing promotion backtest failed; publication disabled.'
        FROM latest_failed failed
        WHERE failed.model_version_id = model.id
        """
    )

    op.add_column(
        "analytics_strategy_metrics",
        sa.Column(
            "metric_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "catalog_quality_issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("catalog_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_game_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_catalog_quality_issues_severity",
        ),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_snapshot_id"], ["game_catalog_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_game_id"], ["games.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_quality_issues_run_code",
        "catalog_quality_issues",
        ["scrape_run_id", "code"],
    )

    _drop_analytics_views()
    _create_analytics_views()


def _drop_analytics_views() -> None:
    op.execute("DROP VIEW IF EXISTS games_to_review_carefully_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_rankings_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_ranking_status_v")
    op.execute("DROP VIEW IF EXISTS current_strategy_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_tier_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_game_metrics_v")
    op.execute("DROP VIEW IF EXISTS current_analytics_run_v")


def _create_analytics_views() -> None:
    op.execute(
        """
        CREATE VIEW current_analytics_run_v AS
        SELECT analytics.*
        FROM analytics_runs analytics
        JOIN analytics_model_versions model ON model.id = analytics.model_version_id
        JOIN current_complete_scrape_run_v source
          ON source.id = analytics.as_of_scrape_run_id
        WHERE analytics.status = 'success'
          AND analytics.publishable
          AND model.model_name = 'core_ticket_model'
          AND model.approval_status = 'approved'
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
        CREATE VIEW current_strategy_ranking_status_v AS
        WITH approved_model AS (
          SELECT * FROM analytics_model_versions
          WHERE model_name = 'core_ticket_model' AND approval_status = 'approved'
        ), source AS (
          SELECT * FROM current_complete_scrape_run_v
        ), catalog AS (
          SELECT * FROM current_complete_catalog_run_v
        ), analytics AS (
          SELECT * FROM current_analytics_run_v
        ), state AS (
          SELECT
            source.id AS source_run_id,
            source.source_observed_at AS source_observed_at,
            catalog.id AS catalog_run_id,
            catalog.source_observed_at AS catalog_observed_at,
            approved_model.id AS model_version_id,
            approved_model.semantic_version,
            analytics.id AS analytics_run_id,
            COALESCE(
              (approved_model.parameters ->> 'source_stale_error_hours')::integer,
              72
            ) AS stale_error_hours
          FROM (SELECT 1) anchor
          LEFT JOIN source ON true
          LEFT JOIN catalog ON true
          LEFT JOIN approved_model ON true
          LEFT JOIN analytics ON true
        )
        SELECT state.*,
          CASE
            WHEN model_version_id IS NULL THEN false
            WHEN source_run_id IS NULL THEN false
            WHEN catalog_run_id IS NULL THEN false
            WHEN source_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN false
            WHEN catalog_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN false
            WHEN analytics_run_id IS NULL THEN false
            ELSE true
          END AS available,
          CASE
            WHEN model_version_id IS NULL THEN 'MODEL_NOT_APPROVED'
            WHEN source_run_id IS NULL THEN 'SOURCE_UNAVAILABLE'
            WHEN catalog_run_id IS NULL THEN 'CATALOG_UNAVAILABLE'
            WHEN source_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN 'SOURCE_STALE'
            WHEN catalog_observed_at < now() - make_interval(hours => stale_error_hours)
              THEN 'CATALOG_STALE'
            WHEN analytics_run_id IS NULL THEN 'ANALYTICS_NOT_PUBLISHABLE'
            ELSE 'AVAILABLE'
          END AS reason_code
        FROM state
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
            strategy.one_in_value,
            (metrics.metric_details -> strategy.strategy_key ->> 'launch_metric_value')::numeric
              AS launch_metric_value,
            (metrics.metric_details -> strategy.strategy_key ->> 'target_tier_count')::integer
              AS target_tier_count,
            COALESCE(
              (metrics.metric_details -> strategy.strategy_key ->> 'count_coverage')::numeric,
              strategy.fallback_count_coverage
            ) AS target_count_coverage,
            COALESCE(
              (metrics.metric_details -> strategy.strategy_key ->> 'value_coverage')::numeric,
              strategy.fallback_value_coverage
            ) AS target_value_coverage,
            metrics.metric_statuses ->> strategy.strategy_key AS metric_status,
            COALESCE(
              metrics.metric_details -> strategy.strategy_key ->> 'lowest_confidence',
              metrics.lowest_confidence
            ) AS lowest_confidence,
            COALESCE(
              (metrics.metric_details -> strategy.strategy_key ->> 'contains_lumpy_tier')::boolean,
              metrics.contains_lumpy_tier
            ) AS contains_lumpy_tier,
            current_run.as_of_observed_at AS source_observed_at,
            catalog.source_observed_at AS catalog_observed_at,
            model.semantic_version AS model_version,
            model.created_at AS model_created_at
          FROM current_strategy_metrics_v metrics
          JOIN current_analytics_run_v current_run
            ON current_run.id = metrics.analytics_run_id
          JOIN analytics_model_versions model ON model.id = current_run.model_version_id
          JOIN games ON games.id = metrics.game_id
          JOIN recommendation_current_games_v recommended
            ON recommended.id = metrics.game_id
          JOIN current_strategy_ranking_status_v ranking_status
            ON ranking_status.available
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
          ) AS strategy(
            strategy_key, metric_value, one_in_value,
            fallback_count_coverage, fallback_value_coverage
          )
        ), eligible AS (
          SELECT expanded.*,
            CASE
              WHEN launch_metric_value IS NOT NULL AND launch_metric_value <> 0
                THEN metric_value / launch_metric_value
            END AS relative_to_launch,
            target_count_coverage AS coverage,
            true AS eligible_all_confidence,
            COALESCE(lowest_confidence IN ('moderate', 'high'), false)
              AS eligible_moderate_or_high
          FROM expanded
          WHERE metric_status = 'complete' AND metric_value IS NOT NULL
        )
        SELECT eligible.*,
          dense_rank() OVER (
            PARTITION BY strategy_key ORDER BY metric_value DESC
          ) AS rank_overall,
          dense_rank() OVER (
            PARTITION BY strategy_key, ticket_price ORDER BY metric_value DESC
          ) AS rank_within_ticket_price
        FROM eligible
        """
    )
    op.execute(
        """
        CREATE VIEW games_to_review_carefully_v AS
        SELECT
          reconciliation.game_id,
          reconciliation.game_number,
          NOT reconciliation.prize_source_current AS absent_from_current_source,
          ranking_status.reason_code IN ('SOURCE_STALE', 'SOURCE_UNAVAILABLE') AS source_stale,
          games.overall_odds_one_in IS NULL AS missing_overall_odds,
          COALESCE(strategy.top_prizes_remaining_reported = 0, false)
            AS no_top_prizes_remaining,
          EXISTS (
            SELECT 1 FROM analytics_quality_issues issue
            JOIN current_analytics_run_v issue_run
              ON issue_run.id = issue.analytics_run_id
            WHERE issue.game_id = reconciliation.game_id
              AND issue.code IN ('STRUCTURE_CHANGED', 'PROGRESS_REVERSAL')
          ) AS structure_change_or_count_reversal,
          COALESCE(calibration.status <> 'available', true)
            OR EXISTS (
              SELECT 1 FROM current_tier_metrics_v tier
              WHERE tier.game_id = reconciliation.game_id
                AND tier.process_group = 'high'
                AND (tier.status = 'unavailable'
                     OR tier.lag_sensitivity_direction_changes)
            ) AS lag_unavailable_or_sensitive,
          COALESCE(strategy.metric_statuses ->> 'value_full' <> 'complete', true)
            OR COALESCE(strategy.metric_statuses ->> 'value_ex_top' <> 'complete', true)
            AS full_or_ex_top_metric_partial,
          CASE
            WHEN (model.parameters ->> 'weak_payout_ratio_vs_launch_threshold') IS NULL
              THEN NULL
            ELSE strategy.ev_full_vs_launch <
              (model.parameters ->> 'weak_payout_ratio_vs_launch_threshold')::numeric
          END AS weak_adjusted_payout_ratio,
          COALESCE(strategy.contains_lumpy_tier, false)
            AS high_prize_value_dominated_by_lumpy_tiers,
          current_run.as_of_scrape_run_id IS DISTINCT FROM source.id
            AS analytics_source_cutoff_mismatch
        FROM current_game_source_reconciliation_v reconciliation
        JOIN games ON games.id = reconciliation.game_id
        LEFT JOIN current_strategy_metrics_v strategy
          ON strategy.game_id = reconciliation.game_id
        LEFT JOIN current_analytics_run_v current_run ON true
        LEFT JOIN current_complete_scrape_run_v source ON true
        LEFT JOIN analytics_model_versions model
          ON model.id = current_run.model_version_id
        LEFT JOIN analytics_lag_calibrations calibration
          ON calibration.analytics_run_id = current_run.id
        JOIN current_strategy_ranking_status_v ranking_status ON true
        WHERE reconciliation.prize_source_current OR reconciliation.catalog_current
        """
    )


def downgrade() -> None:
    _drop_analytics_views()
    _create_legacy_analytics_views()

    op.drop_index(
        "ix_catalog_quality_issues_run_code", table_name="catalog_quality_issues"
    )
    op.drop_table("catalog_quality_issues")
    op.drop_column("analytics_strategy_metrics", "metric_details")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_analytics_model_version_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'analytics model versions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
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
    op.drop_column("analytics_model_versions", "approval_reason")
    op.drop_column("analytics_model_versions", "approval_decided_at")
    op.drop_column("analytics_model_versions", "approval_backtest_run_id")
    op.drop_column("analytics_model_versions", "approval_status")


def _create_legacy_analytics_views() -> None:
    op.execute(
        """
        CREATE VIEW current_analytics_run_v AS
        SELECT ar.* FROM analytics_runs ar
        JOIN analytics_model_versions mv ON mv.id = ar.model_version_id
        JOIN current_complete_scrape_run_v source ON source.id = ar.as_of_scrape_run_id
        WHERE ar.status = 'success' AND ar.publishable
          AND mv.model_name = 'core_ticket_model'
          AND mv.id = (
            SELECT max(latest.id) FROM analytics_model_versions latest
            WHERE latest.model_name = 'core_ticket_model'
          )
        """
    )
    op.execute(
        "CREATE VIEW current_game_metrics_v AS SELECT metrics.* "
        "FROM analytics_game_metrics metrics JOIN current_analytics_run_v current_run "
        "ON current_run.id = metrics.analytics_run_id"
    )
    op.execute(
        "CREATE VIEW current_tier_metrics_v AS SELECT metrics.* "
        "FROM analytics_tier_metrics metrics JOIN current_analytics_run_v current_run "
        "ON current_run.id = metrics.analytics_run_id"
    )
    op.execute(
        "CREATE VIEW current_strategy_metrics_v AS SELECT metrics.* "
        "FROM analytics_strategy_metrics metrics JOIN current_analytics_run_v current_run "
        "ON current_run.id = metrics.analytics_run_id"
    )
    op.execute(
        """
        CREATE VIEW current_strategy_rankings_v AS
        WITH expanded AS (
          SELECT metrics.analytics_run_id, metrics.game_id, games.game_number,
            metrics.ticket_price, strategy.strategy_key, strategy.metric_value,
            metrics.metric_statuses ->> strategy.strategy_key AS metric_status,
            metrics.lowest_confidence, strategy.coverage
          FROM current_strategy_metrics_v metrics
          JOIN games ON games.id = metrics.game_id
          JOIN recommendation_current_games_v recommended ON recommended.id = metrics.game_id
          CROSS JOIN LATERAL (VALUES
            ('money_back_exact', metrics.p_break_even_exact, metrics.full_count_coverage),
            ('profit_ex_top', metrics.p_strict_profit_ex_top, metrics.ex_top_count_coverage),
            ('value_full', metrics.estimated_payout_ratio_full, metrics.full_value_coverage),
            ('value_ex_top', metrics.estimated_payout_ratio_ex_top, metrics.ex_top_value_coverage),
            ('moderate_5x', metrics.p_5x_or_better_ex_top, metrics.ex_top_count_coverage),
            ('moderate_10x', metrics.p_10x_or_better_ex_top, metrics.ex_top_count_coverage),
            ('jackpot_top_odds', metrics.p_top_prize_estimated, metrics.full_count_coverage),
            ('large_1000', metrics.p_1000_or_better, metrics.full_count_coverage),
            ('large_100000', metrics.p_100000_or_better, metrics.full_count_coverage)
          ) AS strategy(strategy_key, metric_value, coverage)
        ), eligible AS (
          SELECT * FROM expanded WHERE metric_status = 'complete' AND metric_value IS NOT NULL
        )
        SELECT eligible.*,
          dense_rank() OVER (PARTITION BY strategy_key ORDER BY metric_value DESC) rank_overall,
          dense_rank() OVER (
            PARTITION BY strategy_key, ticket_price ORDER BY metric_value DESC
          ) rank_within_ticket_price
        FROM eligible
        """
    )
