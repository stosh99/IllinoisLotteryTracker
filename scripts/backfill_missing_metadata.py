#!/usr/bin/env python
"""Fetch/import missing instant-ticket detail metadata for existing games."""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.metadata_backfill import (
    backfill_missing_game_metadata,
    render_metadata_backfill_result,
    stderr_progress,
)
from illinois_lottery_tracker.metrics import compute_snapshot_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill launch date, odds, and other detail metadata for games "
            "already seen in unpaid-prizes snapshots."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and stage metadata updates, then roll back instead of committing.",
    )
    parser.add_argument(
        "--max-detail-pages",
        type=int,
        metavar="N",
        help="Maximum instant-ticket detail pages to fetch.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages on stderr.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = backfill_missing_game_metadata(
                session,
                max_detail_pages=args.max_detail_pages,
                progress=None if args.quiet else stderr_progress,
            )
            metrics_result = compute_snapshot_metrics(session) if result.changed_games else None
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: metadata backfill failed: {exc}", file=sys.stderr)
            return 1

    mode = "DRY RUN - rolled back" if args.dry_run else "committed"
    print(f"Mode: {mode}")
    print(render_metadata_backfill_result(result), end="")
    if metrics_result is not None:
        print("Metrics recompute:")
        print(f"  Games updated:                {metrics_result.games_updated}")
        print(f"  Snapshots computed:           {metrics_result.snapshots_computed}")
        print(f"  Skipped no odds:              {metrics_result.snapshots_skipped_no_odds}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
