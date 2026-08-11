from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from illinois_lottery_tracker.auth.maintenance import AuthenticationMaintenance
from illinois_lottery_tracker.auth_models import (
    AppUser,
    AuthEvent,
    OidcLoginAttempt,
    UserSession,
)


@pytest.fixture()
def auth_sessions():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    factory = sessionmaker(engine, expire_on_commit=False, future=True)

    @contextmanager
    def sessions():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    yield engine, sessions
    engine.dispose()


def _attempt(status: str, created: datetime, *, completed=None) -> OidcLoginAttempt:
    return OidcLoginAttempt(
        id=uuid.uuid4(),
        provider="google",
        state_digest=os.urandom(32),
        browser_binding_digest=os.urandom(32),
        nonce_digest=os.urandom(32),
        pkce_verifier_ciphertext="v1." + "A" * 152,
        return_path="/",
        intent="login",
        status=status,
        created_at=created,
        expires_at=created + timedelta(minutes=10),
        claimed_at=(
            created + timedelta(minutes=1)
            if status in {"exchanging", "succeeded"}
            else None
        ),
        completed_at=completed,
    )


def test_postgres_maintenance_applies_in_bounded_idempotent_batches(auth_sessions) -> None:
    engine, sessions = auth_sessions
    now = datetime.now(UTC).replace(microsecond=0)
    user_id = uuid.uuid4()
    with sessions() as session:
        session.add(
            AppUser(
                id=user_id,
                status="active",
                created_at=now - timedelta(days=100),
                updated_at=now - timedelta(days=100),
            )
        )
        session.flush()
        session.add(
            UserSession(
                id=uuid.uuid4(),
                user_id=user_id,
                token_digest=os.urandom(32),
                created_at=now - timedelta(days=40),
                last_seen_at=now - timedelta(days=39),
                idle_expires_at=now - timedelta(days=35),
                absolute_expires_at=now - timedelta(days=33),
            )
        )
        session.add_all(
            [
                _attempt("pending", now - timedelta(minutes=20)),
                _attempt("exchanging", now - timedelta(minutes=20)),
                _attempt(
                    "succeeded",
                    now - timedelta(days=2),
                    completed=now - timedelta(hours=25),
                ),
                AuthEvent(
                    occurred_at=now - timedelta(days=91),
                    event_type="login_started",
                    outcome="info",
                    details={},
                ),
            ]
        )

    result = AuthenticationMaintenance(sessions, clock=lambda: now, batch_size=1).run(
        apply=True
    )
    assert result.attempts_expired == 1
    assert result.exchanges_abandoned == 1
    assert result.attempts_deleted == 1
    assert result.sessions_expired == 1
    assert result.sessions_deleted == 1
    assert result.events_deleted == 1
    assert AuthenticationMaintenance(sessions, clock=lambda: now).run(apply=True).document(
        mode="apply"
    ) == {
        "mode": "apply",
        "attempts_expired": 0,
        "exchanges_abandoned": 0,
        "attempts_deleted": 0,
        "sessions_expired": 0,
        "sessions_deleted": 0,
        "events_deleted": 0,
    }
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM oidc_login_attempts WHERE "
                "(status='pending' AND expires_at <= now()) OR "
                "(status='exchanging' AND expires_at + interval '30 seconds' <= now())"
            )
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM auth_events WHERE occurred_at < now()-interval '90 days'")
        ) == 0
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_events"))
        connection.execute(text("DELETE FROM oidc_login_attempts"))
        connection.execute(text("DELETE FROM user_sessions"))
        connection.execute(text("DELETE FROM user_identities"))
        connection.execute(text("DELETE FROM app_users"))
