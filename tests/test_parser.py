"""Tests for illinois_lottery_tracker.parser. No network, no live database."""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from illinois_lottery_tracker.parser import (
    ParsedPrizeTier,
    ParseResult,
    parse_count_to_int,
    parse_currency_to_int,
    parse_display_name,
    parse_game_number_cell,
    parse_html,
    split_br_cell,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_prizes.html"


def _row(
    cells: list[str],
    *,
    data_price: str = "1",
    classes: str = "unclaimed-prizes-table__row",
    style: str = "display: table-row;",
) -> str:
    rendered = "".join(
        f'<td class="unclaimed-prizes-table__cell">{c}</td>' for c in cells
    )
    return (
        f'<tr data-price="{data_price}" class="{classes}" style="{style}">'
        f"{rendered}</tr>"
    )


def _wrap(rows_html: str) -> str:
    return f"<html><body><table>{rows_html}</table></body></html>"


def _td(html: str):
    return BeautifulSoup(html, "lxml").td


# ---- helper unit tests --------------------------------------------------


def test_parse_currency_to_int_basic():
    assert parse_currency_to_int("$5") == 5
    assert parse_currency_to_int("$10") == 10
    assert parse_currency_to_int("5") == 5


def test_parse_currency_to_int_with_commas():
    assert parse_currency_to_int("$1,000") == 1_000
    assert parse_currency_to_int("$1,000,000") == 1_000_000
    assert parse_currency_to_int("$50,000") == 50_000


def test_parse_currency_to_int_decimals_truncate_to_int():
    assert parse_currency_to_int("$5.50") == 5


def test_parse_currency_to_int_unparseable():
    assert parse_currency_to_int("") is None
    assert parse_currency_to_int("garbage") is None
    assert parse_currency_to_int("$not money") is None


def test_parse_count_to_int_with_commas():
    assert parse_count_to_int("1") == 1
    assert parse_count_to_int("10") == 10
    assert parse_count_to_int("1,000") == 1_000
    assert parse_count_to_int("12,345") == 12_345


def test_parse_count_to_int_unparseable():
    assert parse_count_to_int("") is None
    assert parse_count_to_int("foo") is None


def test_split_br_cell_handles_extra_whitespace():
    td = _td("<td>$1<br>  $2  <br>\n$3\n</td>")
    assert split_br_cell(td) == ["$1", "$2", "$3"]


def test_split_br_cell_handles_indented_html_like_real_page():
    td = _td(
        "<td>\n  $1\n  <br>$2\n  <br>$5\n  <br>$50,000\n</td>"
    )
    assert split_br_cell(td) == ["$1", "$2", "$5", "$50,000"]


def test_parse_display_name_with_price_suffix():
    assert parse_display_name("EMERALDS ($1)") == ("EMERALDS", 1)


def test_parse_display_name_with_comma_price():
    assert parse_display_name("BIG MONEY ($1,000)") == ("BIG MONEY", 1_000)


def test_parse_display_name_without_suffix_returns_text_only():
    name, price = parse_display_name("MISSING SUFFIX")
    assert name == "MISSING SUFFIX"
    assert price is None


def test_parse_display_name_handles_internal_parens():
    name, price = parse_display_name("HOLIDAY GAME (LIMITED) ($5)")
    assert name == "HOLIDAY GAME (LIMITED)"
    assert price == 5


def test_parse_game_number_cell_with_weeks():
    td = _td("<td>7647<br>(9)</td>")
    assert parse_game_number_cell(td) == ("7647", 9)


def test_parse_game_number_cell_without_weeks():
    td = _td("<td>7647</td>")
    assert parse_game_number_cell(td) == ("7647", None)


# ---- parse_html integration --------------------------------------------


def test_parse_html_single_normal_row():
    html = _wrap(
        _row(
            [
                "EMERALDS ($1)",
                "$1",
                "7647<br>(9)",
                "$1<br>$5<br>$50,000",
                "100<br>50<br>2",
                "75<br>30<br>1",
            ]
        )
    )

    result = parse_html(html)

    assert result.warnings == []
    assert len(result.games) == 1
    g = result.games[0]
    assert g.game_name == "EMERALDS"
    assert g.display_name == "EMERALDS ($1)"
    assert g.ticket_price == 1
    assert g.data_price == 1
    assert g.game_number == "7647"
    assert g.weeks_in_market == 9
    assert g.prize_tiers == [
        ParsedPrizeTier(prize_amount=1, total_prizes=100, unclaimed_prizes=75),
        ParsedPrizeTier(prize_amount=5, total_prizes=50, unclaimed_prizes=30),
        ParsedPrizeTier(prize_amount=50_000, total_prizes=2, unclaimed_prizes=1),
    ]


def test_parse_html_multiple_tiers_with_commas():
    html = _wrap(
        _row(
            [
                "MEGA WIN ($5)",
                "$5",
                "1234<br>(3)",
                "$1<br>$1,000<br>$1,000,000",
                "10,000<br>1,000<br>1",
                "9,999<br>900<br>1",
            ],
            data_price="5",
        )
    )

    result = parse_html(html)

    assert result.warnings == []
    g = result.games[0]
    assert g.ticket_price == 5
    assert [t.prize_amount for t in g.prize_tiers] == [1, 1_000, 1_000_000]
    assert [t.total_prizes for t in g.prize_tiers] == [10_000, 1_000, 1]
    assert [t.unclaimed_prizes for t in g.prize_tiers] == [9_999, 900, 1]


def test_parse_html_extracts_data_price_attribute():
    html = _wrap(
        _row(
            ["X ($20)", "$20", "1<br>(1)", "$20", "5", "3"],
            data_price="20",
        )
    )

    result = parse_html(html)
    assert result.games[0].data_price == 20


def test_parse_html_falls_back_to_data_price_when_visible_missing():
    html = _wrap(
        _row(
            ["BIG ($30)", "", "9001<br>(0)", "$30", "5", "3"],
            data_price="30",
        )
    )

    result = parse_html(html)
    g = result.games[0]
    assert g.ticket_price == 30
    assert g.data_price == 30


def test_parse_html_warns_on_length_mismatch_but_keeps_aligned_tiers():
    html = _wrap(
        _row(
            [
                "BAD GAME ($1)",
                "$1",
                "9999<br>(2)",
                "$1<br>$5",          # 2 amounts
                "10<br>5<br>1",      # 3 totals
                "8<br>4",            # 2 unclaimed
            ]
        )
    )

    result = parse_html(html)

    assert len(result.games) == 1
    assert len(result.games[0].prize_tiers) == 2  # min length aligned
    messages = [w.message for w in result.warnings]
    assert any("length mismatch" in m for m in messages)


def test_parse_html_includes_hidden_rows():
    visible = _row(
        ["VISIBLE ($1)", "$1", "1<br>(1)", "$1", "10", "5"],
    )
    hidden = _row(
        ["HIDDEN ($2)", "$2", "2<br>(2)", "$2", "20", "10"],
        data_price="2",
        style="display: none;",
    )
    html = _wrap(visible + hidden)

    result = parse_html(html)

    names = [g.game_name for g in result.games]
    assert names == ["VISIBLE", "HIDDEN"]


def test_parse_html_handles_filtered_modifier_class():
    html = _wrap(
        _row(
            ["FIVES ($5)", "$5", "55<br>(7)", "$5", "50", "25"],
            data_price="5",
            classes="unclaimed-prizes-table__row unclaimed-prizes-table__row--filtered",
        )
    )

    result = parse_html(html)
    assert len(result.games) == 1
    assert result.games[0].game_name == "FIVES"


def test_parse_html_ignores_non_game_rows():
    other = "<tr><td>Header</td></tr>"
    game = _row(["X ($1)", "$1", "1<br>(0)", "$1", "1", "1"])
    html = _wrap(other + game)

    result = parse_html(html)
    assert len(result.games) == 1
    assert result.games[0].game_name == "X"


def test_parse_html_returns_parse_result_with_both_lists():
    result = parse_html("<html><body></body></html>")
    assert isinstance(result, ParseResult)
    assert isinstance(result.games, list)
    assert isinstance(result.warnings, list)
    assert result.games == []
    assert result.warnings == []


def test_parse_html_accepts_path_argument(tmp_path):
    html = _wrap(_row(["A ($1)", "$1", "1<br>(0)", "$1", "1", "1"]))
    file_path = tmp_path / "snippet.html"
    file_path.write_text(html, encoding="utf-8")

    result = parse_html(file_path)
    assert len(result.games) == 1
    assert result.games[0].game_name == "A"


# ---- fixture-backed integration test -----------------------------------


@pytest.mark.skipif(not FIXTURE.is_file(), reason="fixture not present")
def test_parse_html_against_small_fixture():
    result = parse_html(FIXTURE)

    assert result.warnings == []
    assert len(result.games) == 2

    emeralds, five_star = result.games
    assert emeralds.game_name == "EMERALDS"
    assert emeralds.game_number == "7647"
    assert emeralds.weeks_in_market == 9
    assert emeralds.ticket_price == 1
    assert [t.prize_amount for t in emeralds.prize_tiers] == [1, 2, 5, 50_000]
    assert [t.total_prizes for t in emeralds.prize_tiers] == [
        819_477,
        660_240,
        182_124,
        3,
    ]
    assert [t.unclaimed_prizes for t in emeralds.prize_tiers] == [
        666_338,
        533_166,
        145_806,
        3,
    ]

    assert five_star.game_name == "FIVE STAR"
    assert five_star.ticket_price == 5
    assert five_star.data_price == 5
    assert [t.prize_amount for t in five_star.prize_tiers] == [5, 1_000_000]
