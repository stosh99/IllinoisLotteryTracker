"""Persistence operations for authentication services.

Methods flush but never commit.  The caller owns the transaction boundary.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..auth_models import (
    AUTH_EVENT_TYPES,
    AUTH_REASON_CODES,
    AppUser,
    AuthEvent,
    OidcLoginAttempt,
    UserIdentity,
    UserSession,
)

EVENT_OUTCOMES = frozenset({"success", "failure", "info"})
EVENT_DETAIL_KEYS = frozenset(
    {"provider", "intent", "sessions_revoked", "http_status_class", "duration_bucket_ms"}
)
EVENT_DURATION_BUCKETS = frozenset({100, 250, 500, 1000, 2500, 5000, 10000, 10001})


def validate_event_fields(
    event_type: str, outcome: str, reason_code: str | None, details: dict | None
) -> dict:
    """Validate the positive, non-PII auth-event contract before persistence."""

    document = {} if details is None else details
    if event_type not in AUTH_EVENT_TYPES or outcome not in EVENT_OUTCOMES:
        raise ValueError("invalid authentication event")
    if reason_code is not None and reason_code not in AUTH_REASON_CODES:
        raise ValueError("invalid authentication event reason")
    if not isinstance(document, dict) or not set(document) <= EVENT_DETAIL_KEYS:
        raise ValueError("invalid authentication event details")
    if "provider" in document and document["provider"] != "google":
        raise ValueError("invalid authentication event provider")
    if "intent" in document and document["intent"] not in {"login", "reauth_delete"}:
        raise ValueError("invalid authentication event intent")
    if "sessions_revoked" in document and (
        type(document["sessions_revoked"]) is not int
        or not 0 <= document["sessions_revoked"] <= 10
    ):
        raise ValueError("invalid authentication event session count")
    if "http_status_class" in document and document["http_status_class"] not in {
        "4xx",
        "5xx",
    }:
        raise ValueError("invalid authentication event HTTP class")
    if (
        "duration_bucket_ms" in document
        and document["duration_bucket_ms"] not in EVENT_DURATION_BUCKETS
    ):
        raise ValueError("invalid authentication event duration bucket")
    if len(json.dumps(document, separators=(",", ":"), sort_keys=True).encode()) > 2048:
        raise ValueError("authentication event details are too large")
    return document


class AuthRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row

    def identity_by_subject(self, issuer: str, subject: str) -> UserIdentity | None:
        return self.session.scalar(
            select(UserIdentity).where(
                UserIdentity.issuer == issuer, UserIdentity.subject == subject
            )
        )

    def lock_user(self, user_id: uuid.UUID) -> AppUser | None:
        return self.session.scalar(
            select(AppUser).where(AppUser.id == user_id).with_for_update()
        )

    def user_by_id(self, user_id: uuid.UUID) -> AppUser | None:
        return self.session.get(AppUser, user_id)

    def attempt_by_state_for_update(self, state_digest: bytes) -> OidcLoginAttempt | None:
        return self.session.scalar(
            select(OidcLoginAttempt)
            .where(OidcLoginAttempt.state_digest == state_digest)
            .with_for_update()
        )

    def attempt_by_id_for_update(self, attempt_id: uuid.UUID) -> OidcLoginAttempt | None:
        return self.session.scalar(
            select(OidcLoginAttempt)
            .where(OidcLoginAttempt.id == attempt_id)
            .with_for_update()
        )

    def attempt_by_binding_for_update(self, binding_digest: bytes) -> OidcLoginAttempt | None:
        return self.session.scalar(
            select(OidcLoginAttempt)
            .where(OidcLoginAttempt.browser_binding_digest == binding_digest)
            .with_for_update()
        )

    def session_by_digest(self, digest: bytes, *, for_update: bool = False) -> UserSession | None:
        query: Select[tuple[UserSession]] = select(UserSession).where(
            UserSession.token_digest == digest
        )
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def session_by_id_owned_for_update(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserSession | None:
        return self.session.scalar(
            select(UserSession)
            .where(UserSession.id == session_id, UserSession.user_id == user_id)
            .with_for_update()
        )

    def active_sessions_for_update(
        self, user_id: uuid.UUID, now: datetime
    ) -> list[UserSession]:
        return list(
            self.session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.idle_expires_at > now,
                    UserSession.absolute_expires_at > now,
                )
                .order_by(UserSession.created_at, UserSession.id)
                .with_for_update()
            )
        )

    def active_sessions(self, user_id: uuid.UUID, now: datetime) -> list[UserSession]:
        return list(
            self.session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.idle_expires_at > now,
                    UserSession.absolute_expires_at > now,
                )
                .order_by(UserSession.created_at.desc(), UserSession.id)
            )
        )

    def principal_rows(self, digest: bytes):
        return self.session.execute(
            select(UserSession, AppUser, UserIdentity)
            .join(AppUser, AppUser.id == UserSession.user_id)
            .join(UserIdentity, UserIdentity.user_id == AppUser.id)
            .where(
                UserSession.token_digest == digest,
                UserIdentity.provider == "google",
            )
        ).one_or_none()

    def append_event(
        self,
        *,
        event_type: str,
        outcome: str,
        occurred_at: datetime,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        attempt_id: uuid.UUID | None = None,
        reason_code: str | None = None,
        request_id: uuid.UUID | None = None,
        details: dict | None = None,
    ) -> AuthEvent:
        validated_details = validate_event_fields(event_type, outcome, reason_code, details)
        return self.add(
            AuthEvent(
                event_type=event_type,
                outcome=outcome,
                occurred_at=occurred_at,
                user_id=user_id,
                session_id=session_id,
                attempt_id=attempt_id,
                reason_code=reason_code,
                request_id=request_id,
                details=validated_details,
            )
        )

    def delete_user(self, user: AppUser) -> None:
        self.session.delete(user)
        self.session.flush()

    def revoke_active_sessions(
        self, user_id: uuid.UUID, now: datetime, reason: str
    ) -> int:
        rows = self.active_sessions_for_update(user_id, now)
        for row in rows:
            row.revoked_at = now
            row.revocation_reason = reason
        self.session.flush()
        return len(rows)
