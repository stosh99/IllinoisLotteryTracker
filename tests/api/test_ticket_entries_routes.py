from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from illinois_lottery_tracker import api
from illinois_lottery_tracker.auth_api import AuthRuntime
from illinois_lottery_tracker.ticket_entries_api import TicketEntryRecord

from .test_auth_routes import RAW_SESSION, FakeSessions, _csrf, _principal, _settings


class FakeTicketStore:
    def __init__(self) -> None:
        self.entries = [
            TicketEntryRecord(
                id=uuid.UUID("f7e01077-d6c1-4e08-a685-53539160d0f8"),
                game_id=102,
                game_number="7665",
                game_name="Mega Blast",
                ticket_price=Decimal("25.00"),
                played_on=date(2026, 8, 10),
                ticket_count=2,
                amount_won=Decimal("10.00"),
                created_at=datetime(2026, 8, 10, 19, tzinfo=UTC),
            )
        ]
        self.created: dict | None = None
        self.deleted: tuple[uuid.UUID, uuid.UUID] | None = None

    def list_owned(self, _user_id: uuid.UUID):
        return self.entries

    def create(self, user_id: uuid.UUID, **values):
        self.created = {"user_id": user_id, **values}
        return self.entries[0]

    def delete_owned(self, user_id: uuid.UUID, entry_id: uuid.UUID) -> bool:
        self.deleted = (user_id, entry_id)
        return entry_id == self.entries[0].id


@pytest.fixture(autouse=True)
def runtime() -> FakeTicketStore:
    store = FakeTicketStore()
    api.app.state.auth_runtime = AuthRuntime(
        settings=_settings(), sessions=FakeSessions(_principal())  # type: ignore[arg-type]
    )
    api.app.state.ticket_entry_store = store
    yield store
    del api.app.state.auth_runtime
    del api.app.state.ticket_entry_store


def _headers() -> dict[str, str]:
    settings = _settings()
    return {
        "Origin": settings.public_base_url or "",
        "X-CSRF-Token": _csrf(settings, _principal()),
        "Content-Type": "application/json",
    }


def test_list_returns_only_owned_history_and_calculated_totals(runtime: FakeTicketStore) -> None:
    with TestClient(api.app) as client:
        client.cookies.set(_settings().session_cookie_name, RAW_SESSION)
        response = client.get("/api/v1/ticket-entries")
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "entryCount": 1,
        "ticketCount": 2,
        "amountSpent": 50.0,
        "amountWon": 10.0,
        "netResult": -40.0,
        "returnPercentage": 20.0,
    }
    assert response.json()["entries"][0]["gameName"] == "Mega Blast"
    assert response.headers["cache-control"] == "no-store"


def test_create_requires_csrf_and_accepts_bounded_exact_input(runtime: FakeTicketStore) -> None:
    body = {"gameId": 102, "playedOn": "2026-08-10", "ticketCount": 3, "amountWon": 25}
    with TestClient(api.app) as client:
        client.cookies.set(_settings().session_cookie_name, RAW_SESSION)
        assert client.post("/api/v1/ticket-entries", json=body).status_code == 403
        response = client.post("/api/v1/ticket-entries", json=body, headers=_headers())
    assert response.status_code == 201
    assert runtime.created == {
        "user_id": _principal().user_id,
        "game_id": 102,
        "played_on": date(2026, 8, 10),
        "ticket_count": 3,
        "amount_won": Decimal("25"),
    }


def test_create_rejects_future_dates_and_extra_fields(runtime: FakeTicketStore) -> None:
    base = {"gameId": 102, "playedOn": "2099-01-01", "ticketCount": 1, "amountWon": 0}
    with TestClient(api.app) as client:
        client.cookies.set(_settings().session_cookie_name, RAW_SESSION)
        future = client.post("/api/v1/ticket-entries", json=base, headers=_headers())
        extra = client.post(
            "/api/v1/ticket-entries",
            json={**base, "playedOn": "2026-08-10", "note": "private"},
            headers=_headers(),
        )
    assert future.status_code == 400
    assert future.json()["code"] == "INVALID_TICKET_ENTRY"
    assert extra.status_code == 400
    assert runtime.created is None


def test_delete_is_scoped_to_the_current_user(runtime: FakeTicketStore) -> None:
    entry_id = runtime.entries[0].id
    headers = _headers()
    headers.pop("Content-Type")
    with TestClient(api.app) as client:
        client.cookies.set(_settings().session_cookie_name, RAW_SESSION)
        response = client.delete(f"/api/v1/ticket-entries/{entry_id}", headers=headers)
        missing = client.delete(f"/api/v1/ticket-entries/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 204
    assert missing.status_code == 404
    assert runtime.deleted is not None and runtime.deleted[0] == _principal().user_id
