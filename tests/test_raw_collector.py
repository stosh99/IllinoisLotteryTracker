"""Tests for illinois_lottery_tracker.raw_collector.

These tests never hit the live Illinois Lottery site. The HTTP layer is
replaced with a fake ``requests.Session``; the Playwright fallback is
monkeypatched so no browser is launched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from illinois_lottery_tracker import raw_collector
from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.raw_collector import (
    _browser_headers,
    _FetchOutcome,
    _is_forbidden,
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

    def fake_playwright(url, *, user_agent, timeout_ms):
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
