#!/usr/bin/env python3
"""Publish a bundle from the latest complete source runs already in the database."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.catalog import CatalogPageCapture
from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.instant_ticket_discovery import (
    parse_instant_ticket_hub_html,
)
from illinois_lottery_tracker.models import RawSourceSnapshot, ScrapeRun
from illinois_lottery_tracker.raw_collector import RawCollectionResult
from illinois_lottery_tracker.source_bundle import sha256_file, write_source_bundle


def _safe_relative(path: Path, old_root: Path) -> Path:
    try:
        return path.expanduser().resolve().relative_to(old_root.expanduser().resolve())
    except ValueError as exc:
        raise ValueError(f"database source path is outside old raw root: {path}") from exc


def _copy_verified(snapshot: RawSourceSnapshot, old_root: Path, new_root: Path) -> Path:
    source = Path(snapshot.file_path).expanduser().resolve()
    relative = _safe_relative(source, old_root)
    target = new_root.expanduser().resolve() / relative
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != source.stat().st_size or sha256_file(target) != snapshot.sha256:
            raise RuntimeError(f"existing canonical capture differs: {target}")
    else:
        shutil.copy2(source, target)
    if sha256_file(source) != snapshot.sha256 or sha256_file(target) != snapshot.sha256:
        raise RuntimeError(f"capture SHA-256 does not match database: {source}")
    return target


def _collection(snapshot: RawSourceSnapshot, path: Path) -> RawCollectionResult:
    return RawCollectionResult(
        source_url=snapshot.source_url,
        file_path=str(path),
        sha256=snapshot.sha256,
        captured_at=snapshot.captured_at,
        content_type=snapshot.content_type,
        bytes_written=path.stat().st_size,
        fetch_method="requests",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-raw-root", required=True, type=Path)
    parser.add_argument("--new-raw-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with Session(get_engine(), future=True) as session:
            unpaid_run = session.scalar(
                select(ScrapeRun)
                .where(
                    ScrapeRun.workflow == "unpaid_prizes",
                    ScrapeRun.status == "success",
                    ScrapeRun.is_complete.is_(True),
                )
                .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
                .limit(1)
            )
            catalog_run = session.scalar(
                select(ScrapeRun)
                .where(
                    ScrapeRun.workflow == "instant_ticket_catalog",
                    ScrapeRun.status == "success",
                    ScrapeRun.is_complete.is_(True),
                )
                .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
                .limit(1)
            )
            if unpaid_run is None or catalog_run is None:
                raise RuntimeError("latest complete unpaid-prizes or catalog run is missing")
            unpaid_snapshots = session.scalars(
                select(RawSourceSnapshot)
                .where(RawSourceSnapshot.scrape_run_id == unpaid_run.id)
                .order_by(RawSourceSnapshot.id)
            ).all()
            catalog_snapshots = session.scalars(
                select(RawSourceSnapshot)
                .where(RawSourceSnapshot.scrape_run_id == catalog_run.id)
                .order_by(RawSourceSnapshot.id)
            ).all()
            if len(unpaid_snapshots) != 1 or not catalog_snapshots:
                raise RuntimeError("source runs do not contain the expected raw snapshots")

            unpaid_snapshot = unpaid_snapshots[0]
            unpaid_path = _copy_verified(
                unpaid_snapshot, args.old_raw_root, args.new_raw_root
            )
            pages: list[CatalogPageCapture] = []
            for number, snapshot in enumerate(catalog_snapshots, start=1):
                path = _copy_verified(snapshot, args.old_raw_root, args.new_raw_root)
                pages.append(
                    CatalogPageCapture(
                        page_number=number,
                        collection=_collection(snapshot, path),
                        discovery=parse_instant_ticket_hub_html(
                            path, source_url=snapshot.source_url
                        ),
                    )
                )
            manifest = write_source_bundle(
                args.new_raw_root,
                unpaid_prizes=_collection(unpaid_snapshot, unpaid_path),
                catalog_pages=pages,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: saved bundle export failed: {exc}", file=sys.stderr)
        return 1
    print(f"bundle_manifest={manifest}")
    print(f"unpaid_scrape_run_id={unpaid_run.id}")
    print(f"catalog_scrape_run_id={catalog_run.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
