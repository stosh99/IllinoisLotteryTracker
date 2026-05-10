"""Import a saved unpaid-prizes HTML snapshot into the database.

This command does not fetch the network. It parses a local HTML file with the
existing unpaid-prizes parser, then inserts game/prize snapshots for one scrape
run.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.importer import import_unpaid_prizes_parse_result
from illinois_lottery_tracker.models import ScrapeRun
from illinois_lottery_tracker.parser import parse_html
from illinois_lottery_tracker.raw_collector import UNPAID_PRIZES_URL


def _get_or_create_scrape_run(
    session: Session, *, scrape_run_id: int | None, raw_file_path: Path
) -> ScrapeRun:
    if scrape_run_id is not None:
        run = session.get(ScrapeRun, scrape_run_id)
        if run is None:
            raise RuntimeError(f"ScrapeRun not found: id={scrape_run_id}")
        return run

    now = datetime.now(UTC)
    run = ScrapeRun(
        started_at=now,
        finished_at=now,
        status="success",
        source_url=UNPAID_PRIZES_URL,
        raw_file_path=str(raw_file_path),
    )
    session.add(run)
    session.flush()
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a saved Illinois Lottery unpaid-prizes HTML snapshot."
    )
    parser.add_argument("file", help="Path to a saved unpaid-prizes HTML file.")
    parser.add_argument(
        "--scrape-run-id",
        type=int,
        help="Attach imported snapshots to an existing ScrapeRun id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and stage the import, then roll back instead of committing.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    target = Path(args.file)
    if not target.is_file():
        print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 1

    parse_result = parse_html(target)
    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            run = _get_or_create_scrape_run(
                session, scrape_run_id=args.scrape_run_id, raw_file_path=target
            )
            result = import_unpaid_prizes_parse_result(
                session, parse_result, scrape_run=run
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: import failed: {exc}", file=sys.stderr)
            return 1

    mode = "DRY RUN - rolled back" if args.dry_run else "committed"
    print(f"Parsed file: {target}")
    print(f"ScrapeRun id: {run.id}")
    print(f"Mode: {mode}")
    print(f"Games seen: {result.games_seen}")
    print(f"Games upserted: {result.games_upserted}")
    print(f"Games skipped: {result.games_skipped}")
    print(f"Snapshots inserted: {result.snapshots_inserted}")
    print(f"Snapshots skipped existing: {result.snapshots_skipped_existing}")
    print(f"Prize tiers inserted: {result.prize_tiers_inserted}")
    print(f"Parser warnings: {len(result.parser_warnings)}")
    print(f"Import issues: {len(result.issues)}")

    for warning in result.parser_warnings[:5]:
        game_part = f" game={warning.game_name!r}" if warning.game_name else ""
        print(f"  parser warning row={warning.row_index}{game_part}: {warning.message}")
    for issue in result.issues[:5]:
        game_part = f" game={issue.game_name!r}" if issue.game_name else ""
        number_part = f" game_number={issue.game_number!r}" if issue.game_number else ""
        print(f"  import issue:{number_part}{game_part}: {issue.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
