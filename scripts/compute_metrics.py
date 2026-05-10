"""Compute and persist normalized snapshot metrics for all games.

Calculates estimated total tickets (game level), estimated remaining tickets,
estimated EV per ticket, payout ratios, launch-comparison metrics, and
remaining-prize/count fractions for every game snapshot. All values are derived
from existing raw data — no raw values are modified.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.metrics import compute_snapshot_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute and persist normalized snapshot metrics."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and stage metrics, then roll back instead of committing.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = compute_snapshot_metrics(session)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: metrics computation failed: {exc}", file=sys.stderr)
            return 1

    mode = "DRY RUN - rolled back" if args.dry_run else "committed"
    print(f"Mode: {mode}")
    print(f"Games updated (est_total_tickets):      {result.games_updated}")
    print(f"Snapshots with non-odds metrics:        {result.snapshots_with_nonodds_metrics}")
    print(f"Snapshots computed (odds-dependent):    {result.snapshots_computed}")
    print(f"Snapshots skipped (no odds):            {result.snapshots_skipped_no_odds}")
    print(f"Snapshots skipped (no remaining count): {result.snapshots_skipped_no_counts}")
    if result.issues:
        for issue in result.issues:
            print(f"  issue: {issue}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
