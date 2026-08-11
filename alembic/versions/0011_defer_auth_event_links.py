"""Make auth-event anonymization independent of cascade trigger order."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_defer_auth_event_links"
down_revision: str | None = "0010_simplified_high_prize_adjustment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINTS = (
    "auth_events_user_id_fkey",
    "auth_events_session_id_fkey",
    "auth_events_attempt_id_fkey",
)


def upgrade() -> None:
    for name in CONSTRAINTS:
        op.execute(
            f"ALTER TABLE auth_events ALTER CONSTRAINT {name} "
            "DEFERRABLE INITIALLY DEFERRED"
        )


def downgrade() -> None:
    for name in CONSTRAINTS:
        op.execute(
            f"ALTER TABLE auth_events ALTER CONSTRAINT {name} "
            "NOT DEFERRABLE INITIALLY IMMEDIATE"
        )
