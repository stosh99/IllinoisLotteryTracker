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
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.analytics.status import build_nightly_status
from illinois_lottery_tracker.catalog import collect_catalog_pages, persist_catalog_run
from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.lifecycle import current_complete_run_id
from illinois_lottery_tracker.pipeline import (
    LOCAL_TIME_ZONE,
    DuplicateImportError,
    SourceQuarantinedError,
    ValidationError,
    find_successful_snapshot_run_for_source_date,
    orchestration_lock,
    run_analytics_stage,
    run_from_file,
)
from illinois_lottery_tracker.raw_collector import (
    DEFAULT_CHROME_EXECUTABLE,
    UNPAID_PRIZES_URL,
    UNPAID_PRIZES_WAIT_SELECTOR,
    PersistentChromeOptions,
    collect_raw_snapshot,
)


def _persistent_chrome_options(args: argparse.Namespace) -> PersistentChromeOptions | None:
    profile_dir = getattr(args, "chrome_profile_dir", None)
    if profile_dir is None:
        return None
    return PersistentChromeOptions(
        profile_dir=profile_dir,
        executable_path=str(args.chrome_executable),
        headless=args.headless_chrome,
        force_x11=args.chrome_force_x11,
    )


def _main_unlocked(argv: list[str], engine: Engine | None) -> int:
    total_started = time.perf_counter()
    stage_durations = {
        "source_collection": 0.0,
        "source_import": 0.0,
        "catalog_collection_import": 0.0,
        "analytics": 0.0,
    }
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
        "--chrome-profile-dir",
        type=Path,
        metavar="PATH",
        help=(
            "Use installed Chrome with this dedicated persistent collector profile "
            "for browser fallbacks; never use a personal Chrome profile."
        ),
    )
    parser.add_argument(
        "--chrome-executable",
        type=Path,
        default=Path(DEFAULT_CHROME_EXECUTABLE),
        metavar="PATH",
        help=f"Installed Chrome executable (default: {DEFAULT_CHROME_EXECUTABLE}).",
    )
    parser.add_argument(
        "--headless-chrome",
        action="store_true",
        help="Run persistent Chrome without a visible window (headed is the default).",
    )
    parser.add_argument(
        "--chrome-force-x11",
        action="store_true",
        help="Force persistent Chrome onto the X11 display supplied by Xvfb.",
    )
    parser.add_argument(
        "--min-games",
        type=int,
        default=40,
        metavar="N",
        help="Minimum parsed game count before aborting (default: 40).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force collection/processing checks where supported; immutable duplicate "
            "source content is still skipped."
        ),
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
        "--manual-approval-reason",
        help=(
            "Auditable operator reason to override only the 80%%-of-prior count gate; "
            "absolute and structural checks still apply."
        ),
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="collect catalog pages outside a transaction, then commit them separately",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="directory containing backup and restore-verification manifests",
    )
    parser.add_argument(
        "--raw-growth-limit-bytes",
        type=int,
        help="alert when unique raw files captured in 30 days exceed this byte count",
    )
    parser.add_argument(
        "--backfill-missing-metadata",
        action="store_true",
        help=(
            "Deprecated nightly flag; metadata network work must run as a separate "
            "command so it never spans the source transaction."
        ),
    )
    parser.add_argument(
        "--metadata-max-detail-pages",
        type=int,
        metavar="N",
        help="Maximum instant-ticket detail pages to fetch during metadata backfill.",
    )
    args = parser.parse_args(argv)
    assert engine is not None

    if (
        args.headless_chrome or args.chrome_force_x11
    ) and args.chrome_profile_dir is None:
        parser.error(
            "--headless-chrome and --chrome-force-x11 require --chrome-profile-dir"
        )
    chrome_options = _persistent_chrome_options(args)

    fetch_method: str | None = None

    if args.raw_file:
        raw_path = Path(args.raw_file)
        if not raw_path.is_file():
            print(f"ERROR: file not found: {raw_path}", file=sys.stderr)
            return 1
    else:
        if args.skip_if_today_imported and not args.force:
            today = datetime.now(LOCAL_TIME_ZONE).date()
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
                if args.dry_run:
                    return 0
                return _finish_existing_source(
                    engine,
                    args=args,
                    source_run_id=existing_run_id,
                    stage_durations=stage_durations,
                    total_started=total_started,
                )

        collection_started = time.perf_counter()
        print(f"Fetching {UNPAID_PRIZES_URL} ...", flush=True)
        try:
            collection_kwargs = {
                "url": UNPAID_PRIZES_URL,
                "wait_selector": UNPAID_PRIZES_WAIT_SELECTOR,
            }
            if chrome_options is not None:
                collection_kwargs["chrome_options"] = chrome_options
            collection = collect_raw_snapshot(**collection_kwargs)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: fetch failed: {exc}", file=sys.stderr)
            return 1
        stage_durations["source_collection"] = time.perf_counter() - collection_started
        raw_path = Path(collection.file_path)
        fetch_method = collection.fetch_method
        print(
            f"  saved {raw_path} "
            f"({collection.bytes_written:,} bytes, method={fetch_method})"
        )

    metadata_warning: str | None = None
    source_started = time.perf_counter()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            result = run_from_file(
                session,
                raw_path,
                min_games=args.min_games,
                fetch_method=fetch_method,
                force=args.force,
                manual_approval_reason=args.manual_approval_reason,
            )
        except DuplicateImportError as exc:
            session.rollback()
            session.close()
            print(f"SKIP: {exc}", file=sys.stderr)
            if args.dry_run:
                return 0
            with Session(engine, expire_on_commit=False, future=True) as lookup:
                existing_run_id = current_complete_run_id(lookup)
            if existing_run_id is None:
                print("ERROR: duplicate source found but no current complete run", file=sys.stderr)
                return 1
            return _finish_existing_source(
                engine,
                args=args,
                source_run_id=existing_run_id,
                stage_durations=stage_durations,
                total_started=total_started,
            )
        except SourceQuarantinedError as exc:
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
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
    stage_durations["source_import"] = time.perf_counter() - source_started

    catalog_warning = _refresh_catalog_stage(
        engine, args=args, stage_durations=stage_durations
    )
    if catalog_warning:
        print(f"WARNING: {catalog_warning}", file=sys.stderr)
    analytics = None
    if not args.dry_run:
        analytics_started = time.perf_counter()
        analytics = run_analytics_stage(
            sessionmaker(bind=engine, expire_on_commit=False, future=True),
            source_run_id=result.scrape_run_id,
        )
        stage_durations["analytics"] = time.perf_counter() - analytics_started
    if args.backfill_missing_metadata:
        metadata_warning = (
            "nightly metadata network collection is disabled so no database "
            "transaction spans network I/O; run backfill_missing_metadata.py separately"
        )

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

    if metadata_warning is not None:
        print(f"\nWARNING: {metadata_warning}", file=sys.stderr)
    if analytics is not None:
        print()
        print(
            f"Analytics: status={analytics.status} run_id={analytics.analytics_run_id} "
            f"source_run_id={analytics.source_run_id}"
        )
        if analytics.error_message:
            print(f"Analytics error: {analytics.error_message}", file=sys.stderr)

    if result.import_issues:
        print(f"\nImport issues ({len(result.import_issues)}):")
        for issue in result.import_issues[:10]:
            print(f"  {issue}")

    _print_stage_durations(stage_durations, total_started)
    _print_nightly_status(engine, args, stage_durations)

    return 1 if analytics is not None and analytics.status == "failed" else 0


def _print_stage_durations(stage_durations: dict[str, float], total_started: float) -> None:
    stages = " ".join(
        f"{name}={duration:.3f}" for name, duration in stage_durations.items()
    )
    print(f"Stage durations seconds: {stages} total={time.perf_counter() - total_started:.3f}")


def _print_nightly_status(engine: Engine, args, stage_durations: dict[str, float]) -> None:
    try:
        with Session(engine, expire_on_commit=False, future=True) as session:
            document = build_nightly_status(
                session,
                backup_dir=args.backup_dir,
                raw_growth_limit_bytes=args.raw_growth_limit_bytes,
                stage_durations_seconds=stage_durations,
            )
        print(f"Nightly status: {json.dumps(document, sort_keys=True)}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: nightly status reporting failed: {exc}", file=sys.stderr)


def _finish_existing_source(
    engine: Engine,
    *,
    args,
    source_run_id: int,
    stage_durations: dict[str, float],
    total_started: float,
) -> int:
    catalog_warning = _refresh_catalog_stage(
        engine, args=args, stage_durations=stage_durations
    )
    if catalog_warning:
        print(f"WARNING: {catalog_warning}", file=sys.stderr)
    analytics_started = time.perf_counter()
    analytics = run_analytics_stage(
        sessionmaker(bind=engine, expire_on_commit=False, future=True),
        source_run_id=source_run_id,
    )
    stage_durations["analytics"] = time.perf_counter() - analytics_started
    print(
        f"Analytics: status={analytics.status} run_id={analytics.analytics_run_id} "
        f"source_run_id={analytics.source_run_id}"
    )
    _print_stage_durations(stage_durations, total_started)
    _print_nightly_status(engine, args, stage_durations)
    return 1 if analytics.status == "failed" else 0


def _refresh_catalog_stage(
    engine: Engine, *, args, stage_durations: dict[str, float]
) -> str | None:
    if not args.refresh_catalog:
        return None
    started = time.perf_counter()
    try:
        chrome_options = _persistent_chrome_options(args)
        if chrome_options is None:
            pages = collect_catalog_pages()
        else:
            pages = collect_catalog_pages(chrome_options=chrome_options)
        with Session(engine, expire_on_commit=False, future=True) as session:
            result = persist_catalog_run(session, pages)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        print(
            f"Catalog: run_id={result.scrape_run_id} entries={result.unique_entry_count} "
            f"mapped={result.mapped_count} unmapped={result.unmapped_count}"
        )
        return None
    except Exception as exc:  # noqa: BLE001
        return f"catalog refresh failed independently: {exc}"
    finally:
        stage_durations["catalog_collection_import"] = time.perf_counter() - started


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if any(argument in {"-h", "--help"} for argument in arguments):
        return _main_unlocked(arguments, None)
    engine = get_engine()
    with orchestration_lock(engine) as acquired:
        if not acquired:
            print("SKIP: already_running")
            return 0
        return _main_unlocked(arguments, engine)


if __name__ == "__main__":
    raise SystemExit(main())
