"""Parse the Illinois Lottery rendered unclaimed-prizes table into structured data.

This parser does not write to the database, do EV math, or fetch anything from
the network. It accepts raw HTML text or a Path to a saved HTML file and
returns a ``ParseResult`` containing parsed games, parsed prize tiers, and any
parse warnings.

Layout of the table (one ``<tr class="unclaimed-prizes-table__row">`` per game,
six ``<td class="unclaimed-prizes-table__cell">`` cells per row, in order):

  0: display name with price suffix, e.g. ``"EMERALDS ($1)"``
  1: ticket-price text, e.g. ``"$1"``
  2: game number plus weeks-in-market, e.g. ``"7647<br>(9)"``
  3: prize amounts, ``<br>``-separated, e.g. ``"$1<br>$5<br>$50,000"``
  4: total prize counts, ``<br>``-separated
  5: unclaimed prize counts, ``<br>``-separated

The three parallel lists in cells 3/4/5 are aligned by index. Length mismatches
are reported as warnings and do not abort parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ROW_SELECTOR = "tr.unclaimed-prizes-table__row"
CELL_SELECTOR = "td.unclaimed-prizes-table__cell"
EXPECTED_CELL_COUNT = 6

DISPLAY_NAME_CELL = 0
TICKET_PRICE_CELL = 1
GAME_NUMBER_CELL = 2
PRIZE_AMOUNT_CELL = 3
TOTAL_PRIZES_CELL = 4
UNCLAIMED_PRIZES_CELL = 5

_CURRENCY_RE = re.compile(r"^\s*\$?\s*([\d,]+(?:\.\d+)?)\s*$")
_INT_RE = re.compile(r"^\s*([\d,]+)\s*$")
_DISPLAY_NAME_RE = re.compile(r"^(?P<name>.+?)\s*\(\s*\$\s*([\d,]+)\s*\)\s*$")
_WEEKS_RE = re.compile(r"\(\s*(\d+)\s*\)")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ParsedPrizeTier:
    prize_amount: int | None
    total_prizes: int | None
    unclaimed_prizes: int | None


@dataclass
class ParseWarning:
    message: str
    row_index: int | None = None
    game_name: str | None = None
    raw_text: str | None = None


@dataclass
class ParsedGame:
    game_name: str | None
    display_name: str | None
    ticket_price: int | None
    data_price: int | None
    game_number: str | None
    weeks_in_market: int | None
    prize_tiers: list[ParsedPrizeTier] = field(default_factory=list)


@dataclass
class ParseResult:
    games: list[ParsedGame] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip()


def split_br_cell(cell: Tag | None) -> list[str]:
    """Return ``<br>``-separated values from ``cell`` in order, whitespace-trimmed."""
    if cell is None:
        return []
    parts: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        text = clean_text("".join(buf))
        if text:
            parts.append(text)
        buf.clear()

    for node in cell.children:
        name = getattr(node, "name", None)
        if name == "br":
            flush()
        elif name is None:
            buf.append(str(node))
        else:
            buf.append(node.get_text(" "))
    flush()
    return parts


def parse_currency_to_int(text: str) -> int | None:
    """Parse '$5', '$1,000', '$1,000,000' (or '5') into an integer dollar value."""
    if not text:
        return None
    match = _CURRENCY_RE.match(text)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_count_to_int(text: str) -> int | None:
    """Parse '1', '10', '1,000', '12,345' into int."""
    if not text:
        return None
    match = _INT_RE.match(text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_display_name(text: str) -> tuple[str | None, int | None]:
    """Split ``'EMERALDS ($1)'`` into ``('EMERALDS', 1)``."""
    cleaned = clean_text(text)
    if not cleaned:
        return None, None
    match = _DISPLAY_NAME_RE.match(cleaned)
    if not match:
        return cleaned, None
    name = match.group("name").strip() or None
    price = parse_currency_to_int("$" + match.group(2))
    return name, price


def parse_game_number_cell(cell: Tag | None) -> tuple[str | None, int | None]:
    """Pull the game number and weeks-in-market out of ``'7647<br>(9)'``-style cells."""
    parts = split_br_cell(cell)
    if not parts:
        return None, None
    game_number = parts[0] or None
    weeks: int | None = None
    for piece in parts[1:]:
        match = _WEEKS_RE.search(piece)
        if match:
            try:
                weeks = int(match.group(1))
            except ValueError:
                weeks = None
            break
    return game_number, weeks


def _parse_data_price(row: Tag) -> int | None:
    raw = row.get("data-price")
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    try:
        return int(raw_str)
    except ValueError:
        return parse_count_to_int(raw_str)


def parse_row(
    row: Tag, row_index: int, warnings: list[ParseWarning]
) -> ParsedGame | None:
    cells = row.select(CELL_SELECTOR)
    if len(cells) < EXPECTED_CELL_COUNT:
        warnings.append(
            ParseWarning(
                message=(
                    f"row has {len(cells)} cells; expected {EXPECTED_CELL_COUNT}"
                ),
                row_index=row_index,
                raw_text=clean_text(row.get_text(" ")),
            )
        )
        return None

    display_text = clean_text(cells[DISPLAY_NAME_CELL].get_text(" "))
    game_name, suffix_price = parse_display_name(display_text)

    visible_price_text = clean_text(cells[TICKET_PRICE_CELL].get_text(" "))
    visible_price = parse_currency_to_int(visible_price_text) if visible_price_text else None

    data_price = _parse_data_price(row)

    ticket_price = visible_price
    if ticket_price is None:
        ticket_price = data_price
    if ticket_price is None:
        ticket_price = suffix_price
    if ticket_price is None:
        warnings.append(
            ParseWarning(
                message="could not determine ticket price",
                row_index=row_index,
                game_name=game_name,
                raw_text=display_text,
            )
        )

    game_number, weeks_in_market = parse_game_number_cell(cells[GAME_NUMBER_CELL])
    if game_number is None:
        warnings.append(
            ParseWarning(
                message="game number missing or unparseable",
                row_index=row_index,
                game_name=game_name,
                raw_text=clean_text(cells[GAME_NUMBER_CELL].get_text(" ")),
            )
        )

    amount_strs = split_br_cell(cells[PRIZE_AMOUNT_CELL])
    total_strs = split_br_cell(cells[TOTAL_PRIZES_CELL])
    unclaimed_strs = split_br_cell(cells[UNCLAIMED_PRIZES_CELL])

    if not (len(amount_strs) == len(total_strs) == len(unclaimed_strs)):
        warnings.append(
            ParseWarning(
                message=(
                    "prize tier list length mismatch: "
                    f"amounts={len(amount_strs)} totals={len(total_strs)} "
                    f"unclaimed={len(unclaimed_strs)}"
                ),
                row_index=row_index,
                game_name=game_name,
                raw_text=display_text,
            )
        )

    aligned = min(len(amount_strs), len(total_strs), len(unclaimed_strs))
    tiers: list[ParsedPrizeTier] = []
    for i in range(aligned):
        amount = parse_currency_to_int(amount_strs[i])
        total = parse_count_to_int(total_strs[i])
        unclaimed = parse_count_to_int(unclaimed_strs[i])

        if amount is None:
            warnings.append(
                ParseWarning(
                    message=f"could not parse prize amount {amount_strs[i]!r}",
                    row_index=row_index,
                    game_name=game_name,
                    raw_text=amount_strs[i],
                )
            )
        if total is None:
            warnings.append(
                ParseWarning(
                    message=f"could not parse total count {total_strs[i]!r}",
                    row_index=row_index,
                    game_name=game_name,
                    raw_text=total_strs[i],
                )
            )
        if unclaimed is None:
            warnings.append(
                ParseWarning(
                    message=f"could not parse unclaimed count {unclaimed_strs[i]!r}",
                    row_index=row_index,
                    game_name=game_name,
                    raw_text=unclaimed_strs[i],
                )
            )

        tiers.append(
            ParsedPrizeTier(
                prize_amount=amount,
                total_prizes=total,
                unclaimed_prizes=unclaimed,
            )
        )

    return ParsedGame(
        game_name=game_name,
        display_name=display_text or None,
        ticket_price=ticket_price,
        data_price=data_price,
        game_number=game_number,
        weeks_in_market=weeks_in_market,
        prize_tiers=tiers,
    )


def _read_html(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    return source


def parse_html(source: str | Path) -> ParseResult:
    """Parse ``source`` (raw HTML or a ``Path`` to an HTML file) into a ``ParseResult``."""
    html = _read_html(source)
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(ROW_SELECTOR)

    warnings: list[ParseWarning] = []
    games: list[ParsedGame] = []
    for idx, row in enumerate(rows):
        parsed = parse_row(row, idx, warnings)
        if parsed is not None:
            games.append(parsed)
    return ParseResult(games=games, warnings=warnings)
