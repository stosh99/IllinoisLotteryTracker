"""Tests for the instant-ticket hub discovery parser."""

from pathlib import Path

from illinois_lottery_tracker.instant_ticket_discovery import (
    InstantTicketHubDiscoveryResult,
    normalize_illinois_lottery_url,
    parse_instant_ticket_hub_html,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "instant_tickets_hub_page_1.html"
FIXTURE_P2 = FIXTURES / "instant_tickets_hub_page_2.html"
FIXTURE_P3 = FIXTURES / "instant_tickets_hub_page_3.html"
BASE = "https://www.illinoislottery.com"


# ---------------------------------------------------------------------------
# normalize_illinois_lottery_url
# ---------------------------------------------------------------------------

def test_normalize_relative_path():
    assert normalize_illinois_lottery_url("/games-hub/instant-tickets/foo") == (
        BASE + "/games-hub/instant-tickets/foo"
    )


def test_normalize_absolute_url_unchanged():
    url = "https://www.illinoislottery.com/games-hub/instant-tickets/foo"
    assert normalize_illinois_lottery_url(url) == url


def test_normalize_path_without_leading_slash():
    result = normalize_illinois_lottery_url("games-hub/instant-tickets/foo")
    assert result == BASE + "/games-hub/instant-tickets/foo"


# ---------------------------------------------------------------------------
# parse_instant_ticket_hub_html — from fixture file (Path input)
# ---------------------------------------------------------------------------

def test_parse_hub_returns_result_type():
    result = parse_instant_ticket_hub_html(FIXTURE, source_url=BASE + "/games-hub/instant-tickets")
    assert isinstance(result, InstantTicketHubDiscoveryResult)


def test_parse_hub_discovers_ticket_urls():
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert len(result.tickets) >= 1
    for t in result.tickets:
        assert t.detail_url.startswith(BASE + "/games-hub/instant-tickets/")


def test_parse_hub_deduplicates():
    # Fixture has loteria-2026 twice; should appear only once
    result = parse_instant_ticket_hub_html(FIXTURE)
    urls = [t.detail_url for t in result.tickets]
    assert len(urls) == len(set(urls)), "duplicate detail URLs were not removed"


def test_parse_hub_expected_slugs():
    result = parse_instant_ticket_hub_html(FIXTURE)
    slugs = {t.slug for t in result.tickets}
    assert "loteria-2026" in slugs
    assert "money-match-2026" in slugs


def test_parse_hub_preserves_order():
    result = parse_instant_ticket_hub_html(FIXTURE)
    slugs = [t.slug for t in result.tickets]
    assert slugs.index("loteria-2026") < slugs.index("money-match-2026")


def test_parse_hub_extracts_display_name():
    result = parse_instant_ticket_hub_html(FIXTURE)
    loteria = next(t for t in result.tickets if t.slug == "loteria-2026")
    assert loteria.display_name == "Loteria™"


def test_parse_hub_extracts_ticket_price():
    result = parse_instant_ticket_hub_html(FIXTURE)
    loteria = next(t for t in result.tickets if t.slug == "loteria-2026")
    assert loteria.ticket_price == 3
    money = next(t for t in result.tickets if t.slug == "money-match-2026")
    assert money.ticket_price == 5


def test_parse_hub_extracts_top_prize_text():
    result = parse_instant_ticket_hub_html(FIXTURE)
    loteria = next(t for t in result.tickets if t.slug == "loteria-2026")
    assert loteria.top_prize_text is not None
    assert "80,000" in loteria.top_prize_text or "80000" in loteria.top_prize_text


def test_parse_hub_pagination_total_count():
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert result.total_count == 58


def test_parse_hub_pagination_page_label():
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert result.current_page_label == "1 - 20"


def test_parse_hub_pagination_next_url():
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert len(result.pagination_urls) == 1
    assert result.pagination_urls[0] == BASE + "/games-hub/instant-tickets?page=1"


def test_parse_hub_source_url_preserved():
    source = BASE + "/games-hub/instant-tickets"
    result = parse_instant_ticket_hub_html(FIXTURE, source_url=source)
    assert result.source_url == source


def test_parse_hub_no_warnings_on_valid_fixture():
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert result.warnings == []


def test_parse_hub_accepts_string_input():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_instant_ticket_hub_html(html)
    assert len(result.tickets) >= 1


# ---------------------------------------------------------------------------
# Negative / missing-field cases
# ---------------------------------------------------------------------------

def test_parse_hub_empty_page_has_warning():
    result = parse_instant_ticket_hub_html("<html><body></body></html>")
    assert result.tickets == []
    assert any("simple-game-card" in w or "no ticket" in w for w in result.warnings)


def test_parse_hub_ignores_non_ticket_footer_links():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_instant_ticket_hub_html(html)
    # Footer links like /about or /store-locator must not appear
    for t in result.tickets:
        assert "/games-hub/instant-tickets/" in t.detail_url


# ---------------------------------------------------------------------------
# Pagination: three states — first / middle / last page
# ---------------------------------------------------------------------------

def test_pagination_first_page_has_next_only():
    # Page 1: < is a disabled span, > is an active link
    result = parse_instant_ticket_hub_html(FIXTURE)
    assert len(result.pagination_urls) == 1
    assert result.pagination_urls[0] == BASE + "/games-hub/instant-tickets?page=1"


def test_pagination_middle_page_has_next_only():
    # Page 2: both < and > are active links; only > should be returned
    result = parse_instant_ticket_hub_html(FIXTURE_P2)
    assert len(result.pagination_urls) == 1
    assert result.pagination_urls[0] == BASE + "/games-hub/instant-tickets?page=2"


def test_pagination_last_page_has_no_next():
    # Page 3: < is active (prev), > is a disabled span — no next URL
    result = parse_instant_ticket_hub_html(FIXTURE_P3)
    assert result.pagination_urls == []


def test_pagination_last_page_does_not_include_prev_url():
    # Regression: prev link (?page=1) on last page must not be returned as next
    result = parse_instant_ticket_hub_html(FIXTURE_P3)
    for url in result.pagination_urls:
        assert "page=1" not in url or "page=2" in url  # no backward link


def test_pagination_middle_page_label():
    result = parse_instant_ticket_hub_html(FIXTURE_P2)
    assert result.current_page_label == "21 - 40"


def test_pagination_last_page_label():
    result = parse_instant_ticket_hub_html(FIXTURE_P3)
    assert result.current_page_label == "41 - 58"


def test_pagination_total_count_consistent_across_pages():
    for fixture in (FIXTURE, FIXTURE_P2, FIXTURE_P3):
        result = parse_instant_ticket_hub_html(fixture)
        assert result.total_count == 58


def test_pagination_middle_page_tickets():
    result = parse_instant_ticket_hub_html(FIXTURE_P2)
    slugs = {t.slug for t in result.tickets}
    assert "monopoly" in slugs
    assert "royal-riches" in slugs


def test_pagination_last_page_tickets():
    result = parse_instant_ticket_hub_html(FIXTURE_P3)
    slugs = {t.slug for t in result.tickets}
    assert "millionaire-club-2025" in slugs


def test_full_pagination_walk_yields_all_unique_slugs():
    # Simulate the CLI walk across all three fixture pages without network access.
    # Each page returns its own next URL; the caller is responsible for the
    # visited-set guard, but the parser itself must return correct next URLs.
    seen: set[str] = set()
    for fixture in (FIXTURE, FIXTURE_P2, FIXTURE_P3):
        result = parse_instant_ticket_hub_html(fixture)
        for t in result.tickets:
            seen.add(t.slug)
    # All fixture slugs should be present and unique
    assert "loteria-2026" in seen
    assert "monopoly" in seen
    assert "millionaire-club-2025" in seen
    assert len(seen) == len({t.slug for f in (FIXTURE, FIXTURE_P2, FIXTURE_P3)
                             for t in parse_instant_ticket_hub_html(f).tickets})
