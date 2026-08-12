#!/usr/bin/env python3
"""Collect one complete source bundle without reading or writing a database."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from illinois_lottery_tracker.catalog import collect_catalog_pages
from illinois_lottery_tracker.config import DEFAULT_RAW_DATA_DIR, Settings
from illinois_lottery_tracker.pipeline import validate_unpaid_prizes_html
from illinois_lottery_tracker.raw_collector import (
    UNPAID_PRIZES_URL,
    UNPAID_PRIZES_WAIT_SELECTOR,
    PersistentChromeOptions,
    collect_raw_snapshot,
)
from illinois_lottery_tracker.source_bundle import write_source_bundle
from illinois_lottery_tracker.source_quality import CHICAGO_TIME_ZONE


@contextmanager
def collector_lock(raw_root: Path):
    raw_root.mkdir(mode=0o750, parents=True, exist_ok=True)
    lock_path = raw_root / ".collector.lock"
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome-profile-dir", required=True, type=Path)
    parser.add_argument("--chrome-executable", default="/usr/bin/google-chrome")
    parser.add_argument("--chrome-force-x11", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--browser-first", action="store_true")
    parser.add_argument("--skip-if-today-collected", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings(
        database_url=None,
        raw_data_dir=os.environ.get("RAW_DATA_DIR") or DEFAULT_RAW_DATA_DIR,
        app_env="collector",
    )
    raw_root = Path(settings.raw_data_dir).expanduser().resolve()
    with collector_lock(raw_root) as acquired:
        if not acquired:
            print("SKIP: collector_already_running")
            return 0
        if args.skip_if_today_collected:
            from illinois_lottery_tracker.source_bundle import (
                load_source_bundle,
                valid_bundle_manifests,
            )

            today = datetime.now(CHICAGO_TIME_ZONE).date()
            for manifest in reversed(valid_bundle_manifests(raw_root)):
                bundle = load_source_bundle(raw_root, manifest)
                if bundle.unpaid_prizes.captured_at.astimezone(CHICAGO_TIME_ZONE).date() == today:
                    print(f"SKIP: source_date_already_collected bundle_manifest={manifest}")
                    return 0
        chrome = PersistentChromeOptions(
            profile_dir=args.chrome_profile_dir,
            executable_path=args.chrome_executable,
            headless=args.headless,
            force_x11=args.chrome_force_x11,
        )
        try:
            unpaid = collect_raw_snapshot(
                url=UNPAID_PRIZES_URL,
                settings=settings,
                wait_selector=UNPAID_PRIZES_WAIT_SELECTOR,
                chrome_options=chrome,
                requests_first=not args.browser_first,
            )
            validate_unpaid_prizes_html(Path(unpaid.file_path).read_bytes())
            pages = collect_catalog_pages(settings=settings, chrome_options=chrome)
            manifest = write_source_bundle(
                raw_root, unpaid_prizes=unpaid, catalog_pages=pages
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: source collection failed: {exc}", file=sys.stderr)
            return 1
    print(f"bundle_manifest={manifest}")
    print(f"unpaid_sha256={unpaid.sha256}")
    print(f"catalog_pages={len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
