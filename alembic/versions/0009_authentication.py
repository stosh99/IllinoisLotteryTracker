"""Add local Google identities, OIDC attempts, sessions, and auth audit events."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_authentication"
down_revision: str | None = "0008_review_remediations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspension_reason_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "(status = 'active' AND suspended_at IS NULL AND suspension_reason_code IS NULL) OR "
            "(status = 'suspended' AND suspended_at IS NOT NULL AND "
            "suspension_reason_code IN ('abuse','suspected_compromise','legal_request',"
            "'user_request','test_account','operator_correction'))",
            name="ck_app_users_status_shape",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_app_users_updated_at"),
        sa.CheckConstraint(
            "last_login_at IS NULL OR last_login_at >= created_at",
            name="ck_app_users_last_login_at",
        ),
        sa.CheckConstraint(
            "suspended_at IS NULL OR suspended_at >= created_at", name="ck_app_users_suspended_at"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider = 'google'", name="ck_user_identities_provider"),
        sa.CheckConstraint(
            "issuer = 'https://accounts.google.com'", name="ck_user_identities_issuer"
        ),
        sa.CheckConstraint("email_verified", name="ck_user_identities_email_verified"),
        sa.CheckConstraint(
            "subject ~ '^[!-~]+$' AND octet_length(subject) <= 255",
            name="ck_user_identities_subject",
        ),
        sa.CheckConstraint(
            "NULLIF(btrim(email), '') IS NOT NULL AND email = btrim(email)",
            name="ck_user_identities_email",
        ),
        sa.CheckConstraint(
            "last_authenticated_at >= created_at", name="ck_user_identities_authenticated_at"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(32), nullable=True),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_user_sessions_digest"),
        sa.CheckConstraint(
            "created_at <= last_seen_at AND last_seen_at <= idle_expires_at AND "
            "idle_expires_at <= absolute_expires_at AND created_at < idle_expires_at",
            name="ck_user_sessions_timestamps",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revocation_reason IS NULL)",
            name="ck_user_sessions_revocation_shape",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_user_sessions_revoked_at"
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN "
            "('logout','logout_all','session_limit','account_suspended','account_deleted',"
            "'security_event','replaced','expired_idle','expired_absolute')",
            name="ck_user_sessions_revocation_reason",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        "ix_user_sessions_user_active",
        "user_sessions",
        ["user_id", "revoked_at", "absolute_expires_at"],
    )
    op.create_index(
        "ix_user_sessions_expiry", "user_sessions", ["idle_expires_at", "absolute_expires_at"]
    )

    op.create_table(
        "oidc_login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("browser_binding_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("nonce_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("pkce_verifier_ciphertext", sa.String(256), nullable=False),
        sa.Column("return_path", sa.String(512), server_default="/", nullable=False),
        sa.Column("intent", sa.String(24), nullable=False),
        sa.Column("expected_user_id", sa.Uuid(), nullable=True),
        sa.Column("expected_session_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.CheckConstraint("provider = 'google'", name="ck_oidc_attempts_provider"),
        sa.CheckConstraint(
            "octet_length(state_digest) = 32 AND "
            "octet_length(browser_binding_digest) = 32 AND octet_length(nonce_digest) = 32",
            name="ck_oidc_attempts_digests",
        ),
        sa.CheckConstraint("return_path IN ('/', '/account')", name="ck_oidc_attempts_return_path"),
        sa.CheckConstraint(
            "pkce_verifier_ciphertext ~ '^v1[.][A-Za-z0-9_-]{152}$'",
            name="ck_oidc_attempts_pkce_envelope",
        ),
        sa.CheckConstraint(
            "status IN "
            "('pending','exchanging','succeeded','failed','denied','expired','superseded')",
            name="ck_oidc_attempts_status",
        ),
        sa.CheckConstraint("intent IN ('login','reauth_delete')", name="ck_oidc_attempts_intent"),
        sa.CheckConstraint(
            "(intent = 'login' AND expected_user_id IS NULL AND expected_session_id IS NULL) OR "
            "(intent = 'reauth_delete' AND expected_user_id IS NOT NULL AND "
            "expected_session_id IS NOT NULL)",
            name="ck_oidc_attempts_intent_shape",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_oidc_attempts_expiry"),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "(claimed_at IS NULL OR claimed_at >= created_at) AND "
            "(completed_at IS NULL OR completed_at >= created_at) AND "
            "(claimed_at IS NULL OR completed_at IS NULL OR completed_at >= claimed_at)",
            name="ck_oidc_attempts_timestamps",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('user_denied','attempt_expired','attempt_superseded','invalid_callback',"
            "'provider_unavailable','token_exchange_failed','token_validation_failed',"
            "'attempt_decryption_failed','exchange_abandoned','identity_mismatch',"
            "'account_unavailable')",
            name="ck_oidc_attempts_failure_code",
        ),
        sa.ForeignKeyConstraint(["expected_user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["expected_session_id"], ["user_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_digest"),
        sa.UniqueConstraint("browser_binding_digest"),
    )
    op.create_index(
        "ix_oidc_attempts_status_expiry", "oidc_login_attempts", ["status", "expires_at"]
    )
    op.create_index(
        "ix_oidc_attempts_expected_user", "oidc_login_attempts", ["expected_user_id"]
    )
    op.create_index(
        "ix_oidc_attempts_expected_session", "oidc_login_attempts", ["expected_session_id"]
    )

    op.create_table(
        "auth_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('login_started','login_succeeded','login_failed','reauth_started',"
            "'reauth_succeeded','reauth_failed','logout','logout_all','session_revoked',"
            "'session_rejected','account_suspended','account_reactivated','account_deleted')",
            name="ck_auth_events_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('success','failure','info')", name="ck_auth_events_outcome"
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN "
            "('user_denied','attempt_expired','attempt_superseded','invalid_callback',"
            "'provider_unavailable','token_exchange_failed','token_validation_failed',"
            "'attempt_decryption_failed','exchange_abandoned','identity_mismatch',"
            "'account_unavailable','session_limit','account_suspended','security_event',"
            "'replaced','expired_idle','expired_absolute','session_invalid','csrf_invalid',"
            "'rate_limited','abuse','suspected_compromise','legal_request','user_request',"
            "'test_account','operator_correction','review_cleared','test_complete')",
            name="ck_auth_events_reason",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object' AND octet_length(details::text) <= 2048",
            name="ck_auth_events_details_shape",
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["oidc_login_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["user_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_events_occurred_at", "auth_events", ["occurred_at"])
    op.create_index(
        "ix_auth_events_type_outcome_time",
        "auth_events",
        ["event_type", "outcome", "occurred_at"],
    )
    op.create_index("ix_auth_events_user_time", "auth_events", ["user_id", "occurred_at"])
    op.create_index("ix_auth_events_session", "auth_events", ["session_id"])
    op.create_index("ix_auth_events_attempt", "auth_events", ["attempt_id"])
    op.create_index("ix_auth_events_request", "auth_events", ["request_id"])


def downgrade() -> None:
    op.drop_table("auth_events")
    op.drop_table("oidc_login_attempts")
    op.drop_table("user_sessions")
    op.drop_table("user_identities")
    op.drop_table("app_users")
