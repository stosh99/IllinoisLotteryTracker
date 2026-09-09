#!/usr/bin/env python3
"""Collect one complete source bundle without reading or writing a database."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illinois_lottery_tracker.catalog import CatalogPageCapture, collect_catalog_pages
from illinois_lottery_tracker.config import DEFAULT_RAW_DATA_DIR, Settings
from illinois_lottery_tracker.instant_ticket_detail_parser import (
    parse_instant_ticket_detail_html,
)
from illinois_lottery_tracker.pipeline import validate_unpaid_prizes_html
from illinois_lottery_tracker.raw_collector import (
    UNPAID_PRIZES_URL,
    UNPAID_PRIZES_WAIT_SELECTOR,
    BatchPageResult,
    PersistentChromeOptions,
    RawCollectionResult,
    collect_pages_batch,
    collect_raw_snapshot,
)
from illinois_lottery_tracker.source_bundle import (
    SourceBundle,
    bundle_file_collection,
    bundle_has_complete_detail_coverage,
    load_source_bundle,
    valid_bundle_manifests,
    write_source_bundle,
)
from illinois_lottery_tracker.source_quality import CHICAGO_TIME_ZONE

DETAIL_WAIT_SELECTOR = "div.itg-details-block"
DETAIL_REFRESH_INTERVAL = timedelta(days=7)


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


def _catalog_detail_urls(pages: list[CatalogPageCapture]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for page in pages:
        for ticket in page.discovery.tickets:
            normalized = ticket.detail_url.rstrip("/")
            if normalized not in seen:
                seen.add(normalized)
                urls.append(ticket.detail_url)
    return urls


def _detail_filename_prefix(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    return f"instant-ticket-detail-{slug}"


def _batch_collection(result: BatchPageResult) -> RawCollectionResult:
    if not result.success:
        raise ValueError("cannot convert a failed detail-page collection")
    assert result.file_path is not None
    assert result.sha256 is not None
    assert result.captured_at is not None
    assert result.fetch_method is not None
    return RawCollectionResult(
        source_url=result.url,
        file_path=result.file_path,
        sha256=result.sha256,
        captured_at=result.captured_at,
        content_type=result.content_type,
        bytes_written=result.bytes_written,
        fetch_method=result.fetch_method,
    )


def _detail_validation_error(collection: RawCollectionResult) -> str | None:
    detail = parse_instant_ticket_detail_html(
        Path(collection.file_path), source_url=collection.source_url
    )
    missing = []
    for label, value in (
        ("game_name", detail.game_name),
        ("game_number", detail.game_number),
        ("ticket_price", detail.ticket_price),
    ):
        if value is None:
            missing.append(label)
    if missing:
        return "missing required metadata fields: " + ", ".join(missing)
    return None


def collect_bundle_detail_pages(
    raw_root: Path,
    catalog_pages: list[CatalogPageCapture],
    *,
    settings: Settings,
    chrome: PersistentChromeOptions,
    previous_bundle: SourceBundle | None,
    observed_at: datetime | None = None,
    collect_pages_batch_fn=collect_pages_batch,
) -> tuple[list[RawCollectionResult], int, tuple[str, ...]]:
    """Collect new/stale detail pages and carry fresh verified captures forward."""
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    previous = (
        {
            item.source_url.rstrip("/"): item
            for item in previous_bundle.detail_pages
        }
        if previous_bundle is not None
        else {}
    )
    current_urls = _catalog_detail_urls(catalog_pages)
    refresh_urls = [
        url
        for url in current_urls
        if (
            url.rstrip("/") not in previous
            or now - previous[url.rstrip("/")].captured_at >= DETAIL_REFRESH_INTERVAL
        )
    ]
    pairs = [(url, _detail_filename_prefix(url)) for url in refresh_urls]
    results = (
        collect_pages_batch_fn(
            pairs,
            settings=settings,
            wait_selector=DETAIL_WAIT_SELECTOR,
            chrome_options=chrome,
        )
        if pairs
        else []
    )
    results_by_url = {result.url.rstrip("/"): result for result in results}
    refreshed: dict[str, RawCollectionResult] = {}
    failures: list[str] = []
    for url in refresh_urls:
        normalized = url.rstrip("/")
        result = results_by_url.get(normalized)
        if result is None or not result.success:
            error = result.error if result is not None else "collector returned no result"
            failures.append(f"{url}: {error}")
            continue
        collection = _batch_collection(result)
        try:
            validation_error = _detail_validation_error(collection)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url}: detail-page validation failed: {exc}")
            continue
        if validation_error is not None:
            failures.append(f"{url}: {validation_error}")
            continue
        refreshed[normalized] = collection

    selected: list[RawCollectionResult] = []
    for url in current_urls:
        normalized = url.rstrip("/")
        if normalized in refreshed:
            selected.append(refreshed[normalized])
        elif normalized in previous:
            selected.append(bundle_file_collection(raw_root, previous[normalized]))
    return selected, len(refreshed), tuple(failures)


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
        manifests = valid_bundle_manifests(raw_root)
        previous_bundle = load_source_bundle(raw_root, manifests[-1]) if manifests else None
        if args.skip_if_today_collected:
            today = datetime.now(CHICAGO_TIME_ZONE).date()
            for manifest in reversed(manifests):
                bundle = load_source_bundle(raw_root, manifest)
                if (
                    bundle.unpaid_prizes.captured_at.astimezone(CHICAGO_TIME_ZONE).date()
                    == today
                    and bundle_has_complete_detail_coverage(raw_root, bundle)
                ):
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
            details, refreshed_details, detail_failures = collect_bundle_detail_pages(
                raw_root,
                pages,
                settings=settings,
                chrome=chrome,
                previous_bundle=previous_bundle,
            )
            expected_detail_pages = len(_catalog_detail_urls(pages))
            if len(details) != expected_detail_pages:
                first_failure = detail_failures[0] if detail_failures else "unknown"
                raise RuntimeError(
                    "verified detail-page coverage is incomplete: "
                    f"expected={expected_detail_pages} actual={len(details)}; "
                    f"first_failure={first_failure}"
                )
            manifest = write_source_bundle(
                raw_root,
                unpaid_prizes=unpaid,
                catalog_pages=pages,
                detail_pages=details,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: source collection failed: {exc}", file=sys.stderr)
            return 1
    print(f"bundle_manifest={manifest}")
    print(f"unpaid_sha256={unpaid.sha256}")
    print(f"catalog_pages={len(pages)}")
    print(f"detail_pages={len(details)} refreshed={refreshed_details}")
    for failure in detail_failures:
        print(f"WARNING: detail-page collection failed: {failure}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
