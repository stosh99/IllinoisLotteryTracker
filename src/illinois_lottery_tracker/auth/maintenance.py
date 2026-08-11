"""Bounded authentication lifecycle and retention maintenance."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..auth_models import AuthEvent, OidcLoginAttempt, UserSession
from .repository import AuthRepository

SessionContextFactory = Callable[[], AbstractContextManager[Session]]
TERMINAL_ATTEMPT_STATUSES = ("succeeded", "failed", "denied", "expired", "superseded")
BATCH_SIZE = 1_000


@dataclass
class MaintenanceCounts:
    attempts_expired: int = 0
    exchanges_abandoned: int = 0
    attempts_deleted: int = 0
    sessions_expired: int = 0
    sessions_deleted: int = 0
    events_deleted: int = 0

    def add(self, name: str, value: int) -> None:
        setattr(self, name, getattr(self, name) + value)

    def document(self, *, mode: str) -> dict[str, int | str]:
        return {"mode": mode, **asdict(self)}


class AuthenticationMaintenance:
    def __init__(
        self,
        sessions: SessionContextFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_size: int = BATCH_SIZE,
    ):
        if not 1 <= batch_size <= BATCH_SIZE:
            raise ValueError("maintenance batch size must be between 1 and 1000")
        self.sessions = sessions
        self.clock = clock
        self.batch_size = batch_size

    def run(self, *, apply: bool = False) -> MaintenanceCounts:
        now = self.clock()
        if not apply:
            return self._dry_run(now)
        counts = MaintenanceCounts()
        self._process_attempts(now, "pending", counts)
        self._process_attempts(now, "exchanging", counts)
        self._delete_attempts(now, counts)
        self._expire_sessions(now, counts)
        self._delete_sessions(now, counts)
        self._delete_events(now, counts)
        return counts

    def _dry_run(self, now: datetime) -> MaintenanceCounts:
        attempt_cutoff = now - timedelta(hours=24)
        session_cutoff = now - timedelta(days=30)
        event_cutoff = now - timedelta(days=90)
        with self.sessions() as session:
            def scalar(query) -> int:
                return int(session.scalar(query) or 0)

            return MaintenanceCounts(
                attempts_expired=scalar(
                    select(func.count()).select_from(OidcLoginAttempt).where(
                        OidcLoginAttempt.status == "pending",
                        OidcLoginAttempt.expires_at <= now,
                    )
                ),
                exchanges_abandoned=scalar(
                    select(func.count()).select_from(OidcLoginAttempt).where(
                        OidcLoginAttempt.status == "exchanging",
                        OidcLoginAttempt.expires_at <= now - timedelta(seconds=30),
                    )
                ),
                attempts_deleted=scalar(
                    select(func.count()).select_from(OidcLoginAttempt).where(
                        OidcLoginAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES),
                        OidcLoginAttempt.completed_at < attempt_cutoff,
                    )
                ),
                sessions_expired=scalar(
                    select(func.count()).select_from(UserSession).where(
                        UserSession.revoked_at.is_(None),
                        or_(
                            UserSession.idle_expires_at <= now,
                            UserSession.absolute_expires_at <= now,
                        ),
                    )
                ),
                sessions_deleted=scalar(
                    select(func.count()).select_from(UserSession).where(
                        or_(
                            UserSession.revoked_at < session_cutoff,
                            UserSession.idle_expires_at < session_cutoff,
                            UserSession.absolute_expires_at < session_cutoff,
                        )
                    )
                ),
                events_deleted=scalar(
                    select(func.count()).select_from(AuthEvent).where(
                        AuthEvent.occurred_at < event_cutoff
                    )
                ),
            )

    def _process_attempts(
        self, now: datetime, status: str, counts: MaintenanceCounts
    ) -> None:
        result_name = "attempts_expired" if status == "pending" else "exchanges_abandoned"
        while True:
            with self.sessions() as session:
                query = (
                    select(OidcLoginAttempt)
                    .where(
                        OidcLoginAttempt.status == status,
                        OidcLoginAttempt.expires_at
                        <= now
                        - (timedelta(seconds=30) if status == "exchanging" else timedelta()),
                    )
                    .order_by(OidcLoginAttempt.expires_at, OidcLoginAttempt.id)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
                rows = list(session.scalars(query))
                repository = AuthRepository(session)
                for row in rows:
                    row.status = "expired" if status == "pending" else "failed"
                    row.completed_at = now
                    row.failure_code = (
                        "attempt_expired" if status == "pending" else "exchange_abandoned"
                    )
                    repository.append_event(
                        event_type=(
                            "reauth_failed" if row.intent == "reauth_delete" else "login_failed"
                        ),
                        outcome="failure",
                        occurred_at=now,
                        user_id=row.expected_user_id,
                        session_id=row.expected_session_id,
                        attempt_id=row.id,
                        reason_code=row.failure_code,
                        details={"provider": "google", "intent": row.intent},
                    )
                session.flush()
            counts.add(result_name, len(rows))
            if len(rows) < self.batch_size:
                return

    def _delete_attempts(self, now: datetime, counts: MaintenanceCounts) -> None:
        cutoff = now - timedelta(hours=24)
        self._delete_in_batches(
            OidcLoginAttempt,
            select(OidcLoginAttempt.id).where(
                OidcLoginAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES),
                OidcLoginAttempt.completed_at < cutoff,
            ),
            "attempts_deleted",
            counts,
        )

    def _expire_sessions(self, now: datetime, counts: MaintenanceCounts) -> None:
        while True:
            with self.sessions() as session:
                rows = list(
                    session.scalars(
                        select(UserSession)
                        .where(
                            UserSession.revoked_at.is_(None),
                            or_(
                                UserSession.idle_expires_at <= now,
                                UserSession.absolute_expires_at <= now,
                            ),
                        )
                        .order_by(UserSession.idle_expires_at, UserSession.id)
                        .limit(self.batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                repository = AuthRepository(session)
                for row in rows:
                    idle_first = row.idle_expires_at <= row.absolute_expires_at
                    row.revoked_at = (
                        row.idle_expires_at if idle_first else row.absolute_expires_at
                    )
                    row.revocation_reason = "expired_idle" if idle_first else "expired_absolute"
                    repository.append_event(
                        event_type="session_rejected",
                        outcome="failure",
                        occurred_at=now,
                        user_id=row.user_id,
                        session_id=row.id,
                        reason_code=row.revocation_reason,
                    )
                session.flush()
            counts.add("sessions_expired", len(rows))
            if len(rows) < self.batch_size:
                return

    def _delete_sessions(self, now: datetime, counts: MaintenanceCounts) -> None:
        cutoff = now - timedelta(days=30)
        self._delete_in_batches(
            UserSession,
            select(UserSession.id).where(
                or_(
                    UserSession.revoked_at < cutoff,
                    UserSession.idle_expires_at < cutoff,
                    UserSession.absolute_expires_at < cutoff,
                )
            ),
            "sessions_deleted",
            counts,
        )

    def _delete_events(self, now: datetime, counts: MaintenanceCounts) -> None:
        self._delete_in_batches(
            AuthEvent,
            select(AuthEvent.id).where(AuthEvent.occurred_at < now - timedelta(days=90)),
            "events_deleted",
            counts,
        )

    def _delete_in_batches(self, model, base_query, name: str, counts: MaintenanceCounts) -> None:
        while True:
            with self.sessions() as session:
                ids = list(
                    session.scalars(
                        base_query.order_by(model.id)
                        .limit(self.batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                if ids:
                    session.execute(delete(model).where(model.id.in_(ids)))
            counts.add(name, len(ids))
            if len(ids) < self.batch_size:
                return
