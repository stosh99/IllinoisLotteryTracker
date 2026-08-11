from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import illinois_lottery_tracker.auth.service as service_module
from illinois_lottery_tracker.auth.config import load_auth_settings
from illinois_lottery_tracker.auth.crypto import token_digest
from illinois_lottery_tracker.auth.service import ClaimedAttempt, SessionService
from illinois_lottery_tracker.auth.types import VerifiedIdentity
from illinois_lottery_tracker.auth_models import (
    AppUser,
    OidcLoginAttempt,
    UserIdentity,
    UserSession,
)

from .fakes import FakeSession, fake_session_context

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _settings():
    root = base64.urlsafe_b64encode(bytes([8]) * 32).rstrip(b"=").decode()
    return load_auth_settings(
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


class Store:
    def __init__(self):
        self.attempt = OidcLoginAttempt(
            id=uuid.uuid4(),
            provider="google",
            state_digest=bytes([1]) * 32,
            browser_binding_digest=bytes([2]) * 32,
            nonce_digest=bytes([3]) * 32,
            pkce_verifier_ciphertext="v1." + "A" * 152,
            return_path="/",
            intent="login",
            status="exchanging",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
            claimed_at=NOW,
        )
        self.user: AppUser | None = None
        self.identity: UserIdentity | None = None
        self.sessions: list[UserSession] = []
        self.events: list[dict] = []


class FakeRepository:
    store = Store()

    def __init__(self, session):
        self.session = session

    def attempt_by_id_for_update(self, attempt_id):
        return self.store.attempt if self.store.attempt.id == attempt_id else None

    def identity_by_subject(self, issuer, subject):
        identity = self.store.identity
        if identity and identity.issuer == issuer and identity.subject == subject:
            return identity
        return None

    def add(self, row):
        if isinstance(row, AppUser):
            self.store.user = row
        elif isinstance(row, UserIdentity):
            self.store.identity = row
        elif isinstance(row, UserSession):
            self.store.sessions.append(row)
        return row

    def lock_user(self, user_id):
        return self.store.user if self.store.user and self.store.user.id == user_id else None

    def active_sessions_for_update(self, user_id, now):
        return sorted(
            [
                row
                for row in self.store.sessions
                if row.user_id == user_id
                and row.revoked_at is None
                and row.idle_expires_at > now
                and row.absolute_expires_at > now
            ],
            key=lambda row: (row.created_at, row.id),
        )

    def append_event(self, **values):
        self.store.events.append(values)
        return SimpleNamespace(**values)

    def principal_rows(self, digest):
        for row in self.store.sessions:
            if row.token_digest == digest and self.store.user and self.store.identity:
                return row, self.store.user, self.store.identity
        return None


@pytest.fixture(autouse=True)
def fake_repository(monkeypatch):
    FakeRepository.store = Store()
    monkeypatch.setattr(service_module, "AuthRepository", FakeRepository)


def _service(clock=lambda: NOW) -> SessionService:
    session = FakeSession()
    return SessionService(
        _settings(), lambda: fake_session_context(session), clock=clock
    )


def _claimed() -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id=FakeRepository.store.attempt.id,
        code="code",
        code_verifier="unused",
        nonce_digest=bytes([3]) * 32,
        return_path="/",
        intent="login",
        expected_user_id=None,
        expected_session_id=None,
    )


def _identity() -> VerifiedIdentity:
    return VerifiedIdentity(
        issuer="https://accounts.google.com",
        subject="123456789",
        email="player@example.test",
    )


def test_first_login_issues_only_digest_to_repository() -> None:
    issued = _service().finalize_login(_claimed(), _identity())
    stored = FakeRepository.store.sessions[0]
    assert stored.token_digest == token_digest(issued.token)
    assert issued.token.encode() not in stored.token_digest
    assert FakeRepository.store.attempt.status == "succeeded"
    assert FakeRepository.store.user is not None
    assert FakeRepository.store.identity is not None


def test_sixth_session_revokes_deterministic_oldest() -> None:
    store = FakeRepository.store
    user_id = uuid.uuid4()
    store.user = AppUser(id=user_id, status="active", created_at=NOW, updated_at=NOW)
    store.identity = UserIdentity(
        id=uuid.uuid4(),
        user_id=user_id,
        provider="google",
        issuer="https://accounts.google.com",
        subject="123456789",
        email="player@example.test",
        email_verified=True,
        created_at=NOW,
        last_authenticated_at=NOW,
    )
    for index in range(5):
        created = NOW - timedelta(hours=5 - index)
        store.sessions.append(
            UserSession(
                id=uuid.uuid4(),
                user_id=user_id,
                token_digest=bytes([index + 10]) * 32,
                created_at=created,
                last_seen_at=created,
                idle_expires_at=NOW + timedelta(hours=2),
                absolute_expires_at=NOW + timedelta(days=1),
            )
        )
    oldest = min(store.sessions, key=lambda row: (row.created_at, row.id))
    _service().finalize_login(_claimed(), _identity())
    assert oldest.revocation_reason == "session_limit"
    assert sum(row.revoked_at is None for row in store.sessions) == 5


def test_resolve_touches_idle_but_not_absolute_deadline() -> None:
    issued = _service().finalize_login(_claimed(), _identity())
    row = FakeRepository.store.sessions[0]
    absolute = row.absolute_expires_at
    later = NOW + timedelta(minutes=6)
    principal = _service(clock=lambda: later).resolve_principal(issued.token)
    assert principal is not None
    assert row.last_seen_at == later
    assert row.absolute_expires_at == absolute


def test_expired_session_is_revoked() -> None:
    issued = _service().finalize_login(_claimed(), _identity())
    row = FakeRepository.store.sessions[0]
    row.idle_expires_at = NOW + timedelta(minutes=1)
    principal = _service(clock=lambda: NOW + timedelta(minutes=2)).resolve_principal(issued.token)
    assert principal is None
    assert row.revocation_reason == "expired_idle"
