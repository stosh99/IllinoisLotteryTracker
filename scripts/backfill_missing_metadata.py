#!/usr/bin/env python
"""Fetch/import missing instant-ticket detail metadata for existing games."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.metadata_backfill import (
    backfill_missing_game_metadata,
    collect_metadata_network_inputs,
    plan_metadata_targets,
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
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Run the separately scheduled weekly refresh for every current catalog game.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore persisted retry times (does not bypass candidate matching).",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    engine = get_engine()
    observed_now = datetime.now(UTC)
    with Session(engine, expire_on_commit=False, future=True) as planning_session:
        plan = plan_metadata_targets(
            planning_session,
            full_refresh=args.full_refresh,
            force=args.force,
            now=observed_now,
        )
        planning_session.rollback()
    try:
        network_inputs = collect_metadata_network_inputs(
            plan,
            max_detail_pages=args.max_detail_pages,
            progress=None if args.quiet else stderr_progress,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: metadata collection failed: {exc}", file=sys.stderr)
        return 1
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = backfill_missing_game_metadata(
                session,
                max_detail_pages=args.max_detail_pages,
                progress=None if args.quiet else stderr_progress,
                full_refresh=args.full_refresh,
                force=args.force,
                now=observed_now,
                network_inputs=network_inputs,
            )
            metrics_result = (
                compute_snapshot_metrics(session, include_legacy=False)
                if result.changed_games
                else None
            )
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
