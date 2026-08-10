"""Tests for deterministic source validation and structure fingerprints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from illinois_lottery_tracker.parser import ParsedGame, ParsedPrizeTier, ParseResult
from illinois_lottery_tracker.source_quality import (
    assess_parse_result,
    canonical_structure_serialization,
    chicago_source_date,
    require_valid_parse_result,
    structure_fingerprint,
)


def _game() -> ParsedGame:
    return ParsedGame(
        game_name="TEST",
        display_name="TEST ($5)",
        ticket_price=5,
        data_price=5,
        game_number="1001",
        weeks_in_market=1,
        prize_tiers=[
            ParsedPrizeTier(prize_amount=1000, total_prizes=2, unclaimed_prizes=1),
            ParsedPrizeTier(prize_amount=10, total_prizes=100, unclaimed_prizes=75),
            ParsedPrizeTier(prize_amount=20, total_prizes=25, unclaimed_prizes=20),
        ],
    )


def test_structure_serialization_is_sorted_and_fixed_precision():
    tiers = [(Decimal("1000"), 2), (Decimal("10"), 100), (Decimal("20.0"), 25)]
    assert canonical_structure_serialization(tiers) == "10.00:100|20.00:25|1000.00:2"
    assert structure_fingerprint(tiers) == structure_fingerprint(reversed(tiers))
    assert len(structure_fingerprint(tiers)) == 64


def test_chicago_source_date_uses_source_timezone_boundary():
    assert chicago_source_date(datetime(2026, 8, 8, 4, 30, tzinfo=UTC)).isoformat() == (
        "2026-08-07"
    )
    assert chicago_source_date(datetime(2026, 8, 8, 5, 30, tzinfo=UTC)).isoformat() == (
        "2026-08-08"
    )


def test_chicago_source_date_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        chicago_source_date(datetime(2026, 8, 8, 5, 30))


def test_valid_parse_result_reports_exact_counts():
    report = require_valid_parse_result(ParseResult(games=[_game()]))
    assert report.is_valid
    assert report.parsed_game_count == 1
    assert report.parsed_prize_tier_count == 3


def test_duplicate_game_number_is_rejected():
    game = _game()
    duplicate = _game()
    report = assess_parse_result(ParseResult(games=[game, duplicate]))
    assert {issue.code for issue in report.issues} == {"DUPLICATE_GAME_NUMBER"}


@pytest.mark.parametrize(
    ("original", "remaining"),
    [(None, 1), (2, None), (-1, 0), (1, -1), (1, 2)],
)
def test_invalid_tier_counts_are_rejected(original, remaining):
    game = _game()
    game.prize_tiers[0].total_prizes = original
    game.prize_tiers[0].unclaimed_prizes = remaining
    report = assess_parse_result(ParseResult(games=[game]))
    assert "INVALID_TIER_COUNT" in {issue.code for issue in report.issues}
