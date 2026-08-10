#!/usr/bin/env python3
"""Backfill versioned analytics in cutoff order with per-cutoff commits."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy.orm import sessionmaker

from illinois_lottery_tracker.analytics.backfill import backfill_analytics
from illinois_lottery_tracker.db import get_engine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--from-source-date", type=date.fromisoformat)
    parser.add_argument("--to-source-date", type=date.fromisoformat)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        args.from_source_date is not None
        and args.to_source_date is not None
        and args.from_source_date > args.to_source_date
    ):
        print("ERROR: --from-source-date must not be after --to-source-date", file=sys.stderr)
        return 2
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    try:
        result = backfill_analytics(
            factory,
            semantic_version=args.model_version,
            from_source_date=args.from_source_date,
            to_source_date=args.to_source_date,
            resume=args.resume,
            force=args.force,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: analytics backfill failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"requested={result.requested} attempted={result.attempted} "
        f"success={result.succeeded} failed={result.failed} skipped={result.skipped} "
        f"failed_cutoffs={','.join(map(str, result.failed_cutoffs)) or 'none'} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
