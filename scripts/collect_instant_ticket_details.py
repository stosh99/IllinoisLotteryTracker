"""Collect and parse all individual instant-ticket detail pages.

Pipeline
--------
1. Discover all detail URLs by walking the instant-tickets hub (live fetch).
2. Batch-fetch every detail page via Playwright (single browser session).
3. Parse each saved HTML with instant_ticket_detail_parser.
4. Print a summary report and save a JSON report.

Does not write parsed metadata to the database.

Usage:
    python scripts/collect_instant_ticket_details.py
    python scripts/collect_instant_ticket_details.py --hub-from-dir data/raw/2026-05-08
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HUB_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"
BASE_URL = "https://www.illinoislottery.com"
DETAIL_WAIT_SELECTOR = "div.itg-details-block"


# ---------------------------------------------------------------------------
# Phase 1: hub discovery
# ---------------------------------------------------------------------------

def _discover_detail_urls(
    settings: object,
    *,
    hub_from_dir: Path | None = None,
) -> list[str]:
    """Return all unique detail URLs from the instant-tickets hub.

    If ``hub_from_dir`` is given, re-uses the most recent hub HTML files in
    that directory instead of making live fetches.
    """
    from illinois_lottery_tracker.instant_ticket_discovery import (
        parse_instant_ticket_hub_html,
    )

    if hub_from_dir is not None:
        return _discover_from_saved_hub(hub_from_dir)

    from illinois_lottery_tracker.raw_collector import collect_raw_snapshot

    detail_urls: list[str] = []
    seen_detail: set[str] = set()
    hub_url: str | None = HUB_URL
    visited_hub: set[str] = set()
    page_num = 0

    while hub_url and hub_url not in visited_hub:
        visited_hub.add(hub_url)
        page_num += 1
        print(f"  Hub page {page_num}: {hub_url}", file=sys.stderr)
        result = collect_raw_snapshot(
            url=hub_url,
            settings=settings,
            filename_prefix=f"instant-ticket-hub-page-{page_num:03d}",
            wait_selector="div.simple-game-card",
        )
        print(f"    Saved: {result.file_path}", file=sys.stderr)
        html = Path(result.file_path).read_text(encoding="utf-8")
        discovery = parse_instant_ticket_hub_html(html, source_url=hub_url)
        for t in discovery.tickets:
            if t.detail_url not in seen_detail:
                seen_detail.add(t.detail_url)
                detail_urls.append(t.detail_url)
        hub_url = discovery.pagination_urls[0] if discovery.pagination_urls else None

    print(f"  Hub discovery complete: {len(detail_urls)} unique detail URLs", file=sys.stderr)
    return detail_urls


def _discover_from_saved_hub(hub_dir: Path) -> list[str]:
    """Parse already-saved hub HTML files found in ``hub_dir``."""
    from illinois_lottery_tracker.instant_ticket_discovery import (
        parse_instant_ticket_hub_html,
    )

    hub_files = sorted(hub_dir.glob("instant-ticket-hub-page-*.html"))
    if not hub_files:
        print(
            f"WARNING: no hub page files found in {hub_dir}",
            file=sys.stderr,
        )
        return []

    detail_urls: list[str] = []
    seen: set[str] = set()
    for f in hub_files:
        discovery = parse_instant_ticket_hub_html(f, source_url=None)
        for t in discovery.tickets:
            if t.detail_url not in seen:
                seen.add(t.detail_url)
                detail_urls.append(t.detail_url)

    print(
        f"  Loaded {len(hub_files)} saved hub files → {len(detail_urls)} detail URLs",
        file=sys.stderr,
    )
    return detail_urls


# ---------------------------------------------------------------------------
# Phase 2: batch fetch
# ---------------------------------------------------------------------------

def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown"


def _batch_fetch_detail_pages(
    detail_urls: list[str],
    settings: object,
) -> list[object]:
    from illinois_lottery_tracker.raw_collector import collect_pages_batch

    url_prefix_pairs = [
        (url, f"instant-ticket-detail-{_slug_from_url(url)}")
        for url in detail_urls
    ]

    def _progress(current: int, total: int, url: str) -> None:
        slug = _slug_from_url(url)
        print(f"  [{current:>3}/{total}] {slug}", file=sys.stderr)

    return collect_pages_batch(
        url_prefix_pairs,
        settings=settings,
        wait_selector=DETAIL_WAIT_SELECTOR,
        on_progress=_progress,
    )


# ---------------------------------------------------------------------------
# Phase 3: parse
# ---------------------------------------------------------------------------

def _parse_detail_pages(
    batch_results: list[object],
) -> list[tuple[object, object | None, str | None]]:
    """Return (batch_result, parsed_detail_or_None, parse_error_or_None) triples."""
    from illinois_lottery_tracker.instant_ticket_detail_parser import (
        parse_instant_ticket_detail_html,
    )
    from illinois_lottery_tracker.raw_collector import BatchPageResult

    triples = []
    for br in batch_results:
        assert isinstance(br, BatchPageResult)
        if not br.success:
            triples.append((br, None, None))
            continue
        try:
            parsed = parse_instant_ticket_detail_html(
                Path(br.file_path),
                source_url=br.url,
            )
            triples.append((br, parsed, None))
        except Exception as exc:
            triples.append((br, None, str(exc)))
    return triples


# ---------------------------------------------------------------------------
# Phase 4: report
# ---------------------------------------------------------------------------

def _build_report(
    triples: list[tuple[object, object | None, str | None]],
    detail_urls: list[str],
    started_at: datetime,
) -> dict:
    from illinois_lottery_tracker.instant_ticket_detail_parser import (
        ParsedInstantTicketDetail,
    )
    from illinois_lottery_tracker.raw_collector import BatchPageResult

    attempted = len(detail_urls)
    fetch_ok = sum(1 for br, _, __ in triples if isinstance(br, BatchPageResult) and br.success)
    fetch_fail = attempted - fetch_ok
    parse_ok = sum(1 for _, p, __ in triples if p is not None)
    parse_fail = sum(
        1 for br, p, err in triples
        if isinstance(br, BatchPageResult) and br.success and p is None
    )

    missing_game_number = 0
    missing_overall_odds = 0
    missing_launch_date = 0
    game_numbers_seen: list[str] = []
    duplicate_game_numbers = 0
    pages: list[dict] = []

    for br, parsed, parse_error in triples:
        assert isinstance(br, BatchPageResult)
        entry: dict = {
            "url": br.url,
            "slug": _slug_from_url(br.url),
            "file_path": br.file_path,
            "fetch_ok": br.success,
            "fetch_error": br.error,
            "parse_ok": parsed is not None,
            "parse_error": parse_error,
        }

        if parsed is not None:
            assert isinstance(parsed, ParsedInstantTicketDetail)
            entry["game_name"] = parsed.game_name
            entry["game_number"] = parsed.game_number
            entry["ticket_price"] = parsed.ticket_price
            entry["overall_odds"] = str(parsed.overall_odds) if parsed.overall_odds else None
            entry["launch_date"] = str(parsed.launch_date) if parsed.launch_date else None
            entry["category"] = parsed.category
            entry["play_style"] = parsed.play_style
            entry["warnings"] = parsed.warnings

            if parsed.game_number is None:
                missing_game_number += 1
            else:
                if parsed.game_number in game_numbers_seen:
                    duplicate_game_numbers += 1
                game_numbers_seen.append(parsed.game_number)

            if parsed.overall_odds is None:
                missing_overall_odds += 1
            if parsed.launch_date is None:
                missing_launch_date += 1
        else:
            entry["warnings"] = []

        pages.append(entry)

    finished_at = datetime.now(UTC)
    return {
        "run": {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        },
        "summary": {
            "urls_attempted": attempted,
            "fetch_ok": fetch_ok,
            "fetch_failed": fetch_fail,
            "parse_ok": parse_ok,
            "parse_failed": parse_fail,
            "missing_game_number": missing_game_number,
            "missing_overall_odds": missing_overall_odds,
            "missing_launch_date": missing_launch_date,
            "duplicate_game_numbers": duplicate_game_numbers,
            "count_matches_hub_total": fetch_ok == attempted,
        },
        "pages": pages,
    }


def _print_report(report: dict) -> None:
    s = report["summary"]
    print()
    print("=" * 60)
    print("Instant Ticket Detail Collection Report")
    print("=" * 60)
    print(f"  URLs attempted:         {s['urls_attempted']}")
    print(f"  Fetch OK:               {s['fetch_ok']}")
    print(f"  Fetch failed:           {s['fetch_failed']}")
    print(f"  Parse OK:               {s['parse_ok']}")
    print(f"  Parse failed:           {s['parse_failed']}")
    print(f"  Missing game_number:    {s['missing_game_number']}")
    print(f"  Missing overall_odds:   {s['missing_overall_odds']}")
    print(f"  Missing launch_date:    {s['missing_launch_date']}")
    print(f"  Duplicate game_numbers: {s['duplicate_game_numbers']}")
    match = "YES" if s["count_matches_hub_total"] else "NO — investigate"
    print(f"  All fetched:            {match}")
    print()

    pages_with_warnings = [p for p in report["pages"] if p.get("warnings")]
    if pages_with_warnings:
        print(f"Pages with warnings ({len(pages_with_warnings)}):")
        for p in pages_with_warnings:
            print(f"  {p['slug']}")
            for w in p["warnings"]:
                print(f"    ! {w}")
        print()

    failed = [p for p in report["pages"] if not p["fetch_ok"] or not p["parse_ok"]]
    if failed:
        print(f"Failures ({len(failed)}):")
        for p in failed:
            reason = p.get("fetch_error") or p.get("parse_error") or "unknown"
            print(f"  {p['slug']}: {reason}")
        print()

    print(f"Started:  {report['run']['started_at']}")
    print(f"Finished: {report['run']['finished_at']}")


def _save_report(report: dict, settings: object) -> Path:
    from illinois_lottery_tracker.paths import dated_raw_dir

    ts = datetime.now(UTC)
    target_dir = dated_raw_dir(ts, settings=settings, create=True)
    ts_str = ts.strftime("%Y%m%dT%H%M%SZ")
    report_path = target_dir / f"instant-ticket-detail-report-{ts_str}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect and parse all instant-ticket detail pages.",
    )
    parser.add_argument(
        "--hub-from-dir",
        metavar="DIR",
        help="Re-use hub HTML files from this directory instead of fetching live.",
    )
    args = parser.parse_args()

    from illinois_lottery_tracker.config import get_settings

    settings = get_settings()
    started_at = datetime.now(UTC)

    # Phase 1
    hub_from_dir = Path(args.hub_from_dir) if args.hub_from_dir else None
    print("Phase 1: Hub discovery", file=sys.stderr)
    detail_urls = _discover_detail_urls(settings, hub_from_dir=hub_from_dir)
    if not detail_urls:
        print("ERROR: no detail URLs discovered — cannot continue.", file=sys.stderr)
        return 1

    # Phase 2
    print(f"\nPhase 2: Fetching {len(detail_urls)} detail pages", file=sys.stderr)
    batch_results = _batch_fetch_detail_pages(detail_urls, settings)

    # Phase 3
    print("\nPhase 3: Parsing saved pages", file=sys.stderr)
    triples = _parse_detail_pages(batch_results)

    # Phase 4
    report = _build_report(triples, detail_urls, started_at)
    _print_report(report)

    report_path = _save_report(report, settings)
    print(f"JSON report: {report_path}")

    return 0 if report["summary"]["fetch_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
