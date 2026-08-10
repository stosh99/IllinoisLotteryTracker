"""Create canonical latest-complete source and current-game views."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_current_source_views"
down_revision: str | None = "0002_source_provenance_and_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW current_complete_scrape_run_v AS
        SELECT sr.*
        FROM scrape_runs sr
        WHERE sr.workflow = 'unpaid_prizes'
          AND sr.status = 'success'
          AND sr.is_complete
        ORDER BY sr.source_observed_at DESC, sr.id DESC
        LIMIT 1
        """
    )
    op.execute(
        """
        CREATE VIEW current_game_snapshots_v AS
        SELECT gs.*
        FROM game_snapshots gs
        JOIN current_complete_scrape_run_v current_run
          ON current_run.id = gs.scrape_run_id
        """
    )
    op.execute(
        """
        UPDATE games g
        SET is_active = EXISTS (
            SELECT 1 FROM current_game_snapshots_v current_snapshot
            WHERE current_snapshot.game_id = g.id
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW current_game_snapshots_v")
    op.execute("DROP VIEW current_complete_scrape_run_v")
