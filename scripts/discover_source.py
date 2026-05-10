"""Source discovery diagnostic for the Illinois Lottery unclaimed-prizes page.

A one-shot exploratory tool. It does NOT parse prize data, write to production
tables, or persist anything to the database. It launches headless Chromium via
Playwright, exercises the price filters and pagination, captures relevant
network responses, and prints a structured report so we can decide how to
build the real collector.

Outputs land under ``data/raw/discovery/`` (git-ignored):

  data/raw/discovery/rendered-initial.html
  data/raw/discovery/rendered-filter-<label>-page-<NNN>.html
  data/raw/discovery/network/<NNN>-<sanitized-url>.<ext>
  data/raw/discovery/report.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
import traceback
from contextlib import suppress
from pathlib import Path

from playwright.sync_api import Locator, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from illinois_lottery_tracker.discovery import (
    FILTER_LABELS,
    DiscoveryReport,
    FilterResult,
    classify_navigation,
    safe_filename_from_url,
    url_or_content_type_is_relevant,
)
from illinois_lottery_tracker.paths import raw_data_dir

SOURCE_URL = "https://www.illinoislottery.com/about-the-games/unpaid-instant-games-prizes"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PAGE_LOAD_TIMEOUT_MS = 60_000
NETWORK_IDLE_TIMEOUT_MS = 12_000
ACTION_SETTLE_SECONDS = 1.5
MAX_PAGES_PER_FILTER = 50
MAX_NETWORK_BODIES_SAVED = 150
MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB cap per saved body

ROW_COUNT_SELECTORS: tuple[str, ...] = (
    "[data-test*='game' i], [data-testid*='game' i], [data-qa*='game' i]",
    "[data-test*='ticket' i], [data-testid*='ticket' i]",
    "li[class*='game' i]",
    "li[class*='card' i]",
    "div[class*='game-card' i]",
    "div[class*='ticket-card' i]",
    "div[class*='prize-card' i]",
    "tbody tr",
    "article",
)

NEXT_BUTTON_SELECTORS: tuple[str, ...] = (
    "button[aria-label*='Next' i]",
    "a[aria-label*='Next' i]",
    "button[class*='next' i]",
    "a[class*='next' i]",
    "[data-test*='next' i], [data-testid*='next' i]",
)

LOAD_MORE_RE = re.compile(r"load more|show more", re.I)
NEXT_TEXT_RE = re.compile(r"^\s*(next|›|»|→)\s*$", re.I)


def discovery_root() -> Path:
    root = raw_data_dir() / "discovery"
    (root / "network").mkdir(parents=True, exist_ok=True)
    return root


def slugify(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower() or "filter"


def settle(page: Page, *, label: str = "") -> None:
    """Best-effort wait for the page/SPA to stop animating after a click."""
    with suppress(PlaywrightTimeoutError, Exception):
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    time.sleep(ACTION_SETTLE_SECONDS)


def count_rows(page: Page) -> tuple[int, str]:
    """Return (count, selector) for the densest plausible result-row selector."""
    best = (0, "")
    for sel in ROW_COUNT_SELECTORS:
        try:
            n = page.locator(sel).count()
        except Exception:
            n = 0
        if n > best[0]:
            best = (n, sel)
    return best


def first_visible_enabled(loc: Locator, *, max_check: int = 20) -> Locator | None:
    """Return the first locator entry that is both visible and enabled."""
    try:
        n = min(loc.count(), max_check)
    except Exception:
        return None
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible() and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def find_filter_locator(page: Page, label: str) -> Locator | None:
    """Find a clickable element representing the given filter label."""
    candidates: list[Locator] = [
        page.get_by_role("button", name=label, exact=False),
        page.get_by_role("link", name=label, exact=False),
        page.get_by_role("tab", name=label, exact=False),
        page.locator(f"button:has-text({json.dumps(label)})"),
        page.locator(f"a:has-text({json.dumps(label)})"),
    ]
    for loc in candidates:
        hit = first_visible_enabled(loc)
        if hit is not None:
            return hit
    return None


def find_next_pagination(page: Page) -> Locator | None:
    """Find a clickable Next-page or Load-More control, if visible."""
    role_candidates = [
        page.get_by_role("button", name=NEXT_TEXT_RE),
        page.get_by_role("link", name=NEXT_TEXT_RE),
        page.get_by_role("button", name=LOAD_MORE_RE),
        page.get_by_role("link", name=LOAD_MORE_RE),
    ]
    for loc in role_candidates:
        hit = first_visible_enabled(loc)
        if hit is not None:
            return hit
    for sel in NEXT_BUTTON_SELECTORS:
        hit = first_visible_enabled(page.locator(sel))
        if hit is not None:
            return hit
    return None


def has_any_pagination_control(page: Page) -> bool:
    """Heuristic: are pagination-shaped controls visible at all?"""
    if find_next_pagination(page) is not None:
        return True
    selectors = (
        "[role='navigation'][aria-label*='pag' i]",
        "nav[aria-label*='pag' i]",
        "[class*='pagination' i]",
        "[class*='paging' i]",
        "ul[class*='pager' i]",
    )
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def save_html(page: Page, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page.content(), encoding="utf-8")


def extension_for_content_type(content_type: str | None) -> str:
    ct = (content_type or "").lower()
    if "json" in ct:
        return ".json"
    if "html" in ct:
        return ".html"
    if "xml" in ct:
        return ".xml"
    if "javascript" in ct:
        return ".js"
    if "text" in ct:
        return ".txt"
    return ".bin"


class NetworkRecorder:
    def __init__(self, network_dir: Path) -> None:
        self.network_dir = network_dir
        self.relevant_urls: list[str] = []
        self.saved_paths: list[str] = []
        self._saved_count = 0

    def handle(self, response: Response) -> None:
        try:
            url = response.url
            ct = response.headers.get("content-type")
            if not url_or_content_type_is_relevant(url, ct):
                return
            self.relevant_urls.append(url)
            if self._saved_count >= MAX_NETWORK_BODIES_SAVED:
                return
            try:
                body = response.body()
            except Exception:
                return
            if not body or len(body) > MAX_BODY_BYTES:
                return
            ext = extension_for_content_type(ct)
            name = safe_filename_from_url(url, self._saved_count) + ext
            target = self.network_dir / name
            target.write_bytes(body)
            self.saved_paths.append(str(target))
            self._saved_count += 1
        except Exception:
            # Never let a recorder error break the discovery run.
            pass


def explore_filter(
    page: Page, label: str, root: Path, *, slug: str
) -> FilterResult:
    result = FilterResult(label=label)
    locator = find_filter_locator(page, label)
    if locator is None:
        result.notes.append("filter control not found on page")
        return result

    result.discovered = True
    result.pre_url = page.url
    try:
        locator.click()
    except Exception as exc:
        result.notes.append(f"click failed: {exc}")
        return result
    settle(page, label=label)
    after_filter_url = page.url
    result.post_urls.append(after_filter_url)

    page_index = 1
    last_url = result.pre_url or after_filter_url
    seen_urls: set[str] = set()

    while page_index <= MAX_PAGES_PER_FILTER:
        rows, _selector = count_rows(page)
        result.rows_per_page.append(rows)
        result.pages_seen = page_index

        html_path = root / f"rendered-filter-{slug}-page-{page_index:03d}.html"
        save_html(page, html_path)
        result.saved_html_paths.append(str(html_path))

        nxt = find_next_pagination(page)
        if nxt is None:
            if page_index == 1:
                result.has_pagination = has_any_pagination_control(page)
            break

        result.has_pagination = True
        before = page.url
        try:
            nxt.click()
        except Exception as exc:
            result.notes.append(f"next click failed at page {page_index}: {exc}")
            break
        settle(page)
        after = page.url
        result.post_urls.append(after)
        kind = classify_navigation(before, after)
        if result.pagination_kind in ("unknown", kind):
            result.pagination_kind = kind
        else:
            result.pagination_kind = "mixed"

        if after == last_url and after in seen_urls:
            # Click had no observable effect — bail to avoid an infinite loop.
            result.notes.append(
                f"pagination stalled at page {page_index} (url unchanged twice)"
            )
            break
        seen_urls.add(after)
        last_url = after
        page_index += 1

    if result.has_pagination and result.pagination_kind == "unknown":
        result.pagination_kind = "client-side"
    if not result.has_pagination:
        result.pagination_kind = "none"
    return result


def filter_url_change_kind(filter_result: FilterResult) -> str:
    """Best classification of the filter activation itself (not pagination)."""
    if filter_result.pre_url is None or not filter_result.post_urls:
        return "unknown"
    return classify_navigation(filter_result.pre_url, filter_result.post_urls[0])


def run_discovery() -> DiscoveryReport:
    root = discovery_root()
    network_dir = root / "network"
    report = DiscoveryReport()
    recorder = NetworkRecorder(network_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.illinoislottery.com/",
                },
            )
            page = context.new_page()
            page.on("response", recorder.handle)

            page.goto(
                SOURCE_URL,
                timeout=PAGE_LOAD_TIMEOUT_MS,
                wait_until="domcontentloaded",
            )
            settle(page, label="initial-load")

            report.page_title = page.title()
            report.final_url = page.url

            save_html(page, root / "rendered-initial.html")

            for label in FILTER_LABELS:
                result = explore_filter(page, label, root, slug=slugify(label))
                if result.discovered:
                    report.detected_filters.append(label)
                    nav_kind = filter_url_change_kind(result)
                    if nav_kind != "client-side":
                        result.notes.append(f"filter activation: {nav_kind}")
                report.filters.append(result)
        finally:
            browser.close()

    report.relevant_network_urls = sorted(set(recorder.relevant_urls))
    report.json_responses_saved = list(recorder.saved_paths)
    report.obvious_json_api = any(
        ".json" in u.lower() or "/api/" in u.lower() for u in report.relevant_network_urls
    )
    report.fully_collectable_via_api = bool(report.json_responses_saved) and any(
        any(kw in u.lower() for kw in ("prize", "game", "ticket", "instant"))
        for u in report.relevant_network_urls
    )
    return report


def print_report(report: DiscoveryReport) -> None:
    print("=" * 72)
    print(f"Page title : {report.page_title!r}")
    print(f"Final URL  : {report.final_url}")
    print(f"Filters    : {report.detected_filters or '(none detected)'}")
    print("-" * 72)
    for fr in report.filters:
        status = "FOUND" if fr.discovered else "missing"
        total = fr.total_rows
        print(f"[{status}] {fr.label}")
        if not fr.discovered:
            for note in fr.notes:
                print(f"    note: {note}")
            continue
        print(
            f"    pages_seen={fr.pages_seen} total_rows~={total} "
            f"per_page={fr.rows_per_page}"
        )
        print(
            f"    has_pagination={fr.has_pagination} "
            f"pagination_kind={fr.pagination_kind}"
        )
        if fr.notes:
            for note in fr.notes:
                print(f"    note: {note}")
    print("-" * 72)
    print(f"Relevant network URLs   : {len(report.relevant_network_urls)}")
    for u in report.relevant_network_urls[:25]:
        print(f"    {u}")
    if len(report.relevant_network_urls) > 25:
        print(f"    ...and {len(report.relevant_network_urls) - 25} more")
    print(f"Saved network bodies    : {len(report.json_responses_saved)}")
    print(f"Obvious JSON/API found  : {report.obvious_json_api}")
    print(f"Likely API-collectable  : {report.fully_collectable_via_api}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a one-shot Playwright diagnostic against the Illinois Lottery "
            "unclaimed-prizes source page."
        )
    )
    parser.parse_args(argv)

    try:
        report = run_discovery()
    except Exception as exc:
        print(f"ERROR: discovery run failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    root = discovery_root()
    report_path = root / "report.json"
    report_path.write_text(
        json.dumps(dataclasses.asdict(report), indent=2, default=str),
        encoding="utf-8",
    )
    print_report(report)
    print(f"Wrote structured report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
