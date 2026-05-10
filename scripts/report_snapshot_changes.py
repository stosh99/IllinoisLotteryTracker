"""Read-only snapshot change report for the unpaid-prizes pipeline.

Compares two unpaid-prizes snapshot sets and reports:
  - New games: appeared in the newer snapshot but not the older.
  - Missing from latest snapshot: appeared in the older but not the newer.
  - Prize structure changes: same game in both, but original prize structure
    fields (prize value, ticket counts, prize tiers) differ.

This script never modifies the database.

Usage:
    # Compare the latest two scrape runs (default):
    python scripts/report_snapshot_changes.py

    # Compare specific runs by ID:
    python scripts/report_snapshot_changes.py --older-run-id 1 --newer-run-id 2
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.snapshot_changes import (
    InsufficientDataError,
    MissingGameRow,
    NewGameRow,
    SnapshotChangeReport,
    StructureChangeRow,
    compare_scrape_runs,
    find_latest_two_comparable_runs,
)


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_price(price: Decimal | None) -> str:
    if price is None:
        return "n/a"
    return f"${price:,.2f}"


def _fmt_count(n: int | None) -> str:
    if n is None:
        return "n/a"
    return f"{n:,}"


def _print_report(report: SnapshotChangeReport) -> None:
    print("Snapshot Change Report")
    print("======================")
    print()
    print(f"Older run:  scrape_run_id={report.older_scrape_run_id}"
          f"   source={_fmt_dt(report.older_source_captured_at)}"
          f"   imported={_fmt_dt(report.older_run_started_at)}")
    print(f"Newer run:  scrape_run_id={report.newer_scrape_run_id}"
          f"   source={_fmt_dt(report.newer_source_captured_at)}"
          f"   imported={_fmt_dt(report.newer_run_started_at)}")
    print()
    print(f"Games in older snapshot:      {report.older_game_count}")
    print(f"Games in newer snapshot:      {report.newer_game_count}")
    print(f"New games:                    {report.new_game_count}")
    print(f"Missing from latest snapshot: {report.missing_game_count}")
    print(f"Prize structure changes:      {report.structure_change_count}")

    # --- New games ---
    print()
    print(f"=== New Games ({report.new_game_count}) ===")
    if not report.new_games:
        print("  (none)")
    else:
        for row in report.new_games:
            _print_new_game(row)

    # --- Missing games ---
    print()
    print(f"=== Missing from Latest Snapshot ({report.missing_game_count}) ===")
    if not report.missing_games:
        print("  (none)")
    else:
        for row in report.missing_games:
            _print_missing_game(row)

    # --- Structure changes ---
    print()
    print(f"=== Prize Structure Changes ({report.structure_change_count}) ===")
    if not report.structure_changes:
        print("  (none)")
    else:
        for row in report.structure_changes:
            _print_structure_change(row)


def _print_new_game(row: NewGameRow) -> None:
    flags = []
    flags.append("detail=yes" if row.has_detail_metadata else "detail=no")
    flags.append("odds=yes" if row.has_odds else "odds=no")
    flags.append("metrics=yes" if row.has_metrics else "metrics=no")
    print(
        f"  [{row.game_number}] {row.game_name}"
        f"  {_fmt_price(row.ticket_price)}"
        f"  {', '.join(flags)}"
    )


def _print_missing_game(row: MissingGameRow) -> None:
    active = "active" if row.is_active else "inactive"
    print(
        f"  [{row.game_number}] {row.game_name}"
        f"  {_fmt_price(row.ticket_price)}"
        f"  last_seen_run={row.last_seen_scrape_run_id}"
        f"  ({active} in games table)"
    )


def _print_structure_change(row: StructureChangeRow) -> None:
    print()
    print(f"  [{row.game_number}] {row.game_name}")
    print(f"    Changed: {', '.join(row.changed_fields)}")
    print(
        f"    total_original_prize_value:     "
        f"{_fmt_price(row.old_total_original_prize_value)} "
        f"→ {_fmt_price(row.new_total_original_prize_value)}"
    )
    print(
        f"    total_original_winning_tickets: "
        f"{_fmt_count(row.old_total_original_winning_tickets)} "
        f"→ {_fmt_count(row.new_total_original_winning_tickets)}"
    )
    print(
        f"    top_prizes_original:            "
        f"{_fmt_count(row.old_top_prizes_original)} "
        f"→ {_fmt_count(row.new_top_prizes_original)}"
    )
    if row.old_est_total_tickets is not None or row.new_est_total_tickets is not None:
        print(
            f"    est_total_tickets:              "
            f"{_fmt_count(row.old_est_total_tickets)} "
            f"→ {_fmt_count(row.new_est_total_tickets)}"
        )
    if row.prize_tier_changes:
        print("    Prize tier original_count changes:")
        for tc in row.prize_tier_changes:
            old = _fmt_count(tc.old_original_count)
            new = _fmt_count(tc.new_original_count)
            print(f"      ${tc.prize_amount:>10,.2f}:  {old} → {new}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only snapshot change report: new games, missing games, "
            "and original prize structure changes between two scrape runs."
        )
    )
    parser.add_argument(
        "--older-run-id",
        type=int,
        metavar="ID",
        help="Scrape run ID to use as the older (baseline) snapshot set.",
    )
    parser.add_argument(
        "--newer-run-id",
        type=int,
        metavar="ID",
        help="Scrape run ID to use as the newer snapshot set.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if (args.older_run_id is None) != (args.newer_run_id is None):
        print(
            "ERROR: provide both --older-run-id and --newer-run-id, or neither.",
            file=sys.stderr,
        )
        return 1

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        if args.older_run_id is None:
            try:
                older_run_id, newer_run_id = find_latest_two_comparable_runs(session)
            except InsufficientDataError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
        else:
            older_run_id = args.older_run_id
            newer_run_id = args.newer_run_id

        try:
            report = compare_scrape_runs(
                session,
                older_run_id=older_run_id,
                newer_run_id=newer_run_id,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: comparison failed: {exc}", file=sys.stderr)
            return 1

    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
