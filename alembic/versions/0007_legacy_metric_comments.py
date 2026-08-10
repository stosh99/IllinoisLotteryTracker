"""Label retained legacy metric columns with canonical replacements."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_legacy_metric_comments"
down_revision: str | None = "0006_backtesting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GAME_COMMENT = (
    "LEGACY transition field; no longer written nightly. Replacement: "
    "analytics_game_metrics.estimated_original_tickets for an explicit model/cutoff."
)
SNAPSHOT_REPLACEMENTS = {
    "estimated_tickets_remaining": "analytics_game_metrics.estimated_remaining_tickets",
    "estimated_ev": "analytics_strategy_metrics.estimated_ev_full",
    "estimated_ev_excluding_top_prize": "analytics_strategy_metrics.estimated_ev_ex_top",
    "estimated_payout_ratio": "analytics_strategy_metrics.estimated_payout_ratio_full",
    "estimated_house_edge": "analytics_strategy_metrics.estimated_house_edge_full",
    "estimated_payout_ratio_excluding_top_prize": (
        "analytics_strategy_metrics.estimated_payout_ratio_ex_top"
    ),
    "launch_ev": "analytics_strategy_metrics.launch_ev_full",
    "launch_payout_ratio": "analytics_strategy_metrics launch EV divided by ticket price",
    "ev_vs_launch_ratio": "analytics_strategy_metrics.ev_full_vs_launch",
}


def upgrade() -> None:
    escaped = GAME_COMMENT.replace("'", "''")
    op.execute(f"COMMENT ON COLUMN games.est_total_tickets IS '{escaped}'")
    for column, replacement in SNAPSHOT_REPLACEMENTS.items():
        comment = (
            "LEGACY transition field; no longer written nightly. Replacement: "
            f"{replacement} for an explicit model/cutoff."
        ).replace("'", "''")
        op.execute(
            f"COMMENT ON COLUMN game_snapshots.{column} IS '{comment}'"
        )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN games.est_total_tickets IS NULL")
    for column in SNAPSHOT_REPLACEMENTS:
        op.execute(f"COMMENT ON COLUMN game_snapshots.{column} IS NULL")
