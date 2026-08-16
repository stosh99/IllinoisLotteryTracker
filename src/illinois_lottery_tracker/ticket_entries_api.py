"""Authenticated CRUD endpoints for user-owned ticket results."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth.types import AuthPrincipal
from .auth_api import (
    _known_user_rate_limit,
    _principal,
    _problem,
    _unavailable,
    _validate_unsafe,
    auth_runtime,
)
from .db import get_session
from .models import Game, UserTicketEntry

router = APIRouter(prefix="/api/v1/ticket-entries", tags=["ticket history"])
SessionContextFactory = Callable[[], AbstractContextManager[Session]]
CHICAGO = ZoneInfo("America/Chicago")


class TicketEntryError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TicketEntryRecord:
    id: uuid.UUID
    game_id: int
    game_number: str
    game_name: str
    ticket_price: Decimal
    played_on: date
    ticket_count: int
    amount_won: Decimal
    created_at: datetime

    @property
    def amount_spent(self) -> Decimal:
        return self.ticket_price * self.ticket_count

    @property
    def net_result(self) -> Decimal:
        return self.amount_won - self.amount_spent


class TicketEntryStore:
    def __init__(self, sessions: SessionContextFactory = get_session):
        self.sessions = sessions

    def list_owned(self, user_id: uuid.UUID) -> list[TicketEntryRecord]:
        with self.sessions() as session:
            entries = session.scalars(
                select(UserTicketEntry)
                .where(UserTicketEntry.user_id == user_id)
                .order_by(UserTicketEntry.played_on.desc(), UserTicketEntry.created_at.desc())
            ).all()
            return [_record(entry) for entry in entries]

    def create(
        self,
        user_id: uuid.UUID,
        *,
        game_id: int,
        played_on: date,
        ticket_count: int,
        amount_won: Decimal,
    ) -> TicketEntryRecord:
        with self.sessions() as session:
            game = session.get(Game, game_id)
            if game is None or game.ticket_price is None:
                raise TicketEntryError("GAME_NOT_FOUND")
            entry = UserTicketEntry(
                user_id=user_id,
                game_id=game.id,
                game_number=game.game_number,
                game_name=game.name,
                ticket_price=game.ticket_price,
                played_on=played_on,
                ticket_count=ticket_count,
                amount_won=amount_won,
            )
            session.add(entry)
            session.flush()
            session.refresh(entry)
            return _record(entry)

    def delete_owned(self, user_id: uuid.UUID, entry_id: uuid.UUID) -> bool:
        with self.sessions() as session:
            result = session.execute(
                delete(UserTicketEntry).where(
                    UserTicketEntry.id == entry_id,
                    UserTicketEntry.user_id == user_id,
                )
            )
            return bool(result.rowcount)


def _store(request: Request) -> TicketEntryStore:
    return getattr(request.app.state, "ticket_entry_store", None) or TicketEntryStore()


def _authenticated(request: Request, policy: str) -> tuple[AuthPrincipal, str] | Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.sessions is None:
        return _unavailable(request)
    try:
        principal, raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    if problem := _known_user_rate_limit(request, runtime, principal, policy):
        return problem
    return principal, raw


@router.get("")
def list_ticket_entries(request: Request) -> Response:
    authenticated = _authenticated(request, "read")
    if isinstance(authenticated, Response):
        return authenticated
    principal, _raw = authenticated
    try:
        entries = _store(request).list_owned(principal.user_id)
    except Exception:
        return _problem(request, 503, "TICKET_HISTORY_UNAVAILABLE", "Ticket history unavailable")
    return JSONResponse(
        _collection_document(entries),
        headers={"Cache-Control": "no-store", "Vary": "Cookie"},
    )


@router.post("")
async def create_ticket_entry(request: Request) -> Response:
    authenticated = _authenticated(request, "write")
    if isinstance(authenticated, Response):
        return authenticated
    principal, raw = authenticated
    runtime = auth_runtime(request)
    if problem := await _validate_unsafe(
        request,
        runtime,
        principal,
        raw,
        require_empty_json=False,
        json_keys=frozenset({"gameId", "playedOn", "ticketCount", "amountWon"}),
    ):
        return problem
    try:
        values = _validate_create_document(request.state.auth_document)
        entry = _store(request).create(principal.user_id, **values)
    except TicketEntryError as exc:
        status = 404 if exc.code == "GAME_NOT_FOUND" else 400
        return _problem(request, status, exc.code, "Ticket result could not be saved")
    except Exception:
        return _problem(request, 503, "TICKET_HISTORY_UNAVAILABLE", "Ticket history unavailable")
    return JSONResponse(
        _entry_document(entry),
        status_code=201,
        headers={"Cache-Control": "no-store", "Vary": "Cookie"},
    )


@router.delete("/{entry_id}")
async def delete_ticket_entry(entry_id: str, request: Request) -> Response:
    authenticated = _authenticated(request, "write")
    if isinstance(authenticated, Response):
        return authenticated
    principal, raw = authenticated
    runtime = auth_runtime(request)
    if problem := await _validate_unsafe(
        request, runtime, principal, raw, require_empty_json=False
    ):
        return problem
    try:
        parsed_id = uuid.UUID(entry_id)
    except ValueError:
        return _problem(request, 404, "TICKET_ENTRY_NOT_FOUND", "Ticket result not found")
    try:
        deleted = _store(request).delete_owned(principal.user_id, parsed_id)
    except Exception:
        return _problem(request, 503, "TICKET_HISTORY_UNAVAILABLE", "Ticket history unavailable")
    if not deleted:
        return _problem(request, 404, "TICKET_ENTRY_NOT_FOUND", "Ticket result not found")
    return Response(status_code=204, headers={"Cache-Control": "no-store", "Vary": "Cookie"})


def _validate_create_document(document: dict) -> dict:
    game_id = document["gameId"]
    ticket_count = document["ticketCount"]
    if isinstance(game_id, bool) or not isinstance(game_id, int) or game_id <= 0:
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    if (
        isinstance(ticket_count, bool)
        or not isinstance(ticket_count, int)
        or not 1 <= ticket_count <= 1000
    ):
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    try:
        played_on = date.fromisoformat(document["playedOn"])
    except (TypeError, ValueError):
        raise TicketEntryError("INVALID_TICKET_ENTRY") from None
    if played_on > datetime.now(CHICAGO).date():
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    amount_value = document["amountWon"]
    if isinstance(amount_value, bool) or not isinstance(amount_value, (int, float, str)):
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    if isinstance(amount_value, float) and not math.isfinite(amount_value):
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    try:
        amount_won = Decimal(str(amount_value))
    except InvalidOperation:
        raise TicketEntryError("INVALID_TICKET_ENTRY") from None
    if amount_won < 0 or amount_won > Decimal("1000000000"):
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    if amount_won != amount_won.quantize(Decimal("0.01")):
        raise TicketEntryError("INVALID_TICKET_ENTRY")
    return {
        "game_id": game_id,
        "played_on": played_on,
        "ticket_count": ticket_count,
        "amount_won": amount_won,
    }


def _record(entry: UserTicketEntry) -> TicketEntryRecord:
    return TicketEntryRecord(
        id=entry.id,
        game_id=entry.game_id,
        game_number=entry.game_number,
        game_name=entry.game_name,
        ticket_price=entry.ticket_price,
        played_on=entry.played_on,
        ticket_count=entry.ticket_count,
        amount_won=entry.amount_won,
        created_at=entry.created_at,
    )


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _entry_document(entry: TicketEntryRecord) -> dict:
    return {
        "id": str(entry.id),
        "gameId": entry.game_id,
        "gameNumber": entry.game_number,
        "gameName": entry.game_name,
        "ticketPrice": _money(entry.ticket_price),
        "playedOn": entry.played_on.isoformat(),
        "ticketCount": entry.ticket_count,
        "amountSpent": _money(entry.amount_spent),
        "amountWon": _money(entry.amount_won),
        "netResult": _money(entry.net_result),
        "createdAt": entry.created_at.isoformat().replace("+00:00", "Z"),
    }


def _collection_document(entries: list[TicketEntryRecord]) -> dict:
    amount_spent = sum((entry.amount_spent for entry in entries), Decimal(0))
    amount_won = sum((entry.amount_won for entry in entries), Decimal(0))
    ticket_count = sum(entry.ticket_count for entry in entries)
    return_percentage = (
        _money((amount_won / amount_spent) * 100) if amount_spent > 0 else None
    )
    return {
        "summary": {
            "entryCount": len(entries),
            "ticketCount": ticket_count,
            "amountSpent": _money(amount_spent),
            "amountWon": _money(amount_won),
            "netResult": _money(amount_won - amount_spent),
            "returnPercentage": return_percentage,
        },
        "entries": [_entry_document(entry) for entry in entries],
    }
