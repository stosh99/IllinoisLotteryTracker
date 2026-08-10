"""Compute direct descriptive ratios or explicitly requested legacy metrics.

The all-winner-denominator estimates are superseded and are never written
unless ``--legacy`` is explicitly supplied for transition auditing.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.metrics import compute_snapshot_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute direct ratios; legacy estimates require --legacy."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and stage metrics, then roll back instead of committing.",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="explicitly recompute superseded estimated_* columns for transition audit",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = compute_snapshot_metrics(session, include_legacy=args.legacy)
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
    print(
        "Metric family: "
        + ("LEGACY all-winner denominator (superseded)" if args.legacy else "observed ratios")
    )
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
