"""Parse an individual Illinois Lottery instant-ticket detail page into structured metadata.

Source relationship
-------------------
Unpaid-prizes page  (/about-the-games/unpaid-instant-games-prizes)
    -> prize-tier availability snapshots (total/unclaimed counts per prize level)

Instant-ticket detail pages (/games-hub/instant-tickets/<slug>)
    -> stable per-game metadata: odds, launch date, category, play style, game number

This parser does not write to the database and does not fetch the network.
A later import step can upsert the returned ``ParsedInstantTicketDetail`` into
the ``games`` table.

Detail page structure (as of 2026-05-08):
  Game title:  <h1 class="cmp-title__text"> (fallback: <title> tag, stripped of site suffix)
  Metadata:    <div class="itg-details-block"> / <table> / <tr><td>label</td><td>value</td></tr>
               Fields: Price Point, Overall Odds, Category, Play Style, Launch Date, Game Number
  Cons. odds:  <h3>Consolidated Odds</h3>

  Overall Odds formats observed on the site:
    "1 in 3.85"  — probability form; denominator stored as-is
    "4.80 to 1"  — ratio form; leading number is the same denominator (1 in 4.80)

Notes on est_total_tickets
--------------------------
Do not compute estimated_ticket_count inside this parser. The detail page only
knows overall_odds. The total original winning-ticket count comes from the
unpaid-prizes parser. A later metrics step combines:

    est_total_tickets = round(overall_odds_one_in * sum(total_prizes_across_all_tiers))
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup

_ODDS_ONE_IN_RE = re.compile(r"1\s+in\s+([\d,.]+)", re.I)
_ODDS_X_TO_ONE_RE = re.compile(r"([\d,.]+)\s+to\s+1\b", re.I)
_PRICE_RE = re.compile(r"\$\s*([\d,]+)")
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d")
_TITLE_SUFFIX_RE = re.compile(r"\s*\|.*$")


@dataclass
class ParsedInstantTicketDetail:
    source_url: str | None
    detail_slug: str | None
    game_name: str | None
    display_name: str | None
    game_number: str | None
    ticket_price: int | None
    overall_odds: Decimal | None
    overall_odds_text: str | None
    category: str | None
    play_style: str | None
    launch_date: date | None
    top_prize_text: str | None
    image_url: str | None
    play_instructions: str | None
    consolidated_odds_present: bool
    raw_fields: dict[str, str]
    warnings: list[str]


def parse_odds_text(text: str) -> Decimal | None:
    """Parse overall odds text into the ``1-in-X`` denominator as a Decimal.

    Handles both formats observed on the Illinois Lottery site:
      ``"1 in 3.85"``  → ``Decimal("3.85")``
      ``"4.80 to 1"``  → ``Decimal("4.80")``  (X is the denominator; both mean 1-in-X)
    """
    if not text:
        return None
    m = _ODDS_ONE_IN_RE.search(text)
    if m:
        try:
            return Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return None
    m = _ODDS_X_TO_ONE_RE.search(text)
    if m:
        try:
            return Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return None
    return None


def parse_price_point(text: str) -> int | None:
    """Parse ``'$3'`` or ``'3'`` -> ``3``."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def parse_launch_date(text: str) -> date | None:
    """Parse ``'May 5, 2026'`` -> ``date(2026, 5, 5)``."""
    if not text:
        return None
    stripped = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).date()
        except ValueError:
            continue
    return None


def _slug_from_url(url: str) -> str | None:
    if not url:
        return None
    return url.rstrip("/").split("/")[-1] or None


def parse_instant_ticket_detail_html(
    source: str | Path,
    *,
    source_url: str | None = None,
) -> ParsedInstantTicketDetail:
    """Parse ``source`` (raw HTML or Path) and return structured game metadata.

    Does not fetch the network. Does not write to the database.
    Missing optional fields return ``None``; a warning is added for fields
    that are expected but absent.
    """
    html = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []

    h1 = soup.find("h1", class_="cmp-title__text")
    game_name: str | None = h1.get_text(strip=True) if h1 else None
    if game_name is None:
        # Fall back to <title> tag, stripping the " | Instant Ticket | Illinois Lottery" suffix.
        title_el = soup.find("title")
        if title_el:
            game_name = _TITLE_SUFFIX_RE.sub("", title_el.get_text(strip=True)).strip() or None
    if game_name is None:
        warnings.append("game name not found: no <h1 class='cmp-title__text'> or <title>")

    raw_fields: dict[str, str] = {}
    details_block = soup.find(class_="itg-details-block")
    if details_block is None:
        warnings.append("details block not found: no element with class 'itg-details-block'")
    else:
        for tr in details_block.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                label = tds[0].get_text(strip=True)
                value = tds[1].get_text(strip=True)
                if label:
                    raw_fields[label] = value

    game_number = raw_fields.get("Game Number") or None

    price_text = raw_fields.get("Price Point", "")
    ticket_price = parse_price_point(price_text)
    if ticket_price is None and price_text:
        warnings.append(f"could not parse Price Point: {price_text!r}")

    odds_text = raw_fields.get("Overall Odds", "")
    overall_odds = parse_odds_text(odds_text)
    overall_odds_text = odds_text or None
    if overall_odds is None and odds_text:
        warnings.append(f"could not parse Overall Odds: {odds_text!r}")

    launch_date_text = raw_fields.get("Launch Date", "")
    launch_date = parse_launch_date(launch_date_text)
    if launch_date is None and launch_date_text:
        warnings.append(f"could not parse Launch Date: {launch_date_text!r}")

    consolidated_odds_present = bool(
        soup.find(lambda tag: tag.name == "h3" and "consolidated odds" in tag.get_text().lower())
    )

    return ParsedInstantTicketDetail(
        source_url=source_url,
        detail_slug=_slug_from_url(source_url) if source_url else None,
        game_name=game_name,
        display_name=game_name,
        game_number=game_number,
        ticket_price=ticket_price,
        overall_odds=overall_odds,
        overall_odds_text=overall_odds_text,
        category=raw_fields.get("Category") or None,
        play_style=raw_fields.get("Play Style") or None,
        launch_date=launch_date,
        top_prize_text=raw_fields.get("Top Prize") or raw_fields.get("Win Up To") or None,
        image_url=None,
        play_instructions=None,
        consolidated_odds_present=consolidated_odds_present,
        raw_fields=raw_fields,
        warnings=warnings,
    )
