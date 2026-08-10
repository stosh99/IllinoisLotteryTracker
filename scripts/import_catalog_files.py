#!/usr/bin/env python3
"""Import one complete ordered catalog crawl from preserved raw HTML files."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from illinois_lottery_tracker.catalog import (
    HUB_URL,
    CatalogPageCapture,
    persist_catalog_run,
)
from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.instant_ticket_discovery import (
    parse_instant_ticket_hub_html,
)
from illinois_lottery_tracker.raw_collector import RawCollectionResult

_FILENAME_TIMESTAMP = re.compile(r"(\d{8}T\d{6}Z)")


def _captured_at(path: Path) -> datetime:
    match = _FILENAME_TIMESTAMP.search(path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog_pages_from_files(paths: list[Path]) -> list[CatalogPageCapture]:
    pages: list[CatalogPageCapture] = []
    source_url = HUB_URL
    for page_number, supplied_path in enumerate(paths, start=1):
        path = supplied_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"catalog page not found: {path}")
        discovery = parse_instant_ticket_hub_html(path, source_url=source_url)
        pages.append(
            CatalogPageCapture(
                page_number=page_number,
                collection=RawCollectionResult(
                    source_url=source_url,
                    file_path=str(path),
                    sha256=_sha256(path),
                    captured_at=_captured_at(path),
                    content_type="text/html",
                    bytes_written=path.stat().st_size,
                    fetch_method="requests",
                ),
                discovery=discovery,
            )
        )
        if discovery.pagination_urls:
            source_url = discovery.pagination_urls[0]
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pages",
        nargs="+",
        type=Path,
        help="ordered page-1, page-2, ... raw catalog HTML files",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pages = catalog_pages_from_files(args.pages)
        with Session(get_engine(), expire_on_commit=False, future=True) as session:
            result = persist_catalog_run(session, pages)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    except Exception as exc:  # noqa: BLE001 - command boundary
        print(f"ERROR: catalog file import failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"catalog_run_id={result.scrape_run_id} pages={result.page_count} "
        f"entries={result.unique_entry_count} mapped={result.mapped_count} "
        f"unmapped={result.unmapped_count} ambiguous={result.ambiguous_count} "
        f"created={str(result.created).lower()} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
