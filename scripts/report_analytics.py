#!/usr/bin/env python3
"""Report one explicit or latest analytics run without substituting cutoffs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.status import build_nightly_status
from illinois_lottery_tracker.db import get_engine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analytics-run-id", type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--nightly-status",
        action="store_true",
        help="report the complete source/catalog/analytics/protection status surface",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="explicit backup directory used to calculate backup/restore ages",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with Session(get_engine()) as session:
        if args.nightly_status:
            document = build_nightly_status(session, backup_dir=args.backup_dir)
            print(json.dumps(document, indent=2, sort_keys=True, default=str))
            return 0
        run_id = args.analytics_run_id or session.execute(
            text("SELECT id FROM analytics_runs ORDER BY as_of_observed_at DESC, id DESC LIMIT 1")
        ).scalar_one_or_none()
        if run_id is None:
            print("ERROR: no analytics run exists", file=sys.stderr)
            return 1
        row = session.execute(
            text(
                """
                SELECT ar.id, ar.status, ar.as_of_scrape_run_id,
                       ar.as_of_observed_at,
                       (SELECT count(*) FROM analytics_game_metrics gm
                        WHERE gm.analytics_run_id=ar.id) AS games,
                       (SELECT count(*) FROM analytics_tier_metrics tm
                        WHERE tm.analytics_run_id=ar.id) AS tiers,
                       (SELECT count(*) FROM analytics_tier_metrics tm
                        WHERE tm.analytics_run_id=ar.id
                          AND tm.adjustment_status='applied') AS high_adjusted,
                       (SELECT count(*) FROM analytics_tier_metrics tm
                        WHERE tm.analytics_run_id=ar.id
                          AND tm.adjustment_status='reference_unavailable')
                         AS high_reference_unavailable,
                       (SELECT count(*) FROM analytics_quality_issues qi
                        WHERE qi.analytics_run_id=ar.id) AS issues,
                       (SELECT count(*) FROM analytics_strategy_metrics sm
                        WHERE sm.analytics_run_id=ar.id) AS strategies
                FROM analytics_runs ar WHERE ar.id=:run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().one_or_none()
        if row is None:
            print(f"ERROR: analytics run {run_id} not found", file=sys.stderr)
            return 1
    document = {
        key: (value.isoformat() if hasattr(value, "isoformat") else value)
        for key, value in row.items()
    }
    if args.json:
        print(json.dumps(document, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"Analytics run {document['id']}: status={document['status']} "
            f"source_run={document['as_of_scrape_run_id']}"
        )
        print(
            f"Games={document['games']} tiers={document['tiers']} "
            f"high_adjusted={document['high_adjusted']} "
            f"high_reference_unavailable={document['high_reference_unavailable']} "
            f"issues={document['issues']} strategies={document['strategies']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
