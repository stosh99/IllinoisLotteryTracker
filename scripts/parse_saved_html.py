"""Parse a saved Illinois Lottery rendered-HTML file and print a summary.

Does not write to the database. Does not fetch anything from the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

from illinois_lottery_tracker.parser import parse_html


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "Usage: python scripts/parse_saved_html.py <path-to-html>",
            file=sys.stderr,
        )
        return 2

    target = Path(args[0])
    if not target.is_file():
        print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 1

    result = parse_html(target)
    games = result.games
    total_tiers = sum(len(g.prize_tiers) for g in games)
    distinct_prices = sorted(
        {g.ticket_price for g in games if g.ticket_price is not None}
    )

    print(f"Parsed file: {target}")
    print(f"Games parsed: {len(games)}")
    print(f"Prize tiers parsed: {total_tiers}")
    print(f"Ticket prices found: {distinct_prices}")
    print(f"Warnings: {len(result.warnings)}")

    if games:
        print()
        print(f"First {min(5, len(games))} games:")
        for g in games[:5]:
            number = g.game_number or "?"
            label = g.display_name or g.game_name or "(unnamed)"
            print(f"- {number} {label}: {len(g.prize_tiers)} prize tiers")

    if result.warnings:
        print()
        print(f"First {min(5, len(result.warnings))} warnings:")
        for w in result.warnings[:5]:
            game_part = f" game={w.game_name!r}" if w.game_name else ""
            print(f"- row={w.row_index}{game_part}: {w.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
