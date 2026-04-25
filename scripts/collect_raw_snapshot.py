"""Collect a raw snapshot of the Illinois Lottery unpaid-prizes page.

Records a ScrapeRun and a RawSourceSnapshot row. The raw HTML on disk is the
source of truth — if the database write fails after a successful fetch we
print the file path so it can be recovered.
"""

from __future__ import annotations

import sys
import traceback
from datetime import UTC, datetime

from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.db import get_session
from illinois_lottery_tracker.models import RawSourceSnapshot, ScrapeRun
from illinois_lottery_tracker.raw_collector import (
    UNPAID_PRIZES_URL,
    RawCollectionResult,
    collect_raw_snapshot,
)


def _record_failed_run(source_url: str, started_at: datetime, error: str) -> None:
    try:
        with get_session() as session:
            run = ScrapeRun(
                started_at=started_at,
                finished_at=datetime.now(UTC),
                status="failed",
                source_url=source_url,
                error_message=error,
            )
            session.add(run)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: failed to record failure row: {exc}", file=sys.stderr)


def _record_success(result: RawCollectionResult, started_at: datetime) -> int:
    with get_session() as session:
        run = ScrapeRun(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status="success",
            source_url=result.source_url,
            raw_file_path=result.file_path,
        )
        session.add(run)
        session.flush()

        snapshot = RawSourceSnapshot(
            scrape_run_id=run.id,
            source_url=result.source_url,
            content_type=result.content_type,
            file_path=result.file_path,
            sha256=result.sha256,
            captured_at=result.captured_at,
        )
        session.add(snapshot)
        session.flush()
        return run.id


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print(
            "ERROR: DATABASE_URL is not set. Copy .env.example to .env and configure it.",
            file=sys.stderr,
        )
        return 2

    started_at = datetime.now(UTC)
    source_url = UNPAID_PRIZES_URL

    try:
        result = collect_raw_snapshot(url=source_url, settings=settings)
    except Exception as exc:  # noqa: BLE001
        message = f"fetch failed: {exc}"
        print(f"ERROR: {message}", file=sys.stderr)
        traceback.print_exc()
        _record_failed_run(source_url, started_at, message)
        return 1

    print(f"Saved raw snapshot to {result.file_path}")
    print(
        f"  bytes={result.bytes_written} sha256={result.sha256} "
        f"fetch_method={result.fetch_method}"
    )

    try:
        run_id = _record_success(result, started_at)
    except Exception as exc:  # noqa: BLE001
        print(
            "ERROR: raw file saved but database write failed. "
            "Recover from the path above before retrying.",
            file=sys.stderr,
        )
        print(f"  raw_file_path={result.file_path}", file=sys.stderr)
        print(f"  reason: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    print(f"Recorded ScrapeRun id={run_id} status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
