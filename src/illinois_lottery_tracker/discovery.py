"""Pure helpers and dataclasses used by the source-discovery diagnostic.

These are split out of ``scripts/discover_source.py`` so they can be unit-tested
without a Playwright browser. Nothing in this module imports playwright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Price-filter labels we expect on the page, in display order.
FILTER_LABELS: tuple[str, ...] = (
    "All games",
    "$1 Games",
    "$2 Games",
    "$3 Games",
    "$5 Games",
    "$10 Games",
    "$20+ Games",
)

# URL keywords that suggest a useful network response.
RELEVANT_URL_KEYWORDS: tuple[str, ...] = (
    "api",
    "prize",
    "instant",
    "game",
    "unclaimed",
    "ticket",
    ".json",
)

# Content types we treat as data-bearing.
DATA_CONTENT_TYPES: tuple[str, ...] = ("application/json", "text/json", "+json")

PAGINATION_TEXT_TOKENS: frozenset[str] = frozenset(
    {
        "next",
        "previous",
        "prev",
        "load more",
        "show more",
        "more",
        "»",
        "«",
        "›",
        "‹",
        "→",
        "←",
    }
)

_NUMERIC_PAGE_RE = re.compile(r"^\d{1,3}$")
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class FilterResult:
    label: str
    discovered: bool = False
    pages_seen: int = 0
    rows_per_page: list[int] = field(default_factory=list)
    has_pagination: bool = False
    pagination_kind: str = "unknown"
    pre_url: str | None = None
    post_urls: list[str] = field(default_factory=list)
    saved_html_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(self.rows_per_page)


@dataclass
class DiscoveryReport:
    page_title: str = ""
    final_url: str = ""
    detected_filters: list[str] = field(default_factory=list)
    filters: list[FilterResult] = field(default_factory=list)
    relevant_network_urls: list[str] = field(default_factory=list)
    json_responses_saved: list[str] = field(default_factory=list)
    obvious_json_api: bool = False
    fully_collectable_via_api: bool = False
    notes: list[str] = field(default_factory=list)


def url_or_content_type_is_relevant(url: str, content_type: str | None) -> bool:
    """True if a network response looks like data we'd care about for the parser."""
    url_l = url.lower()
    if any(kw in url_l for kw in RELEVANT_URL_KEYWORDS):
        return True
    ct = (content_type or "").lower()
    return any(t in ct for t in DATA_CONTENT_TYPES)


def looks_like_pagination_text(text: str) -> bool:
    """True if the visible text on a control suggests pagination (Next/Prev/N/etc)."""
    text_l = text.strip().lower()
    if not text_l:
        return False
    if text_l in PAGINATION_TEXT_TOKENS:
        return True
    return bool(_NUMERIC_PAGE_RE.match(text_l))


def safe_filename_from_url(url: str, idx: int) -> str:
    """Build a filesystem-safe filename for a saved network response."""
    parsed = urlparse(url)
    raw = parsed.path or "/"
    if parsed.query:
        raw += "?" + parsed.query
    cleaned = _FILENAME_SAFE_RE.sub("_", raw).strip("_") or "root"
    return f"{idx:03d}-{cleaned[:120]}"


def classify_navigation(before: str, after: str) -> str:
    """Classify a URL transition as url-based, hash-based, or client-side."""
    if before == after:
        return "client-side"
    bp = urlparse(before)
    ap = urlparse(after)
    structural_before = (bp.scheme, bp.netloc, bp.path, bp.query)
    structural_after = (ap.scheme, ap.netloc, ap.path, ap.query)
    if structural_before != structural_after:
        return "url-based"
    if bp.fragment != ap.fragment:
        return "hash-based"
    return "url-based"
