"""Contract tests for game history used by the detail-page charts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException, Response

from illinois_lottery_tracker import api
from illinois_lottery_tracker.game_history_api import (
    GameHistoryReadError,
    GameHistoryUnavailableError,
    read_current_game_history_from_connection,
)

SOURCE_AT = datetime(2026, 8, 10, 19, 44, 20, tzinfo=UTC)
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

    def execute(self, _statement, _parameters=None) -> _StubResult:
        if not self.result_sets:
            raise AssertionError("The API issued an unexpected query")
        return _StubResult(self.result_sets.pop(0))


def _status(*, available: bool = True) -> dict[str, object]:
    return {
        "source_observed_at": SOURCE_AT,
        "semantic_version": "2.0.0" if available else None,
        "available": available,
        "reason_code": "AVAILABLE" if available else "SOURCE_STALE",
    }


def _game() -> dict[str, object]:
    return {"game_id": 42, "game_number": "7654", "game_name": "Example game"}


def _sales(day: int, fingerprint: str, sold: str) -> dict[str, object]:
    sold_value = Decimal(sold)
    return {
        "observed_at": SOURCE_AT - timedelta(days=day),
        "structure_fingerprint": fingerprint,
        "estimated_original_tickets": Decimal("1000"),
        "estimated_sold_tickets": sold_value,
        "estimated_remaining_tickets": Decimal("1000") - sold_value,
    }


def _tier(
    snapshot_id: int,
    day: int,
    fingerprint: str,
    prize: str,
    original: int,
    remaining: int,
) -> dict[str, object]:
    return {
        "game_snapshot_id": snapshot_id,
        "observed_at": SOURCE_AT - timedelta(days=day),
        "structure_fingerprint": fingerprint,
        "prize_amount": Decimal(prize),
        "original_count": original,
        "claimed_count": original - remaining,
        "remaining_count": remaining,
    }


def test_history_maps_sales_and_normalized_tier_claim_series() -> None:
    sales = [_sales(20, "a", "100"), _sales(10, "a", "250"), _sales(0, "b", "300")]
    tiers = [
        _tier(1, 20, "a", "1000", 10, 9),
        _tier(1, 20, "a", "10", 100, 90),
        _tier(2, 10, "a", "1000", 10, 7),
        _tier(2, 10, "a", "10", 100, 70),
        _tier(3, 0, "b", "1000", 10, 6),
        _tier(3, 0, "b", "10", 100, 60),
    ]
    connection = _StubConnection([[_status()], [_game()], sales, tiers])

    document = read_current_game_history_from_connection(
        connection,  # type: ignore[arg-type]
        42,
        generated_at=GENERATED_AT,
    )

    assert document is not None
    payload = document.model_dump(mode="json", by_alias=True)
    assert [point["segment"] for point in payload["salesPoints"]] == [0, 0, 1]
    assert [series["prizeAmount"] for series in payload["tierSeries"]] == [1000.0, 10.0]
    assert [point["claimedFraction"] for point in payload["tierSeries"][0]["points"]] == [
        0.1,
        0.3,
        0.4,
    ]
    assert [point["segment"] for point in payload["tierSeries"][0]["points"]] == [0, 0, 1]


def test_history_fails_closed_when_current_publication_is_unavailable() -> None:
    connection = _StubConnection([[_status(available=False)]])

    with pytest.raises(GameHistoryUnavailableError, match="SOURCE_STALE"):
        read_current_game_history_from_connection(
            connection,  # type: ignore[arg-type]
            42,
            generated_at=GENERATED_AT,
        )


def test_history_returns_not_found_for_a_game_outside_current_comparison() -> None:
    connection = _StubConnection([[_status()], []])
    assert (
        read_current_game_history_from_connection(
            connection,  # type: ignore[arg-type]
            999,
            generated_at=GENERATED_AT,
        )
        is None
    )


def test_history_rejects_inconsistent_official_tier_counts() -> None:
    tier = _tier(1, 0, "a", "1000", 10, 8)
    tier["claimed_count"] = 1
    connection = _StubConnection([[_status()], [_game()], [], [tier]])

    with pytest.raises(GameHistoryReadError, match="do not reconcile"):
        read_current_game_history_from_connection(
            connection,  # type: ignore[arg-type]
            42,
            generated_at=GENERATED_AT,
        )


def test_http_projection_returns_no_store_and_distinguishes_missing_game(
    monkeypatch,
) -> None:
    document = read_current_game_history_from_connection(
        _StubConnection(
            [[_status()], [_game()], [_sales(0, "a", "300")], [_tier(1, 0, "a", "1000", 10, 6)]]
        ),  # type: ignore[arg-type]
        42,
        generated_at=GENERATED_AT,
    )
    monkeypatch.setattr(api, "get_engine", lambda: object())
    monkeypatch.setattr(api, "read_current_game_history", lambda _engine, _id: document)

    response = Response()
    returned = api.get_game_history(42, response)

    assert returned.game_id == 42
    assert response.headers["cache-control"] == "no-store"
    assert any(
        route.path == "/api/v1/games/{game_id}/history" for route in api.app.routes
    )

    monkeypatch.setattr(api, "read_current_game_history", lambda _engine, _id: None)
    with pytest.raises(HTTPException) as missing:
        api.get_game_history(999, Response())
    assert missing.value.status_code == 404
