"""Add source provenance, deterministic fingerprints, and raw-data constraints."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_source_provenance_and_constraints"
down_revision: str | None = "0001_existing_schema_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The descriptive blueprint revision identifiers exceed Alembic's default
    # 32-character version column.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "scrape_runs",
        sa.Column(
            "workflow",
            sa.String(length=32),
            server_default="unpaid_prizes",
            nullable=False,
        ),
    )
    op.add_column(
        "scrape_runs", sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("scrape_runs", sa.Column("source_date", sa.Date(), nullable=True))
    op.add_column("scrape_runs", sa.Column("source_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "scrape_runs",
        sa.Column("is_complete", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("scrape_runs", sa.Column("parsed_game_count", sa.Integer(), nullable=True))
    op.add_column(
        "scrape_runs", sa.Column("parsed_prize_tier_count", sa.Integer(), nullable=True)
    )
    op.add_column("scrape_runs", sa.Column("pipeline_version", sa.String(64), nullable=True))
    op.add_column(
        "scrape_runs", sa.Column("manually_approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("scrape_runs", sa.Column("manual_approval_reason", sa.Text(), nullable=True))
    op.add_column(
        "game_snapshots", sa.Column("structure_fingerprint", sa.String(64), nullable=True)
    )

    op.execute(
        """
        WITH raw AS (
            SELECT
                scrape_run_id,
                min(captured_at) AS observed_at,
                min(sha256) AS source_sha256,
                count(*) AS raw_count
            FROM raw_source_snapshots
            GROUP BY scrape_run_id
        ), games AS (
            SELECT scrape_run_id, count(*) AS game_count
            FROM game_snapshots
            GROUP BY scrape_run_id
        ), tiers AS (
            SELECT gs.scrape_run_id, count(p.id) AS tier_count
            FROM game_snapshots gs
            JOIN prize_tier_snapshots p ON p.game_snapshot_id = gs.id
            GROUP BY gs.scrape_run_id
        )
        UPDATE scrape_runs sr
        SET
            source_observed_at = raw.observed_at,
            source_date = (raw.observed_at AT TIME ZONE 'America/Chicago')::date,
            source_sha256 = raw.source_sha256,
            parsed_game_count = coalesce(games.game_count, 0),
            parsed_prize_tier_count = coalesce(tiers.tier_count, 0),
            pipeline_version = coalesce(sr.parser_version, 'historical-backfill-0002'),
            is_complete = (
                sr.status = 'success'
                AND raw.raw_count = 1
                AND coalesce(games.game_count, 0) > 0
                AND coalesce(tiers.tier_count, 0) > 0
            )
        FROM raw
        LEFT JOIN games ON games.scrape_run_id = raw.scrape_run_id
        LEFT JOIN tiers ON tiers.scrape_run_id = raw.scrape_run_id
        WHERE sr.id = raw.scrape_run_id
        """
    )
    op.execute(
        """
        UPDATE game_snapshots gs
        SET captured_at = sr.source_observed_at
        FROM scrape_runs sr
        WHERE sr.id = gs.scrape_run_id
          AND sr.source_observed_at IS NOT NULL
        """
    )
    op.execute(
        """
        WITH serialized AS (
            SELECT
                p.game_snapshot_id,
                string_agg(
                    to_char(p.prize_amount, 'FM999999999990.00')
                    || ':' || p.original_count::text,
                    '|' ORDER BY p.prize_amount
                ) AS structure_text
            FROM prize_tier_snapshots p
            GROUP BY p.game_snapshot_id
        )
        UPDATE game_snapshots gs
        SET structure_fingerprint = encode(
            sha256(convert_to(serialized.structure_text, 'UTF8')),
            'hex'
        )
        FROM serialized
        WHERE serialized.game_snapshot_id = gs.id
        """
    )

    op.alter_column("prize_tier_snapshots", "original_count", nullable=False)
    op.alter_column("prize_tier_snapshots", "remaining_count", nullable=False)
    op.alter_column("prize_tier_snapshots", "claimed_count", nullable=False)

    op.create_check_constraint(
        "ck_scrape_runs_status",
        "scrape_runs",
        "status IN ('running', 'success', 'failed', 'quarantined')",
    )
    op.create_check_constraint(
        "ck_scrape_runs_workflow",
        "scrape_runs",
        "workflow IN ('unpaid_prizes', 'instant_ticket_catalog')",
    )
    op.create_check_constraint(
        "ck_scrape_runs_parsed_game_count_nonnegative",
        "scrape_runs",
        "parsed_game_count IS NULL OR parsed_game_count >= 0",
    )
    op.create_check_constraint(
        "ck_scrape_runs_parsed_tier_count_nonnegative",
        "scrape_runs",
        "parsed_prize_tier_count IS NULL OR parsed_prize_tier_count >= 0",
    )
    op.create_check_constraint(
        "ck_scrape_runs_finished_after_started",
        "scrape_runs",
        "finished_at IS NULL OR finished_at >= started_at",
    )
    op.create_check_constraint(
        "ck_scrape_runs_source_sha256",
        "scrape_runs",
        "source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_scrape_runs_complete_provenance",
        "scrape_runs",
        "NOT (workflow = 'unpaid_prizes' AND status = 'success' AND is_complete) OR "
        "(source_observed_at IS NOT NULL AND source_date IS NOT NULL "
        "AND source_sha256 IS NOT NULL AND parsed_game_count > 0 "
        "AND parsed_prize_tier_count > 0)",
    )
    op.create_check_constraint(
        "ck_scrape_runs_source_date_chicago",
        "scrape_runs",
        "source_observed_at IS NULL OR source_date IS NULL OR "
        "source_date = (source_observed_at AT TIME ZONE 'America/Chicago')::date",
    )
    op.create_check_constraint(
        "ck_games_ticket_price_positive",
        "games",
        "ticket_price IS NULL OR ticket_price > 0",
    )
    op.create_check_constraint(
        "ck_games_overall_odds_greater_than_one",
        "games",
        "overall_odds_one_in IS NULL OR overall_odds_one_in > 1",
    )
    for name, expression in (
        (
            "ck_game_snapshots_original_value_nonnegative",
            "total_original_prize_value IS NULL OR total_original_prize_value >= 0",
        ),
        (
            "ck_game_snapshots_remaining_value_nonnegative",
            "total_remaining_prize_value IS NULL OR total_remaining_prize_value >= 0",
        ),
        (
            "ck_game_snapshots_original_count_nonnegative",
            "total_original_winning_tickets IS NULL OR total_original_winning_tickets >= 0",
        ),
        (
            "ck_game_snapshots_remaining_count_nonnegative",
            "total_remaining_winning_tickets IS NULL OR total_remaining_winning_tickets >= 0",
        ),
        (
            "ck_game_snapshots_remaining_not_above_original",
            "total_original_winning_tickets IS NULL OR "
            "total_remaining_winning_tickets IS NULL OR "
            "total_remaining_winning_tickets <= total_original_winning_tickets",
        ),
        (
            "ck_game_snapshots_top_original_nonnegative",
            "top_prizes_original IS NULL OR top_prizes_original >= 0",
        ),
        (
            "ck_game_snapshots_top_remaining_nonnegative",
            "top_prizes_remaining IS NULL OR top_prizes_remaining >= 0",
        ),
        (
            "ck_game_snapshots_top_remaining_not_above_original",
            "top_prizes_original IS NULL OR top_prizes_remaining IS NULL OR "
            "top_prizes_remaining <= top_prizes_original",
        ),
        (
            "ck_game_snapshots_weeks_nonnegative",
            "weeks_in_market IS NULL OR weeks_in_market >= 0",
        ),
        (
            "ck_game_snapshots_structure_fingerprint",
            "structure_fingerprint IS NULL OR "
            "structure_fingerprint ~ '^[0-9a-f]{64}$'",
        ),
    ):
        op.create_check_constraint(name, "game_snapshots", expression)

    for name, expression in (
        ("ck_prize_tiers_amount_positive", "prize_amount > 0"),
        ("ck_prize_tiers_original_nonnegative", "original_count >= 0"),
        ("ck_prize_tiers_remaining_nonnegative", "remaining_count >= 0"),
        ("ck_prize_tiers_claimed_nonnegative", "claimed_count >= 0"),
        (
            "ck_prize_tiers_remaining_not_above_original",
            "remaining_count <= original_count",
        ),
        (
            "ck_prize_tiers_claimed_identity",
            "claimed_count = original_count - remaining_count",
        ),
    ):
        op.create_check_constraint(name, "prize_tier_snapshots", expression)

    op.create_index(
        "ix_scrape_runs_workflow_complete_observed",
        "scrape_runs",
        ["workflow", "is_complete", sa.text("source_observed_at DESC")],
    )
    op.create_index("ix_scrape_runs_source_date", "scrape_runs", ["source_date"])
    op.create_index(
        "uq_scrape_runs_complete_unpaid_sha256",
        "scrape_runs",
        ["workflow", "source_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "workflow = 'unpaid_prizes' AND status = 'success' AND is_complete"
        ),
    )
    op.create_index(
        "ix_raw_source_snapshots_scrape_run_id", "raw_source_snapshots", ["scrape_run_id"]
    )
    op.create_index("ix_game_snapshots_scrape_run_id", "game_snapshots", ["scrape_run_id"])
    op.create_index(
        "ix_game_snapshots_game_id_structure_fingerprint",
        "game_snapshots",
        ["game_id", "structure_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_snapshots_game_id_structure_fingerprint", table_name="game_snapshots"
    )
    op.drop_index("ix_game_snapshots_scrape_run_id", table_name="game_snapshots")
    op.drop_index("ix_raw_source_snapshots_scrape_run_id", table_name="raw_source_snapshots")
    op.drop_index("uq_scrape_runs_complete_unpaid_sha256", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_source_date", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_workflow_complete_observed", table_name="scrape_runs")

    for constraint in (
        "ck_prize_tiers_claimed_identity",
        "ck_prize_tiers_remaining_not_above_original",
        "ck_prize_tiers_claimed_nonnegative",
        "ck_prize_tiers_remaining_nonnegative",
        "ck_prize_tiers_original_nonnegative",
        "ck_prize_tiers_amount_positive",
    ):
        op.drop_constraint(constraint, "prize_tier_snapshots", type_="check")
    for constraint in (
        "ck_game_snapshots_structure_fingerprint",
        "ck_game_snapshots_weeks_nonnegative",
        "ck_game_snapshots_top_remaining_not_above_original",
        "ck_game_snapshots_top_remaining_nonnegative",
        "ck_game_snapshots_top_original_nonnegative",
        "ck_game_snapshots_remaining_not_above_original",
        "ck_game_snapshots_remaining_count_nonnegative",
        "ck_game_snapshots_original_count_nonnegative",
        "ck_game_snapshots_remaining_value_nonnegative",
        "ck_game_snapshots_original_value_nonnegative",
    ):
        op.drop_constraint(constraint, "game_snapshots", type_="check")
    op.drop_constraint("ck_games_overall_odds_greater_than_one", "games", type_="check")
    op.drop_constraint("ck_games_ticket_price_positive", "games", type_="check")
    for constraint in (
        "ck_scrape_runs_source_date_chicago",
        "ck_scrape_runs_complete_provenance",
        "ck_scrape_runs_source_sha256",
        "ck_scrape_runs_finished_after_started",
        "ck_scrape_runs_parsed_tier_count_nonnegative",
        "ck_scrape_runs_parsed_game_count_nonnegative",
        "ck_scrape_runs_workflow",
        "ck_scrape_runs_status",
    ):
        op.drop_constraint(constraint, "scrape_runs", type_="check")

    op.alter_column("prize_tier_snapshots", "claimed_count", nullable=True)
    op.alter_column("prize_tier_snapshots", "remaining_count", nullable=True)
    op.alter_column("prize_tier_snapshots", "original_count", nullable=True)
    op.drop_column("game_snapshots", "structure_fingerprint")
    for column in (
        "manual_approval_reason",
        "manually_approved_at",
        "pipeline_version",
        "parsed_prize_tier_count",
        "parsed_game_count",
        "is_complete",
        "source_sha256",
        "source_date",
        "source_observed_at",
        "workflow",
    ):
        op.drop_column("scrape_runs", column)
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
