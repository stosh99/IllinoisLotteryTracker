"""Fetch the Illinois Lottery unpaid-prizes page and write a raw snapshot to disk.

This module deliberately does no parsing — it captures the source as-is. It tries
``requests`` first with realistic browser headers; if the origin responds with
HTTP 403 (a common bot-mitigation signal), it falls back to a headless Chromium
fetch via Playwright.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import requests

from .config import Settings, get_settings
from .paths import dated_raw_dir

UNPAID_PRIZES_URL = (
    "https://www.illinoislottery.com/about-the-games/unpaid-instant-games-prizes"
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://www.illinoislottery.com/"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PLAYWRIGHT_TIMEOUT_MS = 45_000
FILENAME_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

FetchMethod = Literal["requests", "playwright"]


@dataclass(frozen=True)
class RawCollectionResult:
    source_url: str
    file_path: str
    sha256: str
    captured_at: datetime
    content_type: str | None
    bytes_written: int
    fetch_method: FetchMethod


@dataclass(frozen=True)
class _FetchOutcome:
    content: bytes
    content_type: str | None
    fetch_method: FetchMethod


def _browser_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": DEFAULT_REFERER,
    }


def _is_forbidden(exc: requests.HTTPError) -> bool:
    response = exc.response
    return response is not None and response.status_code == 403


def _fetch_with_requests(
    url: str,
    *,
    user_agent: str,
    timeout: float,
    session: requests.Session | None,
) -> _FetchOutcome:
    headers = _browser_headers(user_agent)
    http = session or requests
    response = http.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return _FetchOutcome(
        content=response.content,
        content_type=response.headers.get("Content-Type"),
        fetch_method="requests",
    )


def _fetch_with_playwright(
    url: str,
    *,
    user_agent: str,
    timeout_ms: int,
    wait_selector: str | None = None,
) -> _FetchOutcome:
    # Lazy import: the rest of the package must work without playwright installed.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=user_agent,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": DEFAULT_REFERER,
                },
            )
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    pass
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    # networkidle never settles on some pages with long-lived
                    # analytics pings — accept domcontentloaded as good enough.
                    pass
            html = page.content()
        finally:
            browser.close()

    return _FetchOutcome(
        content=html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        fetch_method="playwright",
    )


DEFAULT_FILENAME_PREFIX = "unpaid-instant-games-prizes"


def _filename(captured_at: datetime, prefix: str = DEFAULT_FILENAME_PREFIX) -> str:
    safe_prefix = re.sub(r"[^\w\-]", "-", prefix).strip("-")
    return f"{safe_prefix}-{captured_at.strftime(FILENAME_TIMESTAMP_FORMAT)}.html"


def collect_raw_snapshot(
    *,
    url: str = UNPAID_PRIZES_URL,
    settings: Settings | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    playwright_timeout_ms: int = DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
    session: requests.Session | None = None,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
    wait_selector: str | None = None,
) -> RawCollectionResult:
    """Fetch ``url`` and persist the raw response body under data/raw/YYYY-MM-DD/.

    Tries ``requests`` first; on HTTP 403, falls back to Playwright.
    ``filename_prefix`` controls the saved filename stem.
    ``wait_selector``: CSS selector to wait for after domcontentloaded (Playwright path only).
    """
    settings = settings or get_settings()
    captured_at = datetime.now(UTC)

    try:
        outcome = _fetch_with_requests(
            url, user_agent=user_agent, timeout=timeout, session=session
        )
    except requests.HTTPError as exc:
        if not _is_forbidden(exc):
            raise
        outcome = _fetch_with_playwright(
            url, user_agent=user_agent, timeout_ms=playwright_timeout_ms,
            wait_selector=wait_selector,
        )

    sha256 = hashlib.sha256(outcome.content).hexdigest()
    target_dir: Path = dated_raw_dir(captured_at, settings=settings, create=True)
    target_path = target_dir / _filename(captured_at, filename_prefix)
    target_path.write_bytes(outcome.content)

    return RawCollectionResult(
        source_url=url,
        file_path=str(target_path),
        sha256=sha256,
        captured_at=captured_at,
        content_type=outcome.content_type,
        bytes_written=len(outcome.content),
        fetch_method=outcome.fetch_method,
    )


@dataclass
class BatchPageResult:
    """Outcome for one URL in a batch fetch. ``error`` is set on failure."""

    url: str
    file_path: str | None
    sha256: str | None
    captured_at: datetime | None
    content_type: str | None
    bytes_written: int
    fetch_method: FetchMethod | None
    error: str | None

    @property
    def success(self) -> bool:
        return self.error is None and self.file_path is not None


def _fetch_pages_batch_with_playwright(
    url_prefix_pairs: list[tuple[str, str]],
    *,
    user_agent: str,
    timeout_ms: int,
    wait_selector: str | None,
    settings: Settings,
    on_progress: Callable[[int, int, str], None] | None,
) -> list[BatchPageResult]:
    # Lazy import so the package works without playwright installed.
    from playwright.sync_api import sync_playwright

    results: list[BatchPageResult] = []
    total = len(url_prefix_pairs)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent=user_agent,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": DEFAULT_REFERER,
                },
            )
            for i, (url, prefix) in enumerate(url_prefix_pairs):
                if on_progress:
                    on_progress(i + 1, total, url)
                captured_at = datetime.now(UTC)
                page = ctx.new_page()
                fetch_error: str | None = None
                html = ""
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=timeout_ms)
                        except Exception:
                            # Accept whatever loaded — parser will report missing fields.
                            pass
                    html = page.content()
                except Exception as exc:
                    fetch_error = str(exc)
                finally:
                    page.close()

                if fetch_error:
                    results.append(BatchPageResult(
                        url=url, file_path=None, sha256=None,
                        captured_at=captured_at, content_type=None,
                        bytes_written=0, fetch_method=None, error=fetch_error,
                    ))
                    continue

                content = html.encode("utf-8")
                sha256 = hashlib.sha256(content).hexdigest()
                target_dir = dated_raw_dir(captured_at, settings=settings, create=True)
                target_path = target_dir / _filename(captured_at, prefix)
                target_path.write_bytes(content)
                results.append(BatchPageResult(
                    url=url, file_path=str(target_path), sha256=sha256,
                    captured_at=captured_at, content_type="text/html; charset=utf-8",
                    bytes_written=len(content), fetch_method="playwright", error=None,
                ))
        finally:
            browser.close()

    return results


def collect_pages_batch(
    url_prefix_pairs: list[tuple[str, str]],
    *,
    settings: Settings | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    playwright_timeout_ms: int = DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
    wait_selector: str | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[BatchPageResult]:
    """Fetch multiple URLs using a single Playwright browser, saving each to disk.

    ``url_prefix_pairs``: sequence of ``(url, filename_prefix)`` to fetch.
    ``wait_selector``: CSS selector to wait for after domcontentloaded.
    ``on_progress``: optional ``(current, total, url)`` callback for progress.

    Returns one ``BatchPageResult`` per input URL in the same order.
    Failed pages have ``error`` set and ``file_path=None``.
    """
    return _fetch_pages_batch_with_playwright(
        url_prefix_pairs,
        user_agent=user_agent,
        timeout_ms=playwright_timeout_ms,
        wait_selector=wait_selector,
        settings=settings or get_settings(),
        on_progress=on_progress,
    )
