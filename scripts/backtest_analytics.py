#!/usr/bin/env python3
"""Run the canonical cutoff-strict walk-forward analytics backtest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.backtest import run_walk_forward_backtest
from illinois_lottery_tracker.analytics_models import AnalyticsBacktestRun
from illinois_lottery_tracker.db import get_engine


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--cutoff-start", type=_timestamp)
    parser.add_argument("--cutoff-end", type=_timestamp)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report-json", action="store_true", help="print the promotion report as JSON"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with Session(get_engine(), expire_on_commit=False) as session:
        try:
            result = run_walk_forward_backtest(
                session,
                semantic_version=args.model_version,
                cutoff_start=args.cutoff_start,
                cutoff_end=args.cutoff_end,
            )
            run = session.get(AnalyticsBacktestRun, result.backtest_run_id)
            report = run.promotion_report if run else {}
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: backtest failed: {exc}", file=sys.stderr)
            return 1
    print(
        f"backtest_run_id={result.backtest_run_id} cutoffs={result.cutoff_count} "
        f"predictions={result.prediction_count} eligible={result.eligible_prediction_count} "
        f"excluded={result.excluded_prediction_count} summaries={result.summary_count} "
        f"promotion={result.promotion_status} reused={str(result.reused).lower()} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    if args.report_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
