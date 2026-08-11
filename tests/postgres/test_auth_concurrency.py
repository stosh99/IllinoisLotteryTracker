from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.auth.config import load_auth_settings
from illinois_lottery_tracker.auth.repository import AuthRepository
from illinois_lottery_tracker.auth.service import ClaimedAttempt, SessionService
from illinois_lottery_tracker.auth.types import VerifiedIdentity
from illinois_lottery_tracker.auth_models import AppUser, OidcLoginAttempt, UserIdentity


@pytest.fixture(scope="module")
def concurrency_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    yield engine
    engine.dispose()


def test_only_one_concurrent_callback_claims_attempt(concurrency_engine) -> None:
    now = datetime.now(UTC)
    state_digest = bytes([1]) * 32
    with Session(concurrency_engine) as session, session.begin():
        session.add(
            OidcLoginAttempt(
                id=uuid4(),
                provider="google",
                state_digest=state_digest,
                browser_binding_digest=bytes([2]) * 32,
                nonce_digest=bytes([3]) * 32,
                pkce_verifier_ciphertext="v1." + "A" * 152,
                return_path="/",
                intent="login",
                status="pending",
                created_at=now,
                expires_at=now + timedelta(minutes=10),
            )
        )

    barrier = Barrier(2)

    def claim() -> bool:
        with Session(concurrency_engine) as session, session.begin():
            barrier.wait()
            row = AuthRepository(session).attempt_by_state_for_update(state_digest)
            assert row is not None
            if row.status != "pending":
                return False
            row.status = "exchanging"
            row.claimed_at = datetime.now(UTC)
            session.flush()
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]
    with Session(concurrency_engine) as session, session.begin():
        row = session.scalar(
            select(OidcLoginAttempt).where(OidcLoginAttempt.state_digest == state_digest)
        )
        assert row is not None
        session.delete(row)


def test_concurrent_first_login_creates_one_identity_and_no_orphan(concurrency_engine) -> None:
    now = datetime.now(UTC)
    attempts = [
        OidcLoginAttempt(
            id=uuid4(),
            provider="google",
            state_digest=bytes([10 + index]) * 32,
            browser_binding_digest=bytes([20 + index]) * 32,
            nonce_digest=bytes([30 + index]) * 32,
            pkce_verifier_ciphertext="v1." + "A" * 152,
            return_path="/",
            intent="login",
            status="exchanging",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            claimed_at=now,
        )
        for index in range(2)
    ]
    claimed_inputs = [(attempt.id, attempt.nonce_digest) for attempt in attempts]
    with Session(concurrency_engine) as session, session.begin():
        session.add_all(attempts)

    @contextmanager
    def session_scope():
        with Session(concurrency_engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    root = base64.urlsafe_b64encode(bytes([7]) * 32).rstrip(b"=").decode()
    settings = load_auth_settings(
        {
            "AUTH_ENABLED": "true",
            "APP_ENV": "test",
            "PUBLIC_BASE_URL": "http://localhost:5173",
            "GOOGLE_OIDC_CLIENT_ID": "client.apps.googleusercontent.com",
            "GOOGLE_OIDC_CLIENT_SECRET": "test-secret",
            "AUTH_SECRET_KEYS": root,
            "AUTH_TRUSTED_PROXY_HOPS": "none",
        }
    )
    identity = VerifiedIdentity(
        issuer="https://accounts.google.com",
        subject=f"concurrent-{uuid4().hex}",
        email="same@example.test",
    )
    barrier = Barrier(2)

    def finalize(attempt_data: tuple):
        attempt_id, nonce_digest = attempt_data
        barrier.wait()
        return SessionService(settings, session_scope, clock=lambda: now).finalize_login(
            ClaimedAttempt(
                attempt_id=attempt_id,
                code="code",
                code_verifier="unused",
                nonce_digest=nonce_digest,
                return_path="/",
                intent="login",
                expected_user_id=None,
                expected_session_id=None,
            ),
            identity,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        issued = list(executor.map(finalize, claimed_inputs))
    assert issued[0].user_id == issued[1].user_id
    with Session(concurrency_engine) as session, session.begin():
        identities = list(
            session.scalars(
                select(UserIdentity).where(
                    UserIdentity.issuer == identity.issuer,
                    UserIdentity.subject == identity.subject,
                )
            )
        )
        assert len(identities) == 1
        users = list(session.scalars(select(AppUser).where(AppUser.id == identities[0].user_id)))
        assert len(users) == 1
        session.delete(users[0])
