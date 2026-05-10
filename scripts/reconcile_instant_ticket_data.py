"""Read-only reconciliation of unpaid-prizes snapshot coverage against
instant-ticket detail metadata.

This script never modifies the database. It compares:
  - Games with at least one GameSnapshot (= appeared in unpaid-prizes data)
  - Games with source_url set       (= appeared in instant-ticket detail import)

Usage:
    python scripts/reconcile_instant_ticket_data.py
    python scripts/reconcile_instant_ticket_data.py --details-dir data/raw/2026-05-08
    python scripts/reconcile_instant_ticket_data.py --details-dir data/raw/2026-05-08 --json

With --details-dir: also parses saved detail HTML files to enable price and
name mismatch checks that cannot be detected from stored DB state alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path


def _parse_detail_files(
    details_dir: Path,
) -> list:
    from illinois_lottery_tracker.instant_ticket_detail_parser import (
        parse_instant_ticket_detail_html,
    )

    files = sorted(details_dir.glob("instant-ticket-detail-*.html"))
    if not files:
        print(
            f"WARNING: no instant-ticket-detail-*.html files found in {details_dir}",
            file=sys.stderr,
        )
        return []

    details = []
    for f in files:
        try:
            details.append(parse_instant_ticket_detail_html(f))
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: failed to parse {f.name}: {exc}", file=sys.stderr)
    print(
        f"Parsed {len(details)} detail files from {details_dir}",
        file=sys.stderr,
    )
    return details


def _fmt_price(price: Decimal | None) -> str:
    if price is None:
        return "None"
    return f"${price}"


def _print_report(report) -> None:
    print()
    print("=" * 64)
    print("Instant Ticket Reconciliation Report")
    print("=" * 64)
    print(f"  Total games in DB:              {report.total_games}")
    print(f"  Games with unpaid snapshot:     {report.games_with_unpaid_snapshot}")
    print(f"  Games with detail metadata:     {report.games_with_detail_metadata}")
    print(f"  Matched (both sources):         {report.games_matched}")
    print(f"  Unpaid-prizes only:             {report.unpaid_only_count}")
    print(f"  Detail-metadata only:           {report.detail_only_count}")
    print(f"  Price mismatches:               {report.price_mismatch_count}")
    print(f"  Name/display-name mismatches:   {report.name_mismatch_count}")
    print(f"  Missing overall_odds:           {report.missing_overall_odds_count}")
    print(f"  Missing launch_date:            {report.missing_launch_date_count}")
    print(f"  Duplicate game_numbers (input): {report.duplicate_game_numbers_in_details}")
    print()

    print(f"Hub note: {report.hub_note}")
    print()

    if report.schema_notes:
        print("Schema/coverage notes:")
        for note in report.schema_notes:
            print(f"  * {note}")
        print()

    if report.unpaid_only:
        print(f"Unpaid-prizes only ({len(report.unpaid_only)}):")
        for row in report.unpaid_only:
            print(f"  [{row.game_number}] {row.game_name}")
        print()

    if report.detail_only:
        print(f"Detail-metadata only ({len(report.detail_only)}):")
        for row in report.detail_only:
            print(f"  [{row.game_number}] {row.game_name}")
        print()

    if report.price_mismatches:
        print(f"Price mismatches ({len(report.price_mismatches)}):")
        for row in report.price_mismatches:
            print(
                f"  [{row.game_number}] {row.game_name}: "
                f"db={_fmt_price(row.db_price)} detail={_fmt_price(row.detail_price)}"
            )
        print()

    if report.name_mismatches:
        print(f"Name/display-name mismatches ({len(report.name_mismatches)}):")
        for row in report.name_mismatches:
            print(
                f"  [{row.game_number}] db={row.db_name!r} detail={row.detail_name!r}"
            )
        print()

    if report.missing_odds:
        print(f"Missing overall_odds ({len(report.missing_odds)}):")
        for row in report.missing_odds:
            print(f"  [{row.game_number}] {row.game_name}")
        print()

    if report.missing_dates:
        print(f"Missing launch_date ({len(report.missing_dates)}):")
        for row in report.missing_dates:
            print(f"  [{row.game_number}] {row.game_name}")
        print()

    if report.duplicate_game_numbers:
        print(f"Duplicate game_numbers in detail input ({len(report.duplicate_game_numbers)}):")
        for gnum in report.duplicate_game_numbers:
            print(f"  {gnum}")
        print()


def _report_to_dict(report) -> dict:
    def _row(r) -> dict:
        return {
            "game_number": r.game_number,
            "game_name": r.game_name,
            "has_unpaid_snapshot": r.has_unpaid_snapshot,
            "has_detail_metadata": r.has_detail_metadata,
            "ticket_price": str(r.ticket_price) if r.ticket_price else None,
            "overall_odds_one_in": str(r.overall_odds_one_in) if r.overall_odds_one_in else None,
            "launch_date": str(r.launch_date) if r.launch_date else None,
        }

    return {
        "summary": {
            "total_games": report.total_games,
            "games_with_unpaid_snapshot": report.games_with_unpaid_snapshot,
            "games_with_detail_metadata": report.games_with_detail_metadata,
            "games_matched": report.games_matched,
            "unpaid_only_count": report.unpaid_only_count,
            "detail_only_count": report.detail_only_count,
            "price_mismatch_count": report.price_mismatch_count,
            "name_mismatch_count": report.name_mismatch_count,
            "missing_overall_odds_count": report.missing_overall_odds_count,
            "missing_launch_date_count": report.missing_launch_date_count,
            "duplicate_game_numbers_in_details": report.duplicate_game_numbers_in_details,
        },
        "hub_note": report.hub_note,
        "schema_notes": report.schema_notes,
        "unpaid_only": [_row(r) for r in report.unpaid_only],
        "detail_only": [_row(r) for r in report.detail_only],
        "price_mismatches": [
            {
                "game_number": r.game_number,
                "game_name": r.game_name,
                "db_price": str(r.db_price) if r.db_price else None,
                "detail_price": str(r.detail_price) if r.detail_price else None,
            }
            for r in report.price_mismatches
        ],
        "name_mismatches": [
            {
                "game_number": r.game_number,
                "db_name": r.db_name,
                "detail_name": r.detail_name,
            }
            for r in report.name_mismatches
        ],
        "missing_odds": [_row(r) for r in report.missing_odds],
        "missing_dates": [_row(r) for r in report.missing_dates],
        "duplicate_game_numbers": report.duplicate_game_numbers,
        "all_rows": [_row(r) for r in report.all_rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only reconciliation of unpaid-prizes vs. detail metadata.",
    )
    parser.add_argument(
        "--details-dir",
        metavar="DIR",
        help=(
            "Directory containing instant-ticket-detail-*.html files. "
            "Enables price and name mismatch checks."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also print the full report as JSON to stdout.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    detail_inputs = None
    if args.details_dir:
        details_dir = Path(args.details_dir)
        if not details_dir.is_dir():
            print(f"ERROR: not a directory: {details_dir}", file=sys.stderr)
            return 1
        detail_inputs = _parse_detail_files(details_dir)

    from sqlalchemy.orm import Session

    from illinois_lottery_tracker.db import get_engine
    from illinois_lottery_tracker.reconciliation import reconcile

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        report = reconcile(session=session, detail_inputs=detail_inputs)
        # Never commit — this is read-only.

    _print_report(report)

    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2))

    issues = report.unpaid_only_count + report.detail_only_count + report.price_mismatch_count
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
