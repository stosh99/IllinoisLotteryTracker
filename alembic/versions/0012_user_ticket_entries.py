"""Add private user-owned ticket result history."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_user_ticket_entries"
down_revision: str | None = "0011_defer_auth_event_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_ticket_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_number", sa.String(32), nullable=False),
        sa.Column("game_name", sa.Text(), nullable=False),
        sa.Column("ticket_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("played_on", sa.Date(), nullable=False),
        sa.Column("ticket_count", sa.Integer(), nullable=False),
        sa.Column("amount_won", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("ticket_price > 0", name="ck_user_ticket_entries_price_positive"),
        sa.CheckConstraint(
            "ticket_count > 0 AND ticket_count <= 1000",
            name="ck_user_ticket_entries_count_range",
        ),
        sa.CheckConstraint(
            "amount_won >= 0 AND amount_won <= 1000000000",
            name="ck_user_ticket_entries_winnings_range",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_user_ticket_entries_updated_at"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_ticket_entries_user_played",
        "user_ticket_entries",
        ["user_id", "played_on", "created_at"],
    )
    op.create_index("ix_user_ticket_entries_game", "user_ticket_entries", ["game_id"])


def downgrade() -> None:
    op.drop_table("user_ticket_entries")
