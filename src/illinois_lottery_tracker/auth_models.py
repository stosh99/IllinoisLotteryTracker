"""SQLAlchemy models for local users, OIDC attempts, and revocable sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import JSON_DOCUMENT, Base

USER_STATUSES = ("active", "suspended")
ATTEMPT_STATUSES = (
    "pending",
    "exchanging",
    "succeeded",
    "failed",
    "denied",
    "expired",
    "superseded",
)
ATTEMPT_FAILURE_CODES = (
    "user_denied",
    "attempt_expired",
    "attempt_superseded",
    "invalid_callback",
    "provider_unavailable",
    "token_exchange_failed",
    "token_validation_failed",
    "attempt_decryption_failed",
    "exchange_abandoned",
    "identity_mismatch",
    "account_unavailable",
)
SESSION_REVOCATION_REASONS = (
    "logout",
    "logout_all",
    "session_limit",
    "account_suspended",
    "account_deleted",
    "security_event",
    "replaced",
    "expired_idle",
    "expired_absolute",
)
AUTH_EVENT_TYPES = (
    "login_started",
    "login_succeeded",
    "login_failed",
    "reauth_started",
    "reauth_succeeded",
    "reauth_failed",
    "logout",
    "logout_all",
    "session_revoked",
    "session_rejected",
    "account_suspended",
    "account_reactivated",
    "account_deleted",
)
AUTH_REASON_CODES = ATTEMPT_FAILURE_CODES + (
    "session_limit",
    "account_suspended",
    "security_event",
    "replaced",
    "expired_idle",
    "expired_absolute",
    "session_invalid",
    "csrf_invalid",
    "rate_limited",
    "abuse",
    "suspected_compromise",
    "legal_request",
    "user_request",
    "test_account",
    "operator_correction",
    "review_cleared",
    "test_complete",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


SESSION_REVOCATION_REASONS_SQL = _sql_list(SESSION_REVOCATION_REASONS)


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(
            "(status = 'active' AND suspended_at IS NULL AND suspension_reason_code IS NULL) OR "
            "(status = 'suspended' AND suspended_at IS NOT NULL AND "
            "suspension_reason_code IN ('abuse','suspected_compromise','legal_request',"
            "'user_request','test_account','operator_correction'))",
            name="ck_app_users_status_shape",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_app_users_updated_at"),
        CheckConstraint(
            "last_login_at IS NULL OR last_login_at >= created_at",
            name="ck_app_users_last_login_at",
        ),
        CheckConstraint(
            "suspended_at IS NULL OR suspended_at >= created_at",
            name="ck_app_users_suspended_at",
        ),
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
        UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
        CheckConstraint("provider = 'google'", name="ck_user_identities_provider"),
        CheckConstraint(
            "issuer = 'https://accounts.google.com'", name="ck_user_identities_issuer"
        ),
        CheckConstraint("email_verified", name="ck_user_identities_email_verified"),
        CheckConstraint(
            "subject ~ '^[!-~]+$' AND octet_length(subject) <= 255",
            name="ck_user_identities_subject",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "NULLIF(btrim(email), '') IS NOT NULL AND email = btrim(email)",
            name="ck_user_identities_email",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "last_authenticated_at >= created_at", name="ck_user_identities_authenticated_at"
        ),
        Index("ix_user_identities_user_id", "user_id"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        CheckConstraint(
            "octet_length(token_digest) = 32", name="ck_user_sessions_digest"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "created_at <= last_seen_at AND last_seen_at <= idle_expires_at AND "
            "idle_expires_at <= absolute_expires_at AND created_at < idle_expires_at",
            name="ck_user_sessions_timestamps",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revocation_reason IS NULL)",
            name="ck_user_sessions_revocation_shape",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_user_sessions_revoked_at"
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR "
            f"revocation_reason IN ({SESSION_REVOCATION_REASONS_SQL})",
            name="ck_user_sessions_revocation_reason",
        ),
        Index("ix_user_sessions_user_active", "user_id", "revoked_at", "absolute_expires_at"),
        Index("ix_user_sessions_expiry", "idle_expires_at", "absolute_expires_at"),
    )


class OidcLoginAttempt(Base):
    __tablename__ = "oidc_login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    state_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    browser_binding_digest: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False, unique=True
    )
    nonce_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    pkce_verifier_ciphertext: Mapped[str] = mapped_column(String(256), nullable=False)
    return_path: Mapped[str] = mapped_column(String(512), nullable=False, server_default="/")
    intent: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE")
    )
    expected_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("provider = 'google'", name="ck_oidc_attempts_provider"),
        CheckConstraint(
            "octet_length(state_digest) = 32 AND "
            "octet_length(browser_binding_digest) = 32 AND octet_length(nonce_digest) = 32",
            name="ck_oidc_attempts_digests",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("return_path IN ('/', '/account')", name="ck_oidc_attempts_return_path"),
        CheckConstraint(
            "pkce_verifier_ciphertext ~ '^v1[.][A-Za-z0-9_-]{152}$'",
            name="ck_oidc_attempts_pkce_envelope",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            f"status IN ({_sql_list(ATTEMPT_STATUSES)})", name="ck_oidc_attempts_status"
        ),
        CheckConstraint("intent IN ('login', 'reauth_delete')", name="ck_oidc_attempts_intent"),
        CheckConstraint(
            "(intent = 'login' AND expected_user_id IS NULL AND expected_session_id IS NULL) OR "
            "(intent = 'reauth_delete' AND expected_user_id IS NOT NULL AND "
            "expected_session_id IS NOT NULL)",
            name="ck_oidc_attempts_intent_shape",
        ),
        CheckConstraint("expires_at > created_at", name="ck_oidc_attempts_expiry"),
        CheckConstraint(
            "(status = 'pending' AND claimed_at IS NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'exchanging' AND claimed_at IS NOT NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'succeeded' AND claimed_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status IN ('failed','denied') AND claimed_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
            "(status IN ('expired','superseded') AND claimed_at IS NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_oidc_attempts_lifecycle",
        ),
        CheckConstraint(
            "(claimed_at IS NULL OR claimed_at >= created_at) AND "
            "(completed_at IS NULL OR completed_at >= created_at) AND "
            "(claimed_at IS NULL OR completed_at IS NULL OR completed_at >= claimed_at)",
            name="ck_oidc_attempts_timestamps",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_sql_list(ATTEMPT_FAILURE_CODES)})",
            name="ck_oidc_attempts_failure_code",
        ),
        Index("ix_oidc_attempts_status_expiry", "status", "expires_at"),
        Index("ix_oidc_attempts_expected_user", "expected_user_id"),
        Index("ix_oidc_attempts_expected_session", "expected_session_id"),
    )


class AuthEvent(Base):
    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "app_users.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"
        )
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "user_sessions.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"
        )
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "oidc_login_attempts.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"
        )
    )
    reason_code: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict, server_default=text("'{}'")
    )

    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_sql_list(AUTH_EVENT_TYPES)})", name="ck_auth_events_type"
        ),
        CheckConstraint("outcome IN ('success','failure','info')", name="ck_auth_events_outcome"),
        CheckConstraint(
            f"reason_code IS NULL OR reason_code IN ({_sql_list(AUTH_REASON_CODES)})",
            name="ck_auth_events_reason",
        ),
        CheckConstraint(
            "jsonb_typeof(details) = 'object' AND octet_length(details::text) <= 2048",
            name="ck_auth_events_details_shape",
        ).ddl_if(dialect="postgresql"),
        Index("ix_auth_events_occurred_at", "occurred_at"),
        Index("ix_auth_events_type_outcome_time", "event_type", "outcome", "occurred_at"),
        Index("ix_auth_events_user_time", "user_id", "occurred_at"),
        Index("ix_auth_events_session", "session_id"),
        Index("ix_auth_events_attempt", "attempt_id"),
        Index("ix_auth_events_request", "request_id"),
    )
