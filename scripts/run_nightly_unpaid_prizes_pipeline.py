"""Nightly pipeline runner for the unpaid-prizes workflow.

Steps (unless --raw-file is supplied):
  1. Optionally skip when today's successful DB snapshot already exists.
  2. Fetch a fresh unpaid-prizes raw HTML file via collect_raw_snapshot.
  3. Validate the saved HTML (Cloudflare / wrong-page detection).
  4. Parse the HTML into structured prize data.
  5. Import a new game/prize-tier snapshot into the database.
  6. Compute estimated-ticket and EV metrics for affected snapshots.
  7. Print a run summary and exit 0 on success, nonzero on any failure.

To schedule nightly (after validating this runner manually):
  systemd:  ExecStart=/path/to/.venv/bin/python \
              /path/to/scripts/run_nightly_unpaid_prizes_pipeline.py \
              --skip-if-today-imported
  timer:    schedule 03:00, 04:00, 05:00, and 06:00 local time. Later runs
            exit without fetching once today's successful DB snapshot exists.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.metadata_backfill import (
    backfill_missing_game_metadata,
    render_metadata_backfill_result,
    stderr_progress,
)
from illinois_lottery_tracker.metrics import compute_snapshot_metrics
from illinois_lottery_tracker.pipeline import (
    LOCAL_TIME_ZONE,
    DuplicateImportError,
    ValidationError,
    find_successful_snapshot_run_for_source_date,
    run_from_file,
)
from illinois_lottery_tracker.raw_collector import UNPAID_PRIZES_URL, collect_raw_snapshot


def _run_metadata_backfill(session: Session, *, max_detail_pages: int | None):
    metadata_result = backfill_missing_game_metadata(
        session,
        max_detail_pages=max_detail_pages,
        progress=stderr_progress,
    )
    metadata_metrics_result = (
        compute_snapshot_metrics(session) if metadata_result.changed_games else None
    )
    return metadata_result, metadata_metrics_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the nightly unpaid-prizes data pipeline."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, import, and compute metrics, then roll back instead of committing.",
    )
    parser.add_argument(
        "--raw-file",
        metavar="PATH",
        help="Skip network fetch; use this saved HTML file instead.",
    )
    parser.add_argument(
        "--min-games",
        type=int,
        default=20,
        metavar="N",
        help="Minimum parsed game count before aborting (default: 20).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Import even if the same file content was already imported.",
    )
    parser.add_argument(
        "--skip-if-today-imported",
        action="store_true",
        help=(
            "Before fetching live source data, exit 0 if today's source date "
            "already has a successful imported snapshot set."
        ),
    )
    parser.add_argument(
        "--backfill-missing-metadata",
        action="store_true",
        help=(
            "After importing the unpaid-prizes snapshot, fetch current instant-ticket "
            "detail pages and fill missing game metadata such as launch_date and odds."
        ),
    )
    parser.add_argument(
        "--metadata-max-detail-pages",
        type=int,
        metavar="N",
        help="Maximum instant-ticket detail pages to fetch during metadata backfill.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    fetch_method: str | None = None

    if args.raw_file:
        raw_path = Path(args.raw_file)
        if not raw_path.is_file():
            print(f"ERROR: file not found: {raw_path}", file=sys.stderr)
            return 1
    else:
        if args.skip_if_today_imported:
            today = datetime.now(LOCAL_TIME_ZONE).date()
            engine = get_engine()
            with Session(engine, expire_on_commit=False, future=True) as session:
                existing_run_id = find_successful_snapshot_run_for_source_date(
                    session,
                    source_date=today,
                    min_games=args.min_games,
                )
            if existing_run_id is not None:
                print(
                    f"SKIP: successful imported snapshot already exists for "
                    f"{today.isoformat()} as scrape_run_id={existing_run_id}."
                )
                if args.backfill_missing_metadata:
                    with Session(engine, expire_on_commit=False, future=True) as session:
                        try:
                            metadata_result, metadata_metrics_result = _run_metadata_backfill(
                                session,
                                max_detail_pages=args.metadata_max_detail_pages,
                            )
                            if args.dry_run:
                                session.rollback()
                            else:
                                session.commit()
                        except Exception as exc:  # noqa: BLE001
                            session.rollback()
                            print(
                                f"WARNING: metadata backfill failed: {exc}",
                                file=sys.stderr,
                            )
                        else:
                            print()
                            print(render_metadata_backfill_result(metadata_result), end="")
                            if metadata_metrics_result is not None:
                                print()
                                print("Metadata metrics recompute:")
                                print(
                                    f"  Games updated:                "
                                    f"{metadata_metrics_result.games_updated}"
                                )
                                print(
                                    f"  Snapshots computed:           "
                                    f"{metadata_metrics_result.snapshots_computed}"
                                )
                                print(
                                    f"  Skipped no odds:              "
                                    f"{metadata_metrics_result.snapshots_skipped_no_odds}"
                                )
                return 0

        print(f"Fetching {UNPAID_PRIZES_URL} ...", flush=True)
        try:
            collection = collect_raw_snapshot(url=UNPAID_PRIZES_URL)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: fetch failed: {exc}", file=sys.stderr)
            return 1
        raw_path = Path(collection.file_path)
        fetch_method = collection.fetch_method
        print(
            f"  saved {raw_path} "
            f"({collection.bytes_written:,} bytes, method={fetch_method})"
        )

    engine = get_engine()
    metadata_result = None
    metadata_warning: str | None = None
    metadata_metrics_result = None
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = run_from_file(
                session,
                raw_path,
                min_games=args.min_games,
                fetch_method=fetch_method,
                force=args.force,
            )
            if args.backfill_missing_metadata:
                try:
                    with session.begin_nested():
                        metadata_result, metadata_metrics_result = _run_metadata_backfill(
                            session,
                            max_detail_pages=args.metadata_max_detail_pages,
                        )
                except Exception as exc:  # noqa: BLE001
                    metadata_warning = f"metadata backfill failed: {exc}"
        except DuplicateImportError as exc:
            print(f"SKIP: {exc}", file=sys.stderr)
            return 0
        except ValidationError as exc:
            print(f"ERROR: validation failed: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"ERROR: pipeline failed: {exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            session.rollback()
            mode = "DRY RUN - rolled back"
        else:
            session.commit()
            mode = "committed"

    print()
    print(f"Mode:                            {mode}")
    print(f"Raw file:                        {result.raw_file_path}")
    print(f"Raw file size:                   {result.raw_file_bytes:,} bytes")
    if result.fetch_method:
        print(f"Fetch method:                    {result.fetch_method}")
    print()
    print(f"Parsed games:                    {result.parsed_game_count}")
    print(f"Parser warnings:                 {result.parser_warning_count}")
    print()
    print(f"Games upserted:                  {result.games_upserted}")
    print(f"Snapshots inserted:              {result.snapshots_inserted}")
    print(f"Snapshots skipped (existing):    {result.snapshots_skipped_existing}")
    print(f"Prize tiers inserted:            {result.prize_tiers_inserted}")
    print()
    print(f"Metrics games updated:           {result.metrics_games_updated}")
    print(f"Metrics snapshots computed:      {result.metrics_snapshots_computed}")
    print(f"Metrics skipped (no odds):       {result.metrics_skipped_no_odds}")
    print()
    print(f"Total games:                     {result.total_games}")
    print(f"Total game_snapshots:            {result.total_snapshots}")
    print(f"Total prize_tier_snapshots:      {result.total_prize_tiers}")

    if metadata_result is not None:
        print()
        print(render_metadata_backfill_result(metadata_result), end="")
    if metadata_metrics_result is not None:
        print()
        print("Metadata metrics recompute:")
        print(f"  Games updated:                {metadata_metrics_result.games_updated}")
        print(
            f"  Snapshots computed:           "
            f"{metadata_metrics_result.snapshots_computed}"
        )
        print(
            f"  Skipped no odds:              "
            f"{metadata_metrics_result.snapshots_skipped_no_odds}"
        )
    if metadata_warning is not None:
        print(f"\nWARNING: {metadata_warning}", file=sys.stderr)

    if result.import_issues:
        print(f"\nImport issues ({len(result.import_issues)}):")
        for issue in result.import_issues[:10]:
            print(f"  {issue}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
