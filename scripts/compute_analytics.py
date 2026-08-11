#!/usr/bin/env python3
"""Compute all versioned analytics for one source cutoff."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.service import compute_analytics
from illinois_lottery_tracker.db import get_engine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    cutoff = parser.add_mutually_exclusive_group()
    cutoff.add_argument("--cutoff-run-id", type=int, help="complete source scrape-run ID")
    cutoff.add_argument("--source-date", type=date.fromisoformat, help="Chicago date YYYY-MM-DD")
    parser.add_argument("--model-version", default="2.0.0")
    parser.add_argument("--dry-run", action="store_true", help="compute then roll back")
    parser.add_argument(
        "--force",
        action="store_true",
        help="reject reuse of an immutable successful run; use a new model version",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with Session(get_engine(), expire_on_commit=False) as session:
        try:
            result = compute_analytics(
                session,
                scrape_run_id=args.cutoff_run_id,
                source_date=args.source_date,
                semantic_version=args.model_version,
                force=args.force,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: analytics computation failed: {exc}", file=sys.stderr)
            return 1
    print(
        f"analytics_run_id={result.analytics_run_id} source_run_id={result.source_run_id} "
        f"games={result.game_count} tiers={result.tier_count} "
        f"regular={result.regular_scored_count} high={result.high_tier_count} "
        f"high_adjusted={result.high_adjusted_count} "
        f"high_reported_only={result.high_reported_only_count} "
        f"issues={result.issue_count} reused={str(result.reused_successful_run).lower()} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
