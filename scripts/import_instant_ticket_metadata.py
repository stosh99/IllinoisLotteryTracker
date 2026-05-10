"""Import saved instant-ticket detail metadata into the games table.

This command does not fetch the network and does not write prize snapshots.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.importer import import_instant_ticket_detail_metadata
from illinois_lottery_tracker.instant_ticket_detail_parser import (
    parse_instant_ticket_detail_html,
)

_BASE_DETAIL_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"
_TIMESTAMP_SUFFIX_RE = re.compile(r"-\d{8}T\d{6}Z$")


def _source_url_from_path(path: Path) -> str | None:
    """Derive the canonical detail page URL from the saved filename.

    Saved filename format: instant-ticket-detail-{slug}-{timestamp}.html
    Returns: https://www.illinoislottery.com/games-hub/instant-tickets/{slug}
    """
    slug_part = path.stem.removeprefix("instant-ticket-detail-")
    slug = _TIMESTAMP_SUFFIX_RE.sub("", slug_part)
    return f"{_BASE_DETAIL_URL}/{slug}" if slug else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import saved instant-ticket detail metadata into games."
    )
    parser.add_argument("files", nargs="+", help="Saved instant-ticket detail HTML files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and stage metadata updates, then roll back instead of committing.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    targets = [Path(value) for value in args.files]
    missing = [target for target in targets if not target.is_file()]
    if missing:
        for target in missing:
            print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 1

    details = []
    for target in targets:
        details.append(
            parse_instant_ticket_detail_html(target, source_url=_source_url_from_path(target))
        )

    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = import_instant_ticket_detail_metadata(session, details)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: import failed: {exc}", file=sys.stderr)
            return 1

    mode = "DRY RUN - rolled back" if args.dry_run else "committed"
    print(f"Files parsed: {len(targets)}")
    print(f"Mode: {mode}")
    print(f"Details seen: {result.details_seen}")
    print(f"Games created: {result.games_created}")
    print(f"Games updated: {result.games_updated}")
    print(f"Details skipped: {result.details_skipped}")
    print(f"Parser warnings: {len(result.parser_warnings)}")
    print(f"Import issues: {len(result.issues)}")

    for warning in result.parser_warnings[:5]:
        print(f"  parser warning: {warning}")
    for issue in result.issues[:10]:
        number_part = f" game_number={issue.game_number!r}" if issue.game_number else ""
        game_part = f" game={issue.game_name!r}" if issue.game_name else ""
        print(f"  import issue:{number_part}{game_part}: {issue.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
