"""Discover individual instant-ticket detail URLs from the Illinois Lottery hub.

Fetches the hub page (live network, Playwright fallback) or parses a saved HTML
file, then prints the discovered ticket detail URLs and pagination info.

Usage:
    python scripts/discover_instant_ticket_pages.py
    python scripts/discover_instant_ticket_pages.py --from-file path/to/hub.html
    python scripts/discover_instant_ticket_pages.py --all-pages
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

HUB_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"
BASE_URL = "https://www.illinoislottery.com"


def _fetch_hub_page(url: str, page_num: int) -> str:
    """Fetch a hub page via Playwright (site returns 403 to plain requests)."""
    from playwright.sync_api import sync_playwright

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=ua,
            extra_http_headers={"Referer": BASE_URL},
        )
        page = ctx.new_page()
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("div.simple-game-card", timeout=30_000)
        except Exception:
            pass
        html = page.content()
        browser.close()

    # Save raw file
    from illinois_lottery_tracker.config import get_settings
    from illinois_lottery_tracker.paths import dated_raw_dir

    captured_at = datetime.now(UTC)
    settings = get_settings()
    target_dir = dated_raw_dir(captured_at, settings=settings, create=True)
    prefix = f"instant-ticket-hub-page-{page_num:03d}"
    ts = captured_at.strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"{prefix}-{ts}.html"
    path.write_text(html, encoding="utf-8")
    print(f"  Saved: {path}", file=sys.stderr)
    return html


def _discover_page(html: str, source_url: str | None, page_num: int) -> object:
    from illinois_lottery_tracker.instant_ticket_discovery import parse_instant_ticket_hub_html

    return parse_instant_ticket_hub_html(html, source_url=source_url)


def _print_result(result: object, page_num: int) -> None:
    from illinois_lottery_tracker.instant_ticket_discovery import (
        InstantTicketHubDiscoveryResult,
    )

    assert isinstance(result, InstantTicketHubDiscoveryResult)
    print(f"\n--- Page {page_num} ---")
    print(f"Source:     {result.source_url or '(local file)'}")
    print(f"Range:      {result.current_page_label or 'unknown'}")
    print(f"Total:      {result.total_count if result.total_count is not None else 'unknown'}")
    print(f"Discovered: {len(result.tickets)} tickets")
    print(f"Next pages: {len(result.pagination_urls)}")
    for purl in result.pagination_urls:
        print(f"  {purl}")
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  ! {w}")
    print()
    for t in result.tickets:
        price_str = f"${t.ticket_price}" if t.ticket_price is not None else "?"
        print(f"  [{price_str:>4}]  {t.detail_url}  ({t.display_name or t.slug})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover Illinois Lottery instant-ticket URLs.")
    parser.add_argument(
        "--from-file", metavar="PATH",
        help="Parse a saved hub HTML file instead of fetching live.",
    )
    parser.add_argument(
        "--all-pages", action="store_true",
        help="Follow pagination and fetch all hub pages.",
    )
    args = parser.parse_args()

    all_tickets = []

    if args.from_file:
        path = Path(args.from_file)
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 1
        html = path.read_text(encoding="utf-8")
        result = _discover_page(html, source_url=None, page_num=1)
        _print_result(result, page_num=1)
        all_tickets.extend(result.tickets)
    else:
        url = HUB_URL
        page_num = 1
        visited: set[str] = set()
        while url and url not in visited:
            visited.add(url)
            print(f"Fetching page {page_num}: {url}", file=sys.stderr)
            html = _fetch_hub_page(url, page_num)
            result = _discover_page(html, source_url=url, page_num=page_num)
            _print_result(result, page_num)
            all_tickets.extend(result.tickets)
            if not args.all_pages or not result.pagination_urls:
                break
            url = result.pagination_urls[0]
            page_num += 1

    print(f"\nTotal unique tickets across all fetched pages: {len(all_tickets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
