"""Create the schema that existed before Alembic was introduced."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_existing_schema_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_file_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_runs_started_at", "scrape_runs", ["started_at"])
    op.create_index("ix_scrape_runs_status", "scrape_runs", ["status"])

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_number", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("ticket_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("launch_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("overall_odds_one_in", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("est_total_tickets", sa.BigInteger(), nullable=True),
        sa.Column("top_prize_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("play_style", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_number"),
    )
    op.create_index("ix_games_is_active", "games", ["is_active"])

    op.create_table(
        "raw_source_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_source_snapshots_captured_at", "raw_source_snapshots", ["captured_at"])
    op.create_index("ix_raw_source_snapshots_sha256", "raw_source_snapshots", ["sha256"])

    op.create_table(
        "game_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_original_prize_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_remaining_prize_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_original_winning_tickets", sa.BigInteger(), nullable=True),
        sa.Column("total_remaining_winning_tickets", sa.BigInteger(), nullable=True),
        sa.Column("top_prizes_original", sa.Integer(), nullable=True),
        sa.Column("top_prizes_remaining", sa.Integer(), nullable=True),
        sa.Column("weeks_in_market", sa.Integer(), nullable=True),
        sa.Column("estimated_tickets_remaining", sa.BigInteger(), nullable=True),
        sa.Column("estimated_ev", sa.Numeric(14, 6), nullable=True),
        sa.Column("estimated_ev_excluding_top_prize", sa.Numeric(14, 6), nullable=True),
        sa.Column("estimated_payout_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("estimated_house_edge", sa.Numeric(10, 6), nullable=True),
        sa.Column("estimated_payout_ratio_excluding_top_prize", sa.Numeric(10, 6), nullable=True),
        sa.Column("launch_ev", sa.Numeric(14, 6), nullable=True),
        sa.Column("launch_payout_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("ev_vs_launch_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("remaining_prize_value_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("remaining_winning_tickets_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("top_prize_remaining_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("top_prize_depleted", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "scrape_run_id", name="uq_game_snapshots_game_scrape_run"),
    )
    op.create_index("ix_game_snapshots_captured_at", "game_snapshots", ["captured_at"])
    op.create_index(
        "ix_game_snapshots_game_id_captured_at",
        "game_snapshots",
        ["game_id", "captured_at"],
    )

    op.create_table(
        "prize_tier_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("prize_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("original_count", sa.BigInteger(), nullable=True),
        sa.Column("remaining_count", sa.BigInteger(), nullable=True),
        sa.Column("claimed_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["game_snapshot_id"], ["game_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_snapshot_id",
            "prize_amount",
            name="uq_prize_tier_snapshots_snapshot_amount",
        ),
    )


def downgrade() -> None:
    op.drop_table("prize_tier_snapshots")
    op.drop_index("ix_game_snapshots_game_id_captured_at", table_name="game_snapshots")
    op.drop_index("ix_game_snapshots_captured_at", table_name="game_snapshots")
    op.drop_table("game_snapshots")
    op.drop_index("ix_raw_source_snapshots_sha256", table_name="raw_source_snapshots")
    op.drop_index("ix_raw_source_snapshots_captured_at", table_name="raw_source_snapshots")
    op.drop_table("raw_source_snapshots")
    op.drop_index("ix_games_is_active", table_name="games")
    op.drop_table("games")
    op.drop_index("ix_scrape_runs_status", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")
