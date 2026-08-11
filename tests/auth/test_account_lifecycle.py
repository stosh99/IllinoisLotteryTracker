from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import illinois_lottery_tracker.auth.service as service_module
from illinois_lottery_tracker.auth.config import load_auth_settings
from illinois_lottery_tracker.auth.service import (
    AccountDeletionError,
    AccountService,
    ClaimedAttempt,
    LoginAttemptError,
    LoginAttemptService,
    SessionService,
)
from illinois_lottery_tracker.auth.types import AuthPrincipal, VerifiedIdentity
from illinois_lottery_tracker.auth_models import (
    AppUser,
    OidcLoginAttempt,
    UserIdentity,
    UserSession,
)

from .fakes import FakeSession, fake_session_context

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _settings():
    root = base64.urlsafe_b64encode(bytes([6]) * 32).rstrip(b"=").decode()
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
    def __init__(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        self.user = AppUser(id=user_id, status="active", created_at=NOW, updated_at=NOW)
        self.identity = UserIdentity(
            id=uuid.uuid4(),
            user_id=user_id,
            provider="google",
            issuer="https://accounts.google.com",
            subject="subject-one",
            email="player@example.test",
            email_verified=True,
            created_at=NOW,
            last_authenticated_at=NOW,
        )
        self.sessions = [
            UserSession(
                id=session_id,
                user_id=user_id,
                token_digest=bytes([1]) * 32,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(days=1),
                absolute_expires_at=NOW + timedelta(days=7),
            )
        ]
        self.attempts: list[OidcLoginAttempt] = []
        self.events: list[dict] = []
        self.deleted = False


class FakeRepository:
    store = Store()

    def __init__(self, _session):
        pass

    def add(self, row):
        if isinstance(row, OidcLoginAttempt):
            self.store.attempts.append(row)
        elif isinstance(row, UserSession):
            self.store.sessions.append(row)
        return row

    def append_event(self, **values):
        self.store.events.append(values)
        return SimpleNamespace(**values)

    def lock_user(self, user_id):
        return self.store.user if self.store.user.id == user_id and not self.store.deleted else None

    def user_by_id(self, user_id):
        return self.lock_user(user_id)

    def session_by_id_owned_for_update(self, session_id, user_id):
        return next(
            (row for row in self.store.sessions if row.id == session_id and row.user_id == user_id),
            None,
        )

    def attempt_by_binding_for_update(self, digest):
        return next(
            (row for row in self.store.attempts if row.browser_binding_digest == digest),
            None,
        )

    def attempt_by_id_for_update(self, attempt_id):
        return next((row for row in self.store.attempts if row.id == attempt_id), None)

    def identity_by_subject(self, issuer, subject):
        identity = self.store.identity
        return identity if identity.issuer == issuer and identity.subject == subject else None

    def delete_user(self, _user):
        self.store.deleted = True


class FakeProvider:
    def __init__(self) -> None:
        self.values: dict | None = None

    def build_authorization_url(self, **values):
        self.values = values
        return "https://accounts.google.com/o/oauth2/v2/auth?safe=one"


@pytest.fixture(autouse=True)
def fake_repository(monkeypatch):
    FakeRepository.store = Store()
    monkeypatch.setattr(service_module, "AuthRepository", FakeRepository)


def _context():
    return fake_session_context(FakeSession())


def _principal() -> AuthPrincipal:
    store = FakeRepository.store
    row = store.sessions[0]
    return AuthPrincipal(
        user_id=store.user.id,
        session_id=row.id,
        email=store.identity.email,
        session_created_at=row.created_at,
        idle_expires_at=row.idle_expires_at,
        absolute_expires_at=row.absolute_expires_at,
    )


def test_reauth_start_is_bound_to_user_session_and_select_account() -> None:
    provider = FakeProvider()
    service = LoginAttemptService(_settings(), provider, _context, clock=lambda: NOW)
    started = service.start_reauth_delete(_principal())
    attempt = FakeRepository.store.attempts[0]
    assert started.authorization_url.startswith("https://accounts.google.com/")
    assert provider.values is not None and provider.values["prompt"] == "select_account"
    assert attempt.intent == "reauth_delete"
    assert attempt.return_path == "/account"
    assert attempt.expected_user_id == _principal().user_id
    assert attempt.expected_session_id == _principal().session_id


def _claimed() -> ClaimedAttempt:
    store = FakeRepository.store
    attempt = OidcLoginAttempt(
        id=uuid.uuid4(),
        provider="google",
        state_digest=bytes([2]) * 32,
        browser_binding_digest=bytes([3]) * 32,
        nonce_digest=bytes([4]) * 32,
        pkce_verifier_ciphertext="v1." + "A" * 152,
        return_path="/account",
        intent="reauth_delete",
        expected_user_id=store.user.id,
        expected_session_id=store.sessions[0].id,
        status="exchanging",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        claimed_at=NOW,
    )
    store.attempts.append(attempt)
    return ClaimedAttempt(
        attempt.id,
        "code",
        "verifier",
        attempt.nonce_digest,
        "/account",
        "reauth_delete",
        store.user.id,
        store.sessions[0].id,
    )


def test_reauth_requires_same_subject_and_replaces_session() -> None:
    claimed = _claimed()
    prior = FakeRepository.store.sessions[0]
    service = SessionService(
        _settings(), _context, clock=lambda: NOW + timedelta(minutes=2)
    )
    issued = service.finalize_reauthentication(
        claimed,
        VerifiedIdentity(
            "https://accounts.google.com", "subject-one", "updated@example.test"
        ),
    )
    assert prior.revocation_reason == "replaced"
    assert issued.session_id != prior.id
    assert issued.email == "updated@example.test"
    assert FakeRepository.store.attempts[0].status == "succeeded"


def test_reauth_rejects_same_email_from_another_subject() -> None:
    claimed = _claimed()
    with pytest.raises(LoginAttemptError) as caught:
        SessionService(
            _settings(), _context, clock=lambda: NOW + timedelta(minutes=2)
        ).finalize_reauthentication(
            claimed,
            VerifiedIdentity(
                "https://accounts.google.com", "other-subject", "player@example.test"
            ),
        )
    assert getattr(caught.value, "reason_code", None) == "identity_mismatch"
    assert FakeRepository.store.sessions[0].revoked_at is None


def test_delete_requires_recent_auth_and_runs_future_data_seam(monkeypatch) -> None:
    service = AccountService(_settings(), _context, clock=lambda: NOW + timedelta(minutes=11))
    with pytest.raises(AccountDeletionError) as stale:
        service.delete_account(_principal())
    assert stale.value.code == "RECENT_AUTH_REQUIRED"

    deleted: list[uuid.UUID] = []
    monkeypatch.setattr(
        service_module,
        "delete_user_owned_data",
        lambda _session, user_id: deleted.append(user_id),
    )
    service = AccountService(_settings(), _context, clock=lambda: NOW + timedelta(minutes=9))
    service.delete_account(_principal())
    assert deleted == [_principal().user_id]
    assert FakeRepository.store.deleted is True
    assert FakeRepository.store.events[-1]["event_type"] == "account_deleted"
