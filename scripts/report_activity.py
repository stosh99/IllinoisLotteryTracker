"""Read-only report for implied prize activity between stored snapshots.

Does not fetch source data and does not modify database rows.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from illinois_lottery_tracker.activity_report import (
    ActivityReportSection,
    build_activity_report,
    render_text_report,
)
from illinois_lottery_tracker.db import get_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only report of implied prize activity from public "
            "unclaimed-prize snapshot changes."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Rows per ranking section (default: 10).",
    )
    parser.add_argument(
        "--db-url",
        metavar="URL",
        help="Database URL. Defaults to DATABASE_URL from the project configuration.",
    )
    parser.add_argument(
        "--section",
        choices=[section.value for section in ActivityReportSection],
        default=ActivityReportSection.ALL.value,
        help="Report section to print (default: all).",
    )
    parser.add_argument(
        "--game-number",
        metavar="NUMBER",
        help="Game number for --section tiers.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.limit < 1:
        print("ERROR: --limit must be at least 1.", file=sys.stderr)
        return 2

    if args.db_url:
        engine = create_engine(args.db_url, future=True, pool_pre_ping=True)
    else:
        engine = get_engine()

    with Session(engine, expire_on_commit=False, future=True) as session:
        report = build_activity_report(session)

    print(
        render_text_report(
            report,
            limit=args.limit,
            section=ActivityReportSection(args.section),
            game_number=args.game_number,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
