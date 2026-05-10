"""Tests for the individual instant-ticket detail-page parser."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from illinois_lottery_tracker.instant_ticket_detail_parser import (
    ParsedInstantTicketDetail,
    parse_instant_ticket_detail_html,
    parse_launch_date,
    parse_odds_text,
    parse_price_point,
)

FIXTURE = Path(__file__).parent / "fixtures" / "instant_ticket_detail_loteria_2026.html"
SOURCE_URL = "https://www.illinoislottery.com/games-hub/instant-tickets/loteria-2026"


# ---------------------------------------------------------------------------
# Helper parsers
# ---------------------------------------------------------------------------

def test_parse_odds_text_standard():
    assert parse_odds_text("1 in 3.85") == Decimal("3.85")


def test_parse_odds_text_integer():
    assert parse_odds_text("1 in 4") == Decimal("4")


def test_parse_odds_text_whitespace():
    assert parse_odds_text("  1  in  3.85  ") == Decimal("3.85")


def test_parse_odds_text_empty():
    assert parse_odds_text("") is None


def test_parse_odds_text_no_match():
    assert parse_odds_text("Overall odds vary") is None


def test_parse_price_point_dollar():
    assert parse_price_point("$3") == 3


def test_parse_price_point_plain_int():
    assert parse_price_point("10") == 10


def test_parse_price_point_empty():
    assert parse_price_point("") is None


def test_parse_price_point_non_numeric():
    assert parse_price_point("free") is None


def test_parse_launch_date_long_form():
    assert parse_launch_date("May 5, 2026") == date(2026, 5, 5)


def test_parse_launch_date_abbrev():
    assert parse_launch_date("Jan 1, 2025") == date(2025, 1, 1)


def test_parse_launch_date_iso():
    assert parse_launch_date("2026-05-05") == date(2026, 5, 5)


def test_parse_launch_date_empty():
    assert parse_launch_date("") is None


def test_parse_launch_date_garbage():
    assert parse_launch_date("not a date") is None


# ---------------------------------------------------------------------------
# Full parse from fixture — Path input
# ---------------------------------------------------------------------------

def test_parse_detail_returns_result_type():
    result = parse_instant_ticket_detail_html(FIXTURE, source_url=SOURCE_URL)
    assert isinstance(result, ParsedInstantTicketDetail)


def test_parse_detail_game_name():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.game_name == "Loteria™"


def test_parse_detail_game_number_is_string():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.game_number == "7651"
    assert isinstance(result.game_number, str)


def test_parse_detail_ticket_price_is_int():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.ticket_price == 3
    assert isinstance(result.ticket_price, int)


def test_parse_detail_overall_odds():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.overall_odds == Decimal("3.85")


def test_parse_detail_overall_odds_text_preserved():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.overall_odds_text == "1 in 3.85"


def test_parse_detail_launch_date():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.launch_date == date(2026, 5, 5)


def test_parse_detail_category():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.category == "LP"


def test_parse_detail_play_style():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.play_style == "Loteria"


def test_parse_detail_consolidated_odds_present():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.consolidated_odds_present is True


def test_parse_detail_slug_from_source_url():
    result = parse_instant_ticket_detail_html(FIXTURE, source_url=SOURCE_URL)
    assert result.detail_slug == "loteria-2026"


def test_parse_detail_source_url_preserved():
    result = parse_instant_ticket_detail_html(FIXTURE, source_url=SOURCE_URL)
    assert result.source_url == SOURCE_URL


def test_parse_detail_raw_fields_populated():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert "Game Number" in result.raw_fields
    assert "Overall Odds" in result.raw_fields
    assert "Launch Date" in result.raw_fields


def test_parse_detail_no_warnings_on_valid_fixture():
    result = parse_instant_ticket_detail_html(FIXTURE)
    assert result.warnings == []


def test_parse_detail_accepts_string_input():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_instant_ticket_detail_html(html)
    assert result.game_name == "Loteria™"


# ---------------------------------------------------------------------------
# Negative / missing-field cases
# ---------------------------------------------------------------------------

MINIMAL_HTML = """
<html><body>
<div class="itg-details-block">
  <table><tr><td>Game Number</td><td>9999</td></tr></table>
</div>
</body></html>
"""


def test_parse_detail_missing_h1_adds_warning():
    result = parse_instant_ticket_detail_html(MINIMAL_HTML)
    assert result.game_name is None
    assert any("game name" in w.lower() for w in result.warnings)


def test_parse_detail_missing_details_block_adds_warning():
    html = "<html><body><h1 class='cmp-title__text'>Foo</h1></body></html>"
    result = parse_instant_ticket_detail_html(html)
    assert any("details block" in w.lower() for w in result.warnings)


def test_parse_detail_missing_odds_returns_none():
    result = parse_instant_ticket_detail_html(MINIMAL_HTML)
    assert result.overall_odds is None
    assert result.overall_odds_text is None


def test_parse_detail_no_consolidated_odds_section():
    result = parse_instant_ticket_detail_html(MINIMAL_HTML)
    assert result.consolidated_odds_present is False


def test_parse_detail_missing_launch_date_returns_none():
    result = parse_instant_ticket_detail_html(MINIMAL_HTML)
    assert result.launch_date is None


# ---------------------------------------------------------------------------
# "X to 1" odds format
# ---------------------------------------------------------------------------

def test_parse_odds_text_x_to_one():
    assert parse_odds_text("4.80 to 1") == Decimal("4.80")


def test_parse_odds_text_x_to_one_integer():
    assert parse_odds_text("5 to 1") == Decimal("5")


def test_parse_odds_text_x_to_one_with_whitespace():
    assert parse_odds_text("  4.80  to  1  ") == Decimal("4.80")


def test_parse_odds_text_x_to_one_in_html_table():
    html = """
<html><body>
<h1 class="cmp-title__text">10X the Cash</h1>
<div class="itg-details-block">
  <table>
    <tr><td>Overall Odds</td><td>4.80 to 1</td></tr>
    <tr><td>Game Number</td><td>1234</td></tr>
    <tr><td>Price Point</td><td>$5</td></tr>
    <tr><td>Launch Date</td><td>January 1, 2026</td></tr>
  </table>
</div>
</body></html>
"""
    result = parse_instant_ticket_detail_html(html)
    assert result.overall_odds == Decimal("4.80")
    assert result.overall_odds_text == "4.80 to 1"
    assert result.warnings == []


# ---------------------------------------------------------------------------
# <title> fallback for game name
# ---------------------------------------------------------------------------

def test_parse_detail_title_fallback_when_no_h1():
    html = """
<html><head><title>10X the Cash | Instant Ticket | Illinois Lottery</title></head>
<body>
<div class="itg-details-block">
  <table><tr><td>Game Number</td><td>9876</td></tr></table>
</div>
</body></html>
"""
    result = parse_instant_ticket_detail_html(html)
    assert result.game_name == "10X the Cash"
    assert result.warnings == []


def test_parse_detail_title_fallback_strips_suffix():
    html = """
<html><head><title>Lucky 7s | Instant Ticket | Illinois Lottery</title></head>
<body>
<div class="itg-details-block">
  <table><tr><td>Game Number</td><td>1111</td></tr></table>
</div>
</body></html>
"""
    result = parse_instant_ticket_detail_html(html)
    assert result.game_name == "Lucky 7s"


def test_parse_detail_warning_only_when_no_title_either():
    html = """
<html><body>
<div class="itg-details-block">
  <table><tr><td>Game Number</td><td>9999</td></tr></table>
</div>
</body></html>
"""
    result = parse_instant_ticket_detail_html(html)
    assert result.game_name is None
    assert any("game name" in w.lower() for w in result.warnings)
