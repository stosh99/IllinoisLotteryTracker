"""Tests for illinois_lottery_tracker.raw_collector.

These tests never hit the live Illinois Lottery site. The HTTP layer is
replaced with a fake ``requests.Session``; the Playwright fallback is
monkeypatched so no browser is launched.
"""

from __future__ import annotations

import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from illinois_lottery_tracker import raw_collector
from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.paths import dated_raw_dir
from illinois_lottery_tracker.raw_collector import (
    BatchPageResult,
    PersistentChromeOptions,
    _browser_headers,
    _FetchOutcome,
    _filename,
    _is_forbidden,
    _prepare_persistent_chrome,
    cloudflare_challenge_marker,
    collect_pages_batch,
    collect_raw_snapshot,
)


def _settings(raw_dir: Path) -> Settings:
    return Settings(database_url=None, raw_data_dir=str(raw_dir))


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes,
        content_type: str | None = "text/html; charset=utf-8",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers: dict[str, str] = {}
        if content_type is not None:
            self.headers["Content-Type"] = content_type

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self  # type: ignore[assignment]
            raise err


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _FakeResponse:
        self.calls.append((url, {"headers": dict(headers), "timeout": timeout}))
        return self._response


def test_browser_headers_includes_required_keys():
    headers = _browser_headers("test-ua/1.0")

    expected_keys = {
        "User-Agent",
        "Accept",
        "Accept-Language",
        "Accept-Encoding",
        "Connection",
        "Upgrade-Insecure-Requests",
        "Referer",
    }
    assert expected_keys.issubset(headers.keys())
    assert headers["User-Agent"] == "test-ua/1.0"
    assert headers["Referer"] == "https://www.illinoislottery.com/"
    assert headers["Upgrade-Insecure-Requests"] == "1"


def test_is_forbidden_only_for_403():
    err_403 = requests.HTTPError("403")
    err_403.response = _FakeResponse(403, b"")  # type: ignore[assignment]
    err_500 = requests.HTTPError("500")
    err_500.response = _FakeResponse(500, b"")  # type: ignore[assignment]

    assert _is_forbidden(err_403) is True
    assert _is_forbidden(err_500) is False


@pytest.mark.parametrize(
    "content",
    [
        b"<title>Just a moment...</title>",
        b"<div id='challenge-form'></div>",
        b"<script src='/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1'></script>",
    ],
)
def test_cloudflare_challenge_marker_detects_known_markers(content):
    assert cloudflare_challenge_marker(content) is not None


def test_cloudflare_challenge_marker_ignores_normal_html():
    assert cloudflare_challenge_marker(b"<html><h1>Illinois Lottery</h1></html>") is None


def test_collect_uses_requests_path_on_success(tmp_path, monkeypatch):
    body = b"<html>requests-success</html>"
    fake = _FakeSession(_FakeResponse(200, body))

    def boom(*args, **kwargs):
        raise AssertionError("playwright fallback must not run on 200")

    monkeypatch.setattr(raw_collector, "_fetch_with_playwright", boom)

    result = collect_raw_snapshot(
        url="https://example.test/page",
        settings=_settings(tmp_path),
        session=fake,
    )

    assert result.fetch_method == "requests"
    assert result.bytes_written == len(body)
    assert Path(result.file_path).read_bytes() == body
    assert result.content_type == "text/html; charset=utf-8"

    assert len(fake.calls) == 1
    sent_headers = fake.calls[0][1]["headers"]
    assert sent_headers["User-Agent"].startswith("Mozilla/5.0")
    assert sent_headers["Referer"] == "https://www.illinoislottery.com/"


def test_collect_falls_back_to_playwright_on_403(tmp_path, monkeypatch):
    fake = _FakeSession(_FakeResponse(403, b""))

    playwright_body = b"<html>from-playwright</html>"
    calls: dict[str, Any] = {"count": 0, "kwargs": None}

    def fake_playwright(url, *, user_agent, timeout_ms, wait_selector=None):
        calls["count"] += 1
        calls["kwargs"] = {
            "url": url,
            "user_agent": user_agent,
            "timeout_ms": timeout_ms,
        }
        return _FetchOutcome(
            content=playwright_body,
            content_type="text/html; charset=utf-8",
            fetch_method="playwright",
        )

    monkeypatch.setattr(raw_collector, "_fetch_with_playwright", fake_playwright)

    result = collect_raw_snapshot(
        url="https://example.test/page",
        settings=_settings(tmp_path),
        session=fake,
    )

    assert calls["count"] == 1
    assert calls["kwargs"]["url"] == "https://example.test/page"
    assert result.fetch_method == "playwright"
    assert Path(result.file_path).read_bytes() == playwright_body
    assert result.bytes_written == len(playwright_body)


def test_collect_falls_back_to_browser_on_200_cloudflare_challenge(
    tmp_path, monkeypatch
):
    challenge = b"<html><title>Just a moment...</title></html>"
    fake = _FakeSession(_FakeResponse(200, challenge))
    browser_body = b"<html><div class='real-source'>loaded</div></html>"
    calls = 0

    def fake_playwright(url, *, user_agent, timeout_ms, wait_selector=None):
        nonlocal calls
        calls += 1
        return _FetchOutcome(
            content=browser_body,
            content_type="text/html; charset=utf-8",
            fetch_method="playwright",
        )

    monkeypatch.setattr(raw_collector, "_fetch_with_playwright", fake_playwright)

    result = collect_raw_snapshot(
        url="https://example.test/page",
        settings=_settings(tmp_path),
        session=fake,
    )

    assert calls == 1
    assert result.fetch_method == "playwright"
    assert Path(result.file_path).read_bytes() == browser_body


def test_collect_can_force_dedicated_persistent_chrome_path(tmp_path, monkeypatch):
    browser_body = b"<html>installed-chrome</html>"
    options = PersistentChromeOptions(profile_dir=tmp_path / "profile")
    received_options = None

    def fake_playwright(
        url, *, user_agent, timeout_ms, wait_selector=None, chrome_options=None
    ):
        nonlocal received_options
        received_options = chrome_options
        return _FetchOutcome(
            content=browser_body,
            content_type="text/html; charset=utf-8",
            fetch_method="chrome",
        )

    monkeypatch.setattr(raw_collector, "_fetch_with_playwright", fake_playwright)

    result = collect_raw_snapshot(
        url="https://example.test/page",
        settings=_settings(tmp_path / "raw"),
        chrome_options=options,
        requests_first=False,
    )

    assert received_options is options
    assert result.fetch_method == "chrome"
    assert Path(result.file_path).read_bytes() == browser_body


def test_prepare_persistent_chrome_creates_private_profile(tmp_path):
    executable = tmp_path / "chrome"
    executable.write_text("test executable", encoding="utf-8")
    executable.chmod(0o700)
    profile = tmp_path / "collector-profile"

    resolved_executable, resolved_profile = _prepare_persistent_chrome(
        PersistentChromeOptions(
            profile_dir=profile,
            executable_path=str(executable),
        )
    )

    assert resolved_executable == executable.resolve()
    assert resolved_profile == profile.resolve()
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700


def test_collect_does_not_fall_back_on_500(tmp_path, monkeypatch):
    fake = _FakeSession(_FakeResponse(500, b""))

    def boom(*args, **kwargs):
        raise AssertionError("playwright must not run on non-403 errors")

    monkeypatch.setattr(raw_collector, "_fetch_with_playwright", boom)

    with pytest.raises(requests.HTTPError):
        collect_raw_snapshot(
            url="https://example.test/page",
            settings=_settings(tmp_path),
            session=fake,
        )

    # On non-403, no file should have been written.
    assert list(tmp_path.iterdir()) == []


def test_collect_filename_is_dated_and_unique(tmp_path, monkeypatch):
    fake = _FakeSession(_FakeResponse(200, b"<html>x</html>"))
    monkeypatch.setattr(
        raw_collector,
        "_fetch_with_playwright",
        lambda *a, **kw: pytest.fail("should not be called"),
    )

    result = collect_raw_snapshot(
        url="https://example.test/page",
        settings=_settings(tmp_path),
        session=fake,
    )

    file_path = Path(result.file_path)
    assert file_path.parent.name == result.captured_at.strftime("%Y-%m-%d")
    assert file_path.name.startswith("unpaid-instant-games-prizes-")
    assert file_path.name.endswith(".html")


def test_identical_captures_share_content_inode_without_overwriting(tmp_path, monkeypatch):
    body = b"<html>unchanged</html>"
    fake = _FakeSession(_FakeResponse(200, body))
    monkeypatch.setattr(
        raw_collector,
        "_fetch_with_playwright",
        lambda *a, **kw: pytest.fail("should not be called"),
    )

    first = collect_raw_snapshot(settings=_settings(tmp_path), session=fake)
    second = collect_raw_snapshot(settings=_settings(tmp_path), session=fake)

    first_path = Path(first.file_path)
    second_path = Path(second.file_path)
    assert first_path != second_path
    assert first_path.stat().st_ino == second_path.stat().st_ino
    assert first.sha256 == second.sha256 == hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# collect_pages_batch
# ---------------------------------------------------------------------------

def _fake_batch_playwright(body: bytes):
    """Return a fake _fetch_pages_batch_with_playwright that writes ``body`` for each URL."""
    def _fake(url_prefix_pairs, *, user_agent, timeout_ms, wait_selector, settings, on_progress):
        results = []
        for url, prefix in url_prefix_pairs:
            if on_progress:
                on_progress(len(results) + 1, len(url_prefix_pairs), url)
            captured_at = datetime.now(UTC)
            target_dir = dated_raw_dir(captured_at, settings=settings, create=True)
            target_path = target_dir / _filename(captured_at, prefix)
            target_path.write_bytes(body)
            results.append(BatchPageResult(
                url=url,
                file_path=str(target_path),
                sha256=hashlib.sha256(body).hexdigest(),
                captured_at=captured_at,
                content_type="text/html; charset=utf-8",
                bytes_written=len(body),
                fetch_method="playwright",
                error=None,
            ))
        return results
    return _fake


def test_collect_pages_batch_returns_one_result_per_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        raw_collector, "_fetch_pages_batch_with_playwright",
        _fake_batch_playwright(b"<html>ok</html>"),
    )
    pairs = [
        ("https://example.test/a", "prefix-a"),
        ("https://example.test/b", "prefix-b"),
    ]
    results = collect_pages_batch(pairs, settings=_settings(tmp_path))
    assert len(results) == 2


def test_collect_pages_batch_success_results_have_files(tmp_path, monkeypatch):
    body = b"<html>content</html>"
    monkeypatch.setattr(
        raw_collector, "_fetch_pages_batch_with_playwright",
        _fake_batch_playwright(body),
    )
    pairs = [("https://example.test/x", "my-prefix")]
    results = collect_pages_batch(pairs, settings=_settings(tmp_path))
    assert results[0].success is True
    assert Path(results[0].file_path).read_bytes() == body


def test_collect_pages_batch_failed_page_recorded(tmp_path, monkeypatch):
    def _fail_first(  # noqa: E501
        url_prefix_pairs, *, user_agent, timeout_ms, wait_selector, settings, on_progress
    ):
        url, _ = url_prefix_pairs[0]
        return [BatchPageResult(
            url=url, file_path=None, sha256=None, captured_at=None,
            content_type=None, bytes_written=0, fetch_method=None,
            error="timeout",
        )]

    monkeypatch.setattr(raw_collector, "_fetch_pages_batch_with_playwright", _fail_first)
    results = collect_pages_batch(
        [("https://example.test/fail", "p")], settings=_settings(tmp_path)
    )
    assert results[0].success is False
    assert results[0].error == "timeout"
    assert results[0].file_path is None


def test_collect_pages_batch_preserves_order(tmp_path, monkeypatch):
    urls = [f"https://example.test/{i}" for i in range(5)]
    monkeypatch.setattr(
        raw_collector, "_fetch_pages_batch_with_playwright",
        _fake_batch_playwright(b"x"),
    )
    pairs = [(url, f"p{i}") for i, url in enumerate(urls)]
    results = collect_pages_batch(pairs, settings=_settings(tmp_path))
    assert [r.url for r in results] == urls


def test_collect_pages_batch_calls_progress_callback(tmp_path, monkeypatch):
    calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        raw_collector, "_fetch_pages_batch_with_playwright",
        _fake_batch_playwright(b"x"),
    )
    collect_pages_batch(
        [("https://example.test/a", "pa"), ("https://example.test/b", "pb")],
        settings=_settings(tmp_path),
        on_progress=lambda cur, tot, url: calls.append((cur, tot, url)),
    )
    assert calls == [
        (1, 2, "https://example.test/a"),
        (2, 2, "https://example.test/b"),
    ]


def test_batch_page_result_success_property():
    ok = BatchPageResult(
        url="u", file_path="/f", sha256="x", captured_at=datetime.now(UTC),
        content_type="text/html", bytes_written=10, fetch_method="playwright", error=None,
    )
    fail = BatchPageResult(
        url="u", file_path=None, sha256=None, captured_at=None,
        content_type=None, bytes_written=0, fetch_method=None, error="boom",
    )
    assert ok.success is True
    assert fail.success is False
