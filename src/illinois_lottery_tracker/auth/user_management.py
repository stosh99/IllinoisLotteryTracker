"""Guarded database-only operator controls for local accounts."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth_models import AppUser, UserSession
from .deletion import delete_user_owned_data
from .repository import AuthRepository

SessionContextFactory = Callable[[], AbstractContextManager[Session]]
SUSPEND_REASONS = frozenset(
    {
        "abuse",
        "suspected_compromise",
        "legal_request",
        "user_request",
        "test_account",
        "operator_correction",
    }
)
REACTIVATE_REASONS = frozenset({"review_cleared", "operator_correction", "test_complete"})
REVOKE_REASONS = frozenset(
    {"suspected_compromise", "user_request", "operator_correction"}
)
DELETE_REASONS = frozenset({"user_request", "legal_request", "operator_correction"})


class UserOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UserOperationResult:
    user_id: str
    prior_status: str
    resulting_status: str
    sessions_affected: int
    action: str
    mode: str

    def document(self) -> dict[str, str | int]:
        return asdict(self)


class UserAccountManager:
    def __init__(
        self,
        sessions: SessionContextFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.sessions = sessions
        self.clock = clock

    def show(self, user_id: uuid.UUID) -> UserOperationResult:
        with self.sessions() as session:
            user = session.get(AppUser, user_id)
            if user is None:
                raise UserOperationError("user not found")
            count = self._valid_session_count(session, user_id, self.clock())
            return UserOperationResult(
                str(user_id), user.status, user.status, count, "show", "read-only"
            )

    def mutate(
        self, action: str, user_id: uuid.UUID, reason: str, *, apply: bool
    ) -> UserOperationResult:
        allowlist = {
            "suspend": SUSPEND_REASONS,
            "reactivate": REACTIVATE_REASONS,
            "revoke_sessions": REVOKE_REASONS,
            "delete": DELETE_REASONS,
        }.get(action)
        if allowlist is None or reason not in allowlist:
            raise UserOperationError("reason code is not allowed for this action")
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            user = repository.lock_user(user_id) if apply else session.get(AppUser, user_id)
            if user is None:
                raise UserOperationError("user not found")
            prior_status = user.status
            active_count = self._valid_session_count(session, user_id, now)
            if action == "suspend":
                if user.status != "active":
                    raise UserOperationError("user is not active")
                resulting_status = "suspended"
                affected = active_count
                if apply:
                    user.status = "suspended"
                    user.suspended_at = now
                    user.suspension_reason_code = reason
                    user.updated_at = now
                    affected = repository.revoke_active_sessions(
                        user_id, now, "account_suspended"
                    )
                    repository.append_event(
                        event_type="account_suspended",
                        outcome="info",
                        occurred_at=now,
                        user_id=user_id,
                        reason_code=reason,
                        details={"sessions_revoked": affected},
                    )
            elif action == "reactivate":
                if user.status != "suspended":
                    raise UserOperationError("user is not suspended")
                resulting_status = "active"
                affected = 0
                if apply:
                    user.status = "active"
                    user.suspended_at = None
                    user.suspension_reason_code = None
                    user.updated_at = now
                    repository.append_event(
                        event_type="account_reactivated",
                        outcome="info",
                        occurred_at=now,
                        user_id=user_id,
                        reason_code=reason,
                    )
            elif action == "revoke_sessions":
                resulting_status = user.status
                affected = active_count
                if apply:
                    affected = repository.revoke_active_sessions(
                        user_id, now, "security_event"
                    )
                    if affected == 0:
                        raise UserOperationError("user has no active sessions")
                    repository.append_event(
                        event_type="session_revoked",
                        outcome="info",
                        occurred_at=now,
                        user_id=user_id,
                        reason_code=reason,
                        details={"sessions_revoked": affected},
                    )
                elif affected == 0:
                    raise UserOperationError("user has no active sessions")
            else:
                resulting_status = "deleted"
                affected = active_count
                if apply:
                    delete_user_owned_data(session, user_id)
                    repository.append_event(
                        event_type="account_deleted",
                        outcome="success",
                        occurred_at=now,
                        user_id=user_id,
                        reason_code=reason,
                        details={"sessions_revoked": affected},
                    )
                    repository.delete_user(user)
            session.flush()
        return UserOperationResult(
            str(user_id),
            prior_status,
            resulting_status,
            affected,
            action,
            "apply" if apply else "dry-run",
        )

    @staticmethod
    def _valid_session_count(session: Session, user_id: uuid.UUID, now: datetime) -> int:
        return int(
            session.scalar(
                select(func.count()).select_from(UserSession).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.idle_expires_at > now,
                    UserSession.absolute_expires_at > now,
                )
            )
            or 0
        )
