"""Deprecated entry point for the superseded legacy snapshot-metrics report.

Does not fetch source data and does not modify database rows.
"""

from __future__ import annotations

import argparse
import sys

from illinois_lottery_tracker.metrics_report import (
    MetricsReportSection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deprecated legacy snapshot-metrics entry point; use report_analytics.py."
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
        choices=[section.value for section in MetricsReportSection],
        default=MetricsReportSection.ALL.value,
        help="Report section to print (default: all).",
    )
    parser.add_argument(
        "--game-number",
        metavar="NUMBER",
        help="Game number for --section game.",
    )
    parser.add_argument(
        "--format",
        choices=["text"],
        default="text",
        help="Output format. Only text is supported in this pass.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.limit < 1:
        print("ERROR: --limit must be at least 1.", file=sys.stderr)
        return 2

    print(
        "DEPRECATED: report_metrics.py reads superseded all-winner-denominator "
        "columns and is disabled. Use report_analytics.py --nightly-status or "
        "query current_strategy_rankings_v with explicit strategy_key names.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
