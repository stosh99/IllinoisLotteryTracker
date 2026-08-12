#!/usr/bin/env python3
"""Idempotently import one verified source bundle into the configured database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.catalog import persist_catalog_run
from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.db import get_engine
from illinois_lottery_tracker.pipeline import (
    DuplicateImportError,
    SourceQuarantinedError,
    find_prior_import,
    orchestration_lock,
    run_analytics_stage,
    run_from_file,
)
from illinois_lottery_tracker.source_bundle import (
    bundle_file_path,
    catalog_captures,
    load_source_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--min-games", type=int, default=40)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    raw_root = Path(settings.raw_data_dir).expanduser().resolve()
    try:
        bundle = load_source_bundle(raw_root, args.bundle)
        engine = get_engine(settings)
        with orchestration_lock(engine) as acquired:
            if not acquired:
                print("SKIP: database_import_already_running")
                return 0
            unpaid_path = bundle_file_path(raw_root, bundle.unpaid_prizes)
            with Session(engine, expire_on_commit=False, future=True) as session:
                try:
                    result = run_from_file(
                        session,
                        unpaid_path,
                        min_games=args.min_games,
                        fetch_method=bundle.unpaid_prizes.fetch_method,
                    )
                    session.commit()
                    source_run_id = result.scrape_run_id
                    source_created = True
                except DuplicateImportError as exc:
                    session.rollback()
                    source_run_id = find_prior_import(
                        session, bundle.unpaid_prizes.sha256
                    )
                    if source_run_id is None:
                        raise RuntimeError(
                            "duplicate source was reported but its completed run was not found"
                        ) from exc
                    source_created = False
                except SourceQuarantinedError:
                    session.commit()
                    raise

            pages = catalog_captures(raw_root, bundle)
            with Session(engine, expire_on_commit=False, future=True) as session:
                catalog = persist_catalog_run(session, pages)
                session.commit()

            factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
            analytics = run_analytics_stage(factory, source_run_id=source_run_id)
            if analytics.status != "success":
                raise RuntimeError(
                    f"analytics failed for source_run_id={source_run_id}: "
                    f"{analytics.error_message}"
                )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: source-bundle import failed: {exc}", file=sys.stderr)
        return 1

    print(f"bundle_id={bundle.bundle_id}")
    print(f"source_run_id={source_run_id} source_created={str(source_created).lower()}")
    print(
        f"catalog_run_id={catalog.scrape_run_id} "
        f"catalog_created={str(catalog.created).lower()}"
    )
    print(f"analytics_run_id={analytics.analytics_run_id} analytics_status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
