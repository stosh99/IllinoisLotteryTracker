"""Normalize retail catalog membership and metadata retry attempts."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_catalog_and_metadata_attempts"
down_revision: str | None = "0003_current_source_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_catalog_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("ticket_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("top_prize_text", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("card_position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "card_position >= 0", name="ck_catalog_card_position_nonnegative"
        ),
        sa.CheckConstraint("page_number > 0", name="ck_catalog_page_number_positive"),
        sa.CheckConstraint("ticket_price > 0", name="ck_catalog_ticket_price_positive"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"], ["scrape_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scrape_run_id", "detail_url", name="uq_catalog_snapshots_run_url"
        ),
    )
    op.create_index(
        "ix_catalog_snapshots_game_run",
        "game_catalog_snapshots",
        ["game_id", "scrape_run_id"],
    )
    op.create_index(
        "ix_catalog_snapshots_detail_url", "game_catalog_snapshots", ["detail_url"]
    )

    op.create_table(
        "metadata_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_url", sa.Text(), nullable=True),
        sa.Column("outcome_code", sa.String(32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="ck_metadata_attempt_number_positive"),
        sa.CheckConstraint(
            "outcome_code IN ('success', 'no_candidate', 'ambiguous', "
            "'fetch_failed', 'parse_failed', 'not_due')",
            name="ck_metadata_attempt_outcome",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metadata_attempts_game_attempted",
        "metadata_attempts",
        ["game_id", sa.text("attempted_at DESC")],
    )
    op.create_index(
        "ix_metadata_attempts_next_retry", "metadata_attempts", ["next_retry_at"]
    )

    op.execute(
        """
        CREATE VIEW current_complete_catalog_run_v AS
        SELECT sr.*
        FROM scrape_runs sr
        WHERE sr.workflow = 'instant_ticket_catalog'
          AND sr.status = 'success'
          AND sr.is_complete
        ORDER BY sr.source_observed_at DESC, sr.id DESC
        LIMIT 1
        """
    )
    op.execute(
        """
        CREATE VIEW current_catalog_games_v AS
        SELECT DISTINCT ON (catalog.game_id)
            catalog.game_id,
            catalog.scrape_run_id,
            catalog.id AS catalog_snapshot_id,
            catalog.detail_url,
            catalog.display_name,
            catalog.ticket_price
        FROM game_catalog_snapshots catalog
        JOIN current_complete_catalog_run_v current_run
          ON current_run.id = catalog.scrape_run_id
        WHERE catalog.game_id IS NOT NULL
        ORDER BY catalog.game_id, catalog.id
        """
    )
    op.execute(
        """
        CREATE VIEW current_game_source_reconciliation_v AS
        SELECT
            g.id AS game_id,
            g.game_number,
            EXISTS (
                SELECT 1 FROM current_game_snapshots_v source
                WHERE source.game_id = g.id
            ) AS prize_source_current,
            EXISTS (
                SELECT 1 FROM current_catalog_games_v catalog
                WHERE catalog.game_id = g.id
            ) AS catalog_current,
            EXISTS (
                SELECT 1 FROM current_game_snapshots_v source
                WHERE source.game_id = g.id
            ) AND EXISTS (
                SELECT 1 FROM current_catalog_games_v catalog
                WHERE catalog.game_id = g.id
            ) AS recommendation_current
        FROM games g
        """
    )
    op.execute(
        """
        CREATE VIEW recommendation_current_games_v AS
        SELECT g.*
        FROM games g
        JOIN current_game_source_reconciliation_v status ON status.game_id = g.id
        WHERE status.recommendation_current
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW recommendation_current_games_v")
    op.execute("DROP VIEW current_game_source_reconciliation_v")
    op.execute("DROP VIEW current_catalog_games_v")
    op.execute("DROP VIEW current_complete_catalog_run_v")
    op.drop_index("ix_metadata_attempts_next_retry", table_name="metadata_attempts")
    op.drop_index("ix_metadata_attempts_game_attempted", table_name="metadata_attempts")
    op.drop_table("metadata_attempts")
    op.drop_index(
        "ix_catalog_snapshots_detail_url", table_name="game_catalog_snapshots"
    )
    op.drop_index("ix_catalog_snapshots_game_run", table_name="game_catalog_snapshots")
    op.drop_table("game_catalog_snapshots")
