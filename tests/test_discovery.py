"""Tests for illinois_lottery_tracker.discovery (pure helpers only).

No Playwright is launched here; orchestration in scripts/discover_source.py
is intentionally not unit-tested because it depends on a live browser.
"""

from __future__ import annotations

from illinois_lottery_tracker.discovery import (
    FILTER_LABELS,
    DiscoveryReport,
    FilterResult,
    classify_navigation,
    looks_like_pagination_text,
    safe_filename_from_url,
    url_or_content_type_is_relevant,
)


def test_filter_labels_are_in_expected_order():
    assert FILTER_LABELS == (
        "All games",
        "$1 Games",
        "$2 Games",
        "$3 Games",
        "$5 Games",
        "$10 Games",
        "$20+ Games",
    )


def test_url_or_content_type_is_relevant_url_keywords():
    assert url_or_content_type_is_relevant("https://example.com/api/prizes", None)
    assert url_or_content_type_is_relevant("https://example.com/data.json", None)
    assert url_or_content_type_is_relevant(
        "https://example.com/instant-games", "text/html"
    )


def test_url_or_content_type_is_relevant_by_content_type():
    assert url_or_content_type_is_relevant(
        "https://example.com/x", "application/json; charset=utf-8"
    )
    assert url_or_content_type_is_relevant(
        "https://example.com/x", "application/vnd.api+json"
    )


def test_url_or_content_type_is_relevant_negative_cases():
    assert not url_or_content_type_is_relevant("https://example.com/style.css", "text/css")
    assert not url_or_content_type_is_relevant(
        "https://example.com/logo.png", "image/png"
    )
    assert not url_or_content_type_is_relevant("https://example.com/", None)


def test_looks_like_pagination_text_positive_cases():
    assert looks_like_pagination_text("Next")
    assert looks_like_pagination_text(" previous ")
    assert looks_like_pagination_text("Load More")
    assert looks_like_pagination_text("Show more")
    assert looks_like_pagination_text("3")
    assert looks_like_pagination_text("17")
    assert looks_like_pagination_text("»")
    assert looks_like_pagination_text("→")


def test_looks_like_pagination_text_negative_cases():
    assert not looks_like_pagination_text("")
    assert not looks_like_pagination_text("Buy now")
    assert not looks_like_pagination_text("Filter")
    assert not looks_like_pagination_text("12345")  # too long to be a page number


def test_safe_filename_from_url_strips_special_chars():
    name = safe_filename_from_url("https://example.com/api/games?id=42&page=1", 7)
    assert name.startswith("007-")
    assert "/" not in name
    assert "?" not in name
    assert "&" not in name
    assert "=" not in name


def test_safe_filename_from_url_handles_empty_path():
    name = safe_filename_from_url("https://example.com", 0)
    assert name.startswith("000-")
    # Either "_" (from "/") or "root" — both are filesystem-safe.
    assert all(c.isalnum() or c in "-_." for c in name)


def test_safe_filename_from_url_truncates_long_urls():
    long_query = "a=" + "x" * 500
    name = safe_filename_from_url(f"https://example.com/p?{long_query}", 1)
    # idx prefix (4) + at most 120 chars of cleaned path/query
    assert len(name) <= 4 + 120


def test_classify_navigation_no_change():
    assert classify_navigation(
        "https://example.com/page", "https://example.com/page"
    ) == "client-side"


def test_classify_navigation_query_change():
    assert (
        classify_navigation(
            "https://example.com/page",
            "https://example.com/page?filter=5",
        )
        == "url-based"
    )


def test_classify_navigation_path_change():
    assert (
        classify_navigation(
            "https://example.com/page",
            "https://example.com/page/2",
        )
        == "url-based"
    )


def test_classify_navigation_hash_only():
    assert (
        classify_navigation(
            "https://example.com/page",
            "https://example.com/page#section",
        )
        == "hash-based"
    )


def test_filter_result_total_rows_sums_pages():
    fr = FilterResult(label="$5 Games", rows_per_page=[10, 10, 4])
    assert fr.total_rows == 24


def test_discovery_report_defaults_are_empty():
    report = DiscoveryReport()
    assert report.detected_filters == []
    assert report.filters == []
    assert report.relevant_network_urls == []
    assert report.obvious_json_api is False
    assert report.fully_collectable_via_api is False
