"""Discover individual instant-ticket detail URLs from the Illinois Lottery hub page.

Source relationship
-------------------
Unpaid-prizes page  (/about-the-games/unpaid-instant-games-prizes)
    -> prize-tier availability snapshots (total/unclaimed counts per prize level)

Instant-tickets hub (/games-hub/instant-tickets) + detail pages
    -> stable per-game metadata (odds, launch date, category, play style, image)

This module handles the hub page only. It returns detail URLs for a separate
collector/parser to fetch and parse individually.

Hub page structure (as of 2026-05-08):
  Cards:       <div class="simple-game-card card-container__item">
  Image link:  <a aria-label="[name]" href="/games-hub/instant-tickets/[slug]">
  Price:       <span class="simple-game-card-prize__price">
  Pagination:  <div class="itg-container__pagination">
               <span class="itg-container__pagination-range">1 - 20</span>
               <span class="itg-container__pagination-of-text">of 58</span>
               <a href="/games-hub/instant-tickets?page=1"> (next page)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.illinoislottery.com"
_TICKET_HREF_RE = re.compile(r"^/games-hub/instant-tickets/([^/?#]+)$")
_TOTAL_RE = re.compile(r"of\s+([\d,]+)", re.I)
_PRICE_RE = re.compile(r"\$\s*([\d,]+)")


@dataclass
class DiscoveredInstantTicket:
    detail_url: str
    slug: str | None = None
    display_name: str | None = None
    ticket_price: int | None = None
    top_prize_text: str | None = None
    raw_card_text: str | None = None


@dataclass
class InstantTicketHubDiscoveryResult:
    source_url: str | None
    tickets: list[DiscoveredInstantTicket]
    pagination_urls: list[str]
    current_page_label: str | None
    total_count: int | None
    warnings: list[str]


def normalize_illinois_lottery_url(href: str, *, base_url: str = BASE_URL) -> str:
    """Convert a relative Illinois Lottery path to an absolute URL."""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return base_url + (href if href.startswith("/") else "/" + href)


def _extract_slug(href: str) -> str | None:
    m = _TICKET_HREF_RE.match(href)
    return m.group(1) if m else None


def _parse_card(card: Tag, *, base_url: str) -> DiscoveredInstantTicket | None:
    link = card.find("a", href=_TICKET_HREF_RE)
    if link is None:
        return None
    href = str(link.get("href", ""))
    slug = _extract_slug(href)
    detail_url = normalize_illinois_lottery_url(href, base_url=base_url)

    aria = str(link.get("aria-label", "") or "").strip()
    # aria-label on "Find out more" links reads "[name] Find out more" — take only the first part
    display_name: str | None = None
    if aria:
        cleaned = re.sub(r"\s*find out more\s*$", "", aria, flags=re.I).strip()
        display_name = cleaned or None

    price: int | None = None
    price_el = card.find(class_="simple-game-card-prize__price")
    if price_el:
        m = _PRICE_RE.search(price_el.get_text())
        if m:
            try:
                price = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

    top_prize_text: str | None = None
    prize_text_el = card.find(class_="simple-game-card-prize__text")
    if prize_text_el:
        raw = prize_text_el.get_text(" ", strip=True)
        top_prize_text = re.sub(r"\s+", " ", raw).strip() or None

    raw_card_text = (re.sub(r"\s+", " ", card.get_text(" ", strip=True)) or None)
    if raw_card_text:
        raw_card_text = raw_card_text[:200]

    return DiscoveredInstantTicket(
        detail_url=detail_url,
        slug=slug,
        display_name=display_name,
        ticket_price=price,
        top_prize_text=top_prize_text,
        raw_card_text=raw_card_text,
    )


def _parse_pagination(
    soup: BeautifulSoup, *, base_url: str
) -> tuple[str | None, int | None, list[str]]:
    pag = soup.find(class_="itg-container__pagination")
    if pag is None:
        return None, None, []

    range_el = pag.find(class_="itg-container__pagination-range")
    page_label = range_el.get_text(strip=True) if range_el else None

    total_count: int | None = None
    of_el = pag.find(class_="itg-container__pagination-of-text")
    if of_el:
        m = _TOTAL_RE.search(of_el.get_text())
        if m:
            try:
                total_count = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

    # Pagination uses <a class="grey-icon"> for active buttons and <span class="grey-icon">
    # for disabled ones. Text content is literal "&gt;" for next and "&lt;" for prev.
    # Only collect the next-page link (the ">" anchor) to avoid treating the prev-page
    # link as a forward URL on the last page.
    pagination_urls: list[str] = []
    for a in pag.find_all("a", class_="grey-icon", href=True):
        href = str(a.get("href", ""))
        text = a.get_text(strip=True)
        if href and text == ">":
            pagination_urls.append(normalize_illinois_lottery_url(href, base_url=base_url))

    return page_label, total_count, pagination_urls


def parse_instant_ticket_hub_html(
    source: str | Path,
    *,
    source_url: str | None = None,
    base_url: str = BASE_URL,
) -> InstantTicketHubDiscoveryResult:
    """Parse ``source`` (raw HTML or Path) and return discovered ticket detail URLs.

    Does not fetch the network. Deduplicated by absolute detail URL.
    Order is preserved as rendered on the page.
    """
    html = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []

    cards = soup.find_all("div", class_="simple-game-card")
    if not cards:
        warnings.append("no simple-game-card elements found — page structure may have changed")

    seen: set[str] = set()
    tickets: list[DiscoveredInstantTicket] = []
    for card in cards:
        ticket = _parse_card(card, base_url=base_url)
        if ticket is None:
            warnings.append(
                f"card skipped — no ticket href: {card.get_text(strip=True)[:60]!r}"
            )
            continue
        if ticket.detail_url in seen:
            continue
        seen.add(ticket.detail_url)
        tickets.append(ticket)

    page_label, total_count, pagination_urls = _parse_pagination(soup, base_url=base_url)

    if not tickets:
        warnings.append("no ticket detail URLs discovered")

    return InstantTicketHubDiscoveryResult(
        source_url=source_url,
        tickets=tickets,
        pagination_urls=pagination_urls,
        current_page_label=page_label,
        total_count=total_count,
        warnings=warnings,
    )
