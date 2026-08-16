"""Contract tests for the read-only ranking API projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import Response

from illinois_lottery_tracker import api
from illinois_lottery_tracker.rankings_api import (
    RankingReadError,
    read_current_rankings_from_connection,
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

    def execute(self, statement) -> _StubResult:
        self.statements.append(str(statement))
        if not self.result_sets:
            raise AssertionError("The API issued an unexpected query")
        return _StubResult(self.result_sets.pop(0))


def _status_row(*, available: bool) -> dict[str, object]:
    return {
        "source_run_id": 96,
        "source_observed_at": SOURCE_AT,
        "catalog_run_id": 98,
        "catalog_observed_at": CATALOG_AT,
        "semantic_version": "2.0.0" if available else None,
        "analytics_run_id": 91 if available else None,
        "available": available,
        "reason_code": "AVAILABLE" if available else "ANALYTICS_MODEL_UNAVAILABLE",
    }


def _ranking_row() -> dict[str, object]:
    return {
        "analytics_run_id": 91,
        "game_id": 42,
        "game_number": "7654",
        "game_name": "Example game",
        "ticket_price": Decimal("10.00"),
        "strategy_key": "value_ex_top",
        "metric_value": Decimal("0.704"),
        "one_in_value": None,
        "launch_metric_value": Decimal("0.682"),
        "relative_to_launch": Decimal("1.032258"),
        "target_tier_count": 11,
        "target_count_coverage": Decimal("1"),
        "target_value_coverage": Decimal("1"),
        "metric_status": "complete",
        "lowest_confidence": "moderate",
        "contains_lumpy_tier": False,
        "source_observed_at": SOURCE_AT,
        "catalog_observed_at": CATALOG_AT,
        "model_version": "2.0.0",
        "rank_overall": 1,
        "rank_within_ticket_price": 1,
        "estimated_ev_full": Decimal("7.42"),
        "estimated_ev_ex_top": Decimal("7.04"),
        "top_prize_amount": Decimal("500000"),
        "top_prizes_original": 5,
        "top_prizes_remaining": 2,
        "weeks_in_market": 22,
        "profit_ex_top_probability": Decimal("0.08"),
        "one_in_profit_ex_top": Decimal("12.5"),
        "ten_x_ex_top_probability": Decimal("0.01"),
        "one_in_ten_x_ex_top": Decimal("100"),
    }


def test_unavailable_status_never_queries_or_returns_ranking_rows():
    connection = _StubConnection([[_status_row(available=False)]])

    document = read_current_rankings_from_connection(
        connection,  # type: ignore[arg-type]
        generated_at=GENERATED_AT,
    )

    payload = document.model_dump(mode="json", by_alias=True)
    assert payload["mode"] == "live"
    assert payload["status"]["reasonCode"] == "ANALYTICS_MODEL_UNAVAILABLE"
    assert payload["status"]["sourceRunId"] == 96
    assert payload["status"]["catalogRunId"] == 98
    assert payload["status"]["analyticsRunId"] is None
    assert payload["rankings"] == []
    assert len(connection.statements) == 1


def test_available_rows_are_mapped_to_the_camel_case_frontend_contract():
    connection = _StubConnection(
        [[_status_row(available=True)], [_ranking_row()]],
    )

    document = read_current_rankings_from_connection(
        connection,  # type: ignore[arg-type]
        generated_at=GENERATED_AT,
    )

    payload = document.model_dump(mode="json", by_alias=True)
    assert payload["status"]["reasonCode"] == "AVAILABLE"
    assert payload["rankings"] == [
        {
            "analyticsRunId": 91,
            "gameId": 42,
            "gameNumber": "7654",
            "gameName": "Example game",
            "ticketPrice": 10.0,
            "strategyKey": "value_ex_top",
            "metricValue": 0.704,
            "oneInValue": None,
            "launchMetricValue": 0.682,
            "relativeToLaunch": 1.032258,
            "targetTierCount": 11,
            "targetCountCoverage": 1.0,
            "targetValueCoverage": 1.0,
            "metricStatus": "complete",
            "lowestConfidence": "moderate",
            "containsLumpyTier": False,
            "sourceObservedAt": "2026-08-10T19:44:20Z",
            "catalogObservedAt": "2026-08-10T19:47:37Z",
            "modelVersion": "2.0.0",
            "rankOverall": 1,
            "rankWithinTicketPrice": 1,
            "estimatedEvFull": 7.42,
            "estimatedEvExTop": 7.04,
            "topPrizeAmount": 500000.0,
            "topPrizesOriginal": 5,
            "topPrizesRemaining": 2,
            "weeksInMarket": 22,
            "profitExTopProbability": 0.08,
            "oneInProfitExTop": 12.5,
            "tenXExTopProbability": 0.01,
            "oneInTenXExTop": 100.0,
        }
    ]
    assert len(connection.statements) == 2


def test_row_from_a_different_cutoff_is_rejected():
    row = _ranking_row()
    row["source_observed_at"] = SOURCE_AT - timedelta(days=1)
    connection = _StubConnection([[_status_row(available=True)], [row]])

    with pytest.raises(RankingReadError, match="does not match the published cutoff"):
        read_current_rankings_from_connection(
            connection,  # type: ignore[arg-type]
            generated_at=GENERATED_AT,
        )


def test_http_endpoint_uses_aliases_and_disables_caching(monkeypatch):
    document = read_current_rankings_from_connection(
        _StubConnection([[_status_row(available=False)]]),  # type: ignore[arg-type]
        generated_at=GENERATED_AT,
    )
    monkeypatch.setattr(api, "get_engine", lambda: object())
    monkeypatch.setattr(api, "read_current_rankings", lambda _engine: document)

    response = Response()
    returned = api.get_rankings(response)
    payload = returned.model_dump(mode="json", by_alias=True)

    assert response.headers["cache-control"] == "no-store"
    assert payload["generatedAt"] == "2026-08-10T20:00:00Z"
    assert payload["status"]["reasonCode"] == "ANALYTICS_MODEL_UNAVAILABLE"
    assert payload["rankings"] == []
    assert any(route.path == "/api/v1/rankings" for route in api.app.routes)
