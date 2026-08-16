"""Contract tests for the current game-detail API projection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException, Response

from illinois_lottery_tracker import api
from illinois_lottery_tracker.game_details_api import (
    GameDetailReadError,
    GameDetailUnavailableError,
    read_current_game_detail_from_connection,
)

SOURCE_AT = datetime(2026, 8, 10, 19, 44, 20, tzinfo=UTC)
CATALOG_AT = datetime(2026, 8, 10, 19, 47, 37, tzinfo=UTC)
GENERATED_AT = datetime(2026, 8, 10, 20, 0, 0, tzinfo=UTC)


class _StubMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def one(self) -> dict[str, object]:
        if len(self.rows) != 1:
            raise AssertionError(f"Expected one row, received {len(self.rows)}")
        return self.rows[0]

    def one_or_none(self) -> dict[str, object] | None:
        if len(self.rows) > 1:
            raise AssertionError(f"Expected at most one row, received {len(self.rows)}")
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _StubResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> _StubMappings:
        return _StubMappings(self.rows)


class _StubConnection:
    def __init__(self, result_sets: list[list[dict[str, object]]]) -> None:
        self.result_sets = result_sets
        self.statements: list[str] = []

    def execute(self, statement, _parameters=None) -> _StubResult:
        self.statements.append(str(statement))
        if not self.result_sets:
            raise AssertionError("The API issued an unexpected query")
        return _StubResult(self.result_sets.pop(0))


def _status_row(*, available: bool = True) -> dict[str, object]:
    return {
        "source_observed_at": SOURCE_AT,
        "catalog_observed_at": CATALOG_AT,
        "semantic_version": "2.0.0" if available else None,
        "analytics_run_id": 182 if available else None,
        "available": available,
        "reason_code": "AVAILABLE" if available else "SOURCE_STALE",
    }


def _game_row() -> dict[str, object]:
    return {
        "game_id": 42,
        "game_number": "7654",
        "game_name": "Example game",
        "ticket_price": Decimal("10.00"),
        "launch_date": date(2026, 3, 5),
        "weeks_in_market": 22,
        "published_overall_odds_one_in": Decimal("3.92"),
        "estimated_original_tickets": Decimal("5000000"),
        "estimated_sold_tickets": Decimal("2750000.5"),
        "estimated_remaining_tickets": Decimal("2249999.5"),
        "estimated_ev_full": Decimal("7.42"),
        "estimated_ev_ex_top": Decimal("7.04"),
        "top_prize_amount": Decimal("500000"),
        "top_prizes_original": 5,
        "top_prizes_remaining": 2,
        "p_any_win": Decimal("0.25"),
        "one_in_any_win": Decimal("4"),
        "p_strict_profit": Decimal("0.080000888889"),
        "p_strict_profit_ex_top": Decimal("0.08"),
        "one_in_strict_profit_ex_top": Decimal("12.5"),
        "p_10x_or_better_ex_top": Decimal("0.01"),
        "one_in_10x_or_better_ex_top": Decimal("100"),
        "p_top_prize_estimated": Decimal("0.000000888889"),
        "one_in_top_prize_estimated": Decimal("1124999.75"),
        "metric_statuses": {
            "value_full": "complete",
            "profit_ex_top": "complete",
            "moderate_10x": "complete",
            "jackpot_top_odds": "complete",
        },
    }


def _tier_row() -> dict[str, object]:
    return {
        "prize_amount": Decimal("1000"),
        "original_count": 400,
        "claimed_count": 250,
        "is_top_prize": False,
        "reported_remaining_count": 150,
        "estimated_pending_count": Decimal("6.5"),
        "estimated_remaining_count": Decimal("143.5"),
        "adjustment_status": "applied",
        "lag_days_used": 24,
        "launch_one_in": Decimal("12500"),
        "current_one_in": Decimal("15679.44"),
        "confidence_label": "moderate",
        "status": "available",
    }


def test_current_game_detail_maps_real_tier_fields_to_frontend_contract() -> None:
    connection = _StubConnection([[_status_row()], [_game_row()], [_tier_row()]])

    document = read_current_game_detail_from_connection(
        connection,  # type: ignore[arg-type]
        42,
        generated_at=GENERATED_AT,
    )

    assert document is not None
    payload = document.model_dump(mode="json", by_alias=True)
    assert payload["gameId"] == 42
    assert payload["gameName"] == "Example game"
    assert payload["estimatedSoldTickets"] == 2750000.5
    assert payload["estimatedCurrentOverallOddsOneIn"] == 4.0
    assert payload["outcomes"] == [
        {
            "outcomeKey": "any_win",
            "probability": 0.25,
            "oneIn": 4.0,
            "metricStatus": "complete",
        },
        {
            "outcomeKey": "profit_full",
            "probability": 0.080000888889,
            "oneIn": 12.499861112636943,
            "metricStatus": "complete",
        },
        {
            "outcomeKey": "profit_ex_top",
            "probability": 0.08,
            "oneIn": 12.5,
            "metricStatus": "complete",
        },
        {
            "outcomeKey": "moderate_10x_full",
            "probability": 0.010000888889,
            "oneIn": 99.99111190005343,
            "metricStatus": "complete",
        },
        {
            "outcomeKey": "moderate_10x_ex_top",
            "probability": 0.01,
            "oneIn": 100.0,
            "metricStatus": "complete",
        },
        {
            "outcomeKey": "jackpot_top_odds",
            "probability": 8.88889e-07,
            "oneIn": 1124999.75,
            "metricStatus": "complete",
        },
    ]
    assert payload["tiers"] == [
        {
            "prizeAmount": 1000.0,
            "isTopPrize": False,
            "originalCount": 400,
            "claimedCount": 250,
            "reportedRemainingCount": 150,
            "estimatedPendingCount": 6.5,
            "estimatedRemainingCount": 143.5,
            "adjustmentStatus": "applied",
            "lagDaysUsed": 24,
            "launchOneIn": 12500.0,
            "currentOneIn": 15679.44,
            "confidenceLabel": "moderate",
            "status": "available",
        }
    ]
    assert len(connection.statements) == 3


def test_unavailable_publication_fails_closed_before_game_queries() -> None:
    connection = _StubConnection([[_status_row(available=False)]])

    with pytest.raises(GameDetailUnavailableError, match="SOURCE_STALE"):
        read_current_game_detail_from_connection(
            connection,  # type: ignore[arg-type]
            42,
            generated_at=GENERATED_AT,
        )

    assert len(connection.statements) == 1


def test_game_outside_current_published_comparison_is_not_found() -> None:
    connection = _StubConnection([[_status_row()], []])

    document = read_current_game_detail_from_connection(
        connection,  # type: ignore[arg-type]
        999,
        generated_at=GENERATED_AT,
    )

    assert document is None
    assert len(connection.statements) == 2


def test_inconsistent_claimed_count_is_rejected() -> None:
    tier = _tier_row()
    tier["claimed_count"] = 249
    connection = _StubConnection([[_status_row()], [_game_row()], [tier]])

    with pytest.raises(GameDetailReadError, match="claimed-count identity"):
        read_current_game_detail_from_connection(
            connection,  # type: ignore[arg-type]
            42,
            generated_at=GENERATED_AT,
        )


def test_http_projection_returns_no_store_and_distinguishes_missing_game(
    monkeypatch,
) -> None:
    document = read_current_game_detail_from_connection(
        _StubConnection([[_status_row()], [_game_row()], [_tier_row()]]),  # type: ignore[arg-type]
        42,
        generated_at=GENERATED_AT,
    )
    monkeypatch.setattr(api, "get_engine", lambda: object())
    monkeypatch.setattr(api, "read_current_game_detail", lambda _engine, _id: document)

    response = Response()
    returned = api.get_game_detail(42, response)

    assert returned.game_id == 42
    assert response.headers["cache-control"] == "no-store"
    assert any(route.path == "/api/v1/games/{game_id}" for route in api.app.routes)

    monkeypatch.setattr(api, "read_current_game_detail", lambda _engine, _id: None)
    with pytest.raises(HTTPException) as missing:
        api.get_game_detail(999, Response())
    assert missing.value.status_code == 404
