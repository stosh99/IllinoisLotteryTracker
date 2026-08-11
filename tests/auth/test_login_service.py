from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import illinois_lottery_tracker.auth.service as service_module
from illinois_lottery_tracker.auth.config import load_auth_settings
from illinois_lottery_tracker.auth.crypto import token_digest
from illinois_lottery_tracker.auth.service import LoginAttemptError, LoginAttemptService

from .fakes import FakeSession, MemoryStore, fake_session_context

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _settings():
    root = base64.urlsafe_b64encode(bytes([5]) * 32).rstrip(b"=").decode()
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


class FakeProvider:
    def __init__(self):
        self.calls: list[dict] = []

    def build_authorization_url(self, **values) -> str:
        self.calls.append(values)
        return "https://accounts.google.com/o/oauth2/v2/auth?bounded=test"


class FakeRepository:
    store = MemoryStore()

    def __init__(self, session):
        self.session = session

    def add(self, row):
        if row.__class__.__name__ == "OidcLoginAttempt":
            self.store.attempts.append(row)
        return row

    def append_event(self, **values):
        self.store.events.append(values)
        return SimpleNamespace(**values)

    def attempt_by_binding_for_update(self, digest):
        return next(
            (row for row in self.store.attempts if row.browser_binding_digest == digest), None
        )

    def attempt_by_state_for_update(self, digest):
        return next((row for row in self.store.attempts if row.state_digest == digest), None)


@pytest.fixture(autouse=True)
def fake_repository(monkeypatch):
    FakeRepository.store = MemoryStore()
    monkeypatch.setattr(service_module, "AuthRepository", FakeRepository)


def _service() -> tuple[LoginAttemptService, FakeProvider]:
    provider = FakeProvider()
    session = FakeSession()
    service = LoginAttemptService(
        _settings(),
        provider,
        lambda: fake_session_context(session),
        clock=lambda: NOW,
    )
    return service, provider


def test_start_stores_digests_encrypted_verifier_and_minimal_url() -> None:
    service, provider = _service()
    result = service.start_login("/")
    attempt = FakeRepository.store.attempts[0]
    assert result.authorization_url.startswith("https://accounts.google.com/")
    assert attempt.state_digest == token_digest(provider.calls[0]["state"])
    assert attempt.browser_binding_digest == token_digest(result.browser_binding)
    assert attempt.pkce_verifier_ciphertext.startswith("v1.")
    assert len(FakeRepository.store.events) == 1


def test_second_start_supersedes_pending_attempt() -> None:
    service, _ = _service()
    first = service.start_login("/")
    service.start_login("/account", previous_binding=first.browser_binding)
    assert FakeRepository.store.attempts[0].status == "superseded"
    assert FakeRepository.store.attempts[1].status == "pending"


def test_callback_claim_is_one_time_and_decrypts_verifier() -> None:
    service, provider = _service()
    started = service.start_login("/account")
    state = provider.calls[0]["state"]
    claimed = service.claim_callback(
        state=state,
        browser_binding=started.browser_binding,
        code="code",
        error=None,
        issuer="https://accounts.google.com",
    )
    assert claimed.return_path == "/account"
    assert len(claimed.code_verifier) == 86
    assert FakeRepository.store.attempts[0].status == "exchanging"
    with pytest.raises(LoginAttemptError, match="invalid_callback"):
        service.claim_callback(
            state=state,
            browser_binding=started.browser_binding,
            code="code",
            error=None,
            issuer=None,
        )


def test_access_denied_is_terminal_and_recorded() -> None:
    service, provider = _service()
    started = service.start_login("/")
    with pytest.raises(LoginAttemptError) as caught:
        service.claim_callback(
            state=provider.calls[0]["state"],
            browser_binding=started.browser_binding,
            code=None,
            error="access_denied",
            issuer=None,
        )
    assert caught.value.public_result == "cancelled"
    attempt = FakeRepository.store.attempts[0]
    assert attempt.status == "denied"
    assert attempt.failure_code == "user_denied"


def test_expired_attempt_is_consumed_without_claim() -> None:
    service, provider = _service()
    started = service.start_login("/")
    FakeRepository.store.attempts[0].expires_at = NOW - timedelta(seconds=1)
    with pytest.raises(LoginAttemptError) as caught:
        service.claim_callback(
            state=provider.calls[0]["state"],
            browser_binding=started.browser_binding,
            code="code",
            error=None,
            issuer=None,
        )
    assert caught.value.public_result == "expired"
    assert FakeRepository.store.attempts[0].status == "expired"
