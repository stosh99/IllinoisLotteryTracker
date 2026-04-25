"""Verify that the configured PostgreSQL database is reachable."""

from __future__ import annotations

import sys

from sqlalchemy import text

from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.db import get_engine


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print(
            "ERROR: DATABASE_URL is not set. Copy .env.example to .env and configure it.",
            file=sys.stderr,
        )
        return 2

    try:
        engine = get_engine(settings)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT current_database(), current_user")).one()
        print(f"OK: connected to database={row[0]!r} as user={row[1]!r}")
        return 0
    except Exception as exc:  # noqa: BLE001 — top-level CLI surface
        print(f"ERROR: database connection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
