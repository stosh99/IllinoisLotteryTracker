#!/usr/bin/env python3
"""Calibrate and persist the adaptive relative high-tier reporting lag."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.service import calibrate_claim_lag
from illinois_lottery_tracker.db import get_engine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    cutoff = parser.add_mutually_exclusive_group()
    cutoff.add_argument("--cutoff-run-id", type=int)
    cutoff.add_argument("--source-date", type=date.fromisoformat)
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with Session(get_engine(), expire_on_commit=False) as session:
        try:
            result = calibrate_claim_lag(
                session,
                scrape_run_id=args.cutoff_run_id,
                source_date=args.source_date,
                semantic_version=args.model_version,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: lag calibration failed: {exc}", file=sys.stderr)
            return 1
    print(
        f"analytics_run_id={result.analytics_run_id} status={result.status} "
        f"candidates={result.candidate_game_count} "
        f"primary={result.primary_qualified_game_count} "
        f"positive={result.positive_game_count} median_days={result.median_lag_days} "
        f"q1={result.q1_lag_days} q3={result.q3_lag_days} "
        f"bootstrap95={result.bootstrap_lower_lag_days}..{result.bootstrap_upper_lag_days} "
        f"reused={str(result.reused).lower()} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
