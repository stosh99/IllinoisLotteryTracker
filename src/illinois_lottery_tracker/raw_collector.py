"""Fetch Illinois Lottery source pages and write raw snapshots to disk.

This module deliberately does no parsing -- it captures the source as-is. By
default it tries ``requests`` first and falls back to Playwright when the origin
returns HTTP 403 or a successful-looking Cloudflare challenge page. Operators
can explicitly supply :class:`PersistentChromeOptions` to use the machine's
installed Chrome with a dedicated persistent profile.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import requests

from .config import Settings, get_settings
from .paths import dated_raw_dir, raw_data_dir

UNPAID_PRIZES_URL = (
    "https://www.illinoislottery.com/about-the-games/unpaid-instant-games-prizes"
)
UNPAID_PRIZES_WAIT_SELECTOR = ".unclaimed-prizes-table__row"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://www.illinoislottery.com/"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PLAYWRIGHT_TIMEOUT_MS = 45_000
DEFAULT_CHROME_EXECUTABLE = "/usr/bin/google-chrome"
FILENAME_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

FetchMethod = Literal["requests", "playwright", "chrome"]

CLOUDFLARE_CHALLENGE_MARKERS: tuple[bytes, ...] = (
    b"cf-browser-verification",
    b"just a moment...",
    b"challenge-form",
    b"attention required! | cloudflare",
    b"/cdn-cgi/challenge-platform/",
)


@dataclass(frozen=True)
class PersistentChromeOptions:
    """Launch installed Chrome with an isolated, reusable browser profile.

    ``profile_dir`` must be dedicated to the collector. It must never point at
    a person's normal Chrome profile, because Chrome does not safely support
    concurrent access to a profile and that would expose unrelated browser
    history/cookies to the collection process.
    """

    profile_dir: Path
    executable_path: str = DEFAULT_CHROME_EXECUTABLE
    headless: bool = False
    force_x11: bool = False


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


def cloudflare_challenge_marker(content: bytes) -> str | None:
    """Return the first known Cloudflare challenge marker in ``content``."""
    lowered = content.lower()
    for marker in CLOUDFLARE_CHALLENGE_MARKERS:
        if marker in lowered:
            return marker.decode("ascii")
    return None


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


def _prepare_persistent_chrome(options: PersistentChromeOptions) -> tuple[Path, Path]:
    executable_path = Path(options.executable_path).expanduser().resolve()
    if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
        raise RuntimeError(
            f"Chrome executable is missing or not executable: {executable_path}"
        )

    profile_dir = options.profile_dir.expanduser().resolve()
    if profile_dir.exists() and not profile_dir.is_dir():
        raise RuntimeError(f"Chrome profile path is not a directory: {profile_dir}")
    profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    return executable_path, profile_dir


@contextmanager
def _playwright_context(
    playwright: Any,
    *,
    user_agent: str,
    chrome_options: PersistentChromeOptions | None,
):
    """Yield ``(BrowserContext, fetch_method)`` and close it safely."""
    if chrome_options is not None:
        executable_path, profile_dir = _prepare_persistent_chrome(chrome_options)
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "executable_path": str(executable_path),
            "headless": chrome_options.headless,
            "locale": "en-US",
        }
        if chrome_options.force_x11:
            launch_kwargs["args"] = ["--ozone-platform=x11"]
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            yield context, "chrome"
        finally:
            context.close()
        return

    browser = playwright.chromium.launch(headless=True)
    try:
        context = browser.new_context(
            user_agent=user_agent,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": DEFAULT_REFERER,
            },
        )
        yield context, "playwright"
    finally:
        browser.close()


def _fetch_with_playwright(
    url: str,
    *,
    user_agent: str,
    timeout_ms: int,
    wait_selector: str | None = None,
    chrome_options: PersistentChromeOptions | None = None,
) -> _FetchOutcome:
    # Lazy import: the rest of the package must work without playwright installed.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        with _playwright_context(
            p, user_agent=user_agent, chrome_options=chrome_options
        ) as (context, fetch_method):
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    # Persist what loaded so downstream validation can identify
                    # a challenge page or a changed source layout precisely.
                    pass
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    # networkidle never settles on some pages with long-lived
                    # analytics pings — accept domcontentloaded as good enough.
                    pass
            html = page.content()

    return _FetchOutcome(
        content=html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        fetch_method=fetch_method,
    )


def _fetch_with_browser(
    url: str,
    *,
    user_agent: str,
    timeout_ms: int,
    wait_selector: str | None,
    chrome_options: PersistentChromeOptions | None,
) -> _FetchOutcome:
    kwargs: dict[str, Any] = {
        "user_agent": user_agent,
        "timeout_ms": timeout_ms,
        "wait_selector": wait_selector,
    }
    # Preserve the original call shape for compatibility with lightweight
    # monkeypatched collectors while making persistent Chrome opt-in.
    if chrome_options is not None:
        kwargs["chrome_options"] = chrome_options
    return _fetch_with_playwright(url, **kwargs)


DEFAULT_FILENAME_PREFIX = "unpaid-instant-games-prizes"


def _filename(captured_at: datetime, prefix: str = DEFAULT_FILENAME_PREFIX) -> str:
    safe_prefix = re.sub(r"[^\w\-]", "-", prefix).strip("-")
    return f"{safe_prefix}-{captured_at.strftime(FILENAME_TIMESTAMP_FORMAT)}.html"


def _persist_content_addressed(
    content: bytes,
    *,
    captured_at: datetime,
    filename_prefix: str,
    settings: Settings,
) -> tuple[Path, str]:
    """Persist one immutable blob and a per-capture hard link.

    Existing capture files are never replaced.  Filesystems without hard-link
    support receive a normal copy while retaining the same content hash.
    """
    sha256 = hashlib.sha256(content).hexdigest()
    blob_dir = raw_data_dir(settings) / ".content" / sha256[:2]
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob_path = blob_dir / f"{sha256}.html"
    if not blob_path.exists():
        temporary = blob_dir / f".{sha256}.{os.getpid()}.tmp"
        try:
            temporary.write_bytes(content)
            try:
                temporary.replace(blob_path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    elif blob_path.read_bytes() != content:
        raise RuntimeError(f"content hash collision at {blob_path}")

    target_dir = dated_raw_dir(captured_at, settings=settings, create=True)
    requested = target_dir / _filename(captured_at, filename_prefix)
    target_path = requested
    sequence = 1
    while target_path.exists():
        if target_path.read_bytes() == content:
            sequence += 1
            target_path = requested.with_name(
                f"{requested.stem}-{sequence:02d}{requested.suffix}"
            )
            continue
        sequence += 1
        target_path = requested.with_name(
            f"{requested.stem}-{sequence:02d}{requested.suffix}"
        )
    try:
        os.link(blob_path, target_path)
    except OSError:
        target_path.write_bytes(content)
    return target_path, sha256


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
    chrome_options: PersistentChromeOptions | None = None,
    requests_first: bool = True,
) -> RawCollectionResult:
    """Fetch ``url`` and persist the raw response body under data/raw/YYYY-MM-DD/.

    Tries ``requests`` first; on HTTP 403 or a Cloudflare challenge response,
    falls back to Playwright. Set ``requests_first=False`` to exercise the
    browser path directly. When ``chrome_options`` is supplied, that browser
    path uses installed Chrome and its dedicated persistent profile.
    ``filename_prefix`` controls the saved filename stem.
    ``wait_selector``: CSS selector to wait for after domcontentloaded (Playwright path only).
    """
    settings = settings or get_settings()
    captured_at = datetime.now(UTC)

    if requests_first:
        try:
            outcome = _fetch_with_requests(
                url, user_agent=user_agent, timeout=timeout, session=session
            )
        except requests.HTTPError as exc:
            if not _is_forbidden(exc):
                raise
            outcome = _fetch_with_browser(
                url,
                user_agent=user_agent,
                timeout_ms=playwright_timeout_ms,
                wait_selector=wait_selector,
                chrome_options=chrome_options,
            )
        else:
            if cloudflare_challenge_marker(outcome.content) is not None:
                outcome = _fetch_with_browser(
                    url,
                    user_agent=user_agent,
                    timeout_ms=playwright_timeout_ms,
                    wait_selector=wait_selector,
                    chrome_options=chrome_options,
                )
    else:
        outcome = _fetch_with_browser(
            url,
            user_agent=user_agent,
            timeout_ms=playwright_timeout_ms,
            wait_selector=wait_selector,
            chrome_options=chrome_options,
        )

    target_path, sha256 = _persist_content_addressed(
        outcome.content,
        captured_at=captured_at,
        filename_prefix=filename_prefix,
        settings=settings,
    )

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
    chrome_options: PersistentChromeOptions | None = None,
) -> list[BatchPageResult]:
    # Lazy import so the package works without playwright installed.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    results: list[BatchPageResult] = []
    total = len(url_prefix_pairs)

    with sync_playwright() as p:
        with _playwright_context(
            p, user_agent=user_agent, chrome_options=chrome_options
        ) as (ctx, fetch_method):
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
                        except PlaywrightTimeoutError:
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
                target_path, sha256 = _persist_content_addressed(
                    content,
                    captured_at=captured_at,
                    filename_prefix=prefix,
                    settings=settings,
                )
                results.append(BatchPageResult(
                    url=url, file_path=str(target_path), sha256=sha256,
                    captured_at=captured_at, content_type="text/html; charset=utf-8",
                    bytes_written=len(content), fetch_method=fetch_method, error=None,
                ))

    return results


def collect_pages_batch(
    url_prefix_pairs: list[tuple[str, str]],
    *,
    settings: Settings | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    playwright_timeout_ms: int = DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
    wait_selector: str | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    chrome_options: PersistentChromeOptions | None = None,
) -> list[BatchPageResult]:
    """Fetch multiple URLs using a single Playwright browser, saving each to disk.

    ``url_prefix_pairs``: sequence of ``(url, filename_prefix)`` to fetch.
    ``wait_selector``: CSS selector to wait for after domcontentloaded.
    ``on_progress``: optional ``(current, total, url)`` callback for progress.

    Returns one ``BatchPageResult`` per input URL in the same order.
    Failed pages have ``error`` set and ``file_path=None``.
    """
    kwargs: dict[str, Any] = {
        "user_agent": user_agent,
        "timeout_ms": playwright_timeout_ms,
        "wait_selector": wait_selector,
        "settings": settings or get_settings(),
        "on_progress": on_progress,
    }
    if chrome_options is not None:
        kwargs["chrome_options"] = chrome_options
    return _fetch_pages_batch_with_playwright(url_prefix_pairs, **kwargs)
