"""Parse a saved individual instant-ticket detail HTML file and print metadata.

Does not fetch network. Does not write to the database.

Usage:
    python scripts/parse_instant_ticket_detail.py path/to/loteria-2026.html
    python scripts/parse_instant_ticket_detail.py path/to/loteria-2026.html --source-url https://...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a saved instant-ticket detail HTML file.")
    parser.add_argument("file", help="Path to a saved detail page HTML file.")
    parser.add_argument(
        "--source-url", metavar="URL",
        help="Original source URL (for slug extraction).",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    from illinois_lottery_tracker.instant_ticket_detail_parser import (
        parse_instant_ticket_detail_html,
    )

    result = parse_instant_ticket_detail_html(path, source_url=args.source_url)

    print(f"Parsed file:               {path}")
    print(f"Name:                      {result.game_name or '(not found)'}")
    print(f"Slug:                      {result.detail_slug or '(not found)'}")
    print(f"Game Number:               {result.game_number or '(not found)'}")
    price = result.ticket_price if result.ticket_price is not None else "(not found)"
    odds = result.overall_odds if result.overall_odds is not None else "(not found)"
    print(f"Price Point:               {price}")
    print(f"Overall Odds:              {odds}")
    print(f"Overall Odds (text):       {result.overall_odds_text or '(not found)'}")
    print(f"Launch Date:               {result.launch_date or '(not found)'}")
    print(f"Category:                  {result.category or '(not found)'}")
    print(f"Play Style:                {result.play_style or '(not found)'}")
    print(f"Top Prize:                 {result.top_prize_text or '(not found)'}")
    print(f"Image URL:                 {result.image_url or '(not found)'}")
    print(f"Consolidated Odds Present: {'yes' if result.consolidated_odds_present else 'no'}")
    print(f"Warnings:                  {len(result.warnings)}")
    for w in result.warnings:
        print(f"  ! {w}")

    if result.raw_fields:
        print("\nRaw fields from details block:")
        for k, v in result.raw_fields.items():
            print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
