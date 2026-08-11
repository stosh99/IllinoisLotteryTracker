from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from illinois_lottery_tracker import api
from illinois_lottery_tracker.auth.config import AuthSettings
from illinois_lottery_tracker.auth.service import (
    AccountDeletionError,
    AccountRecord,
    ClaimedAttempt,
    LoginStart,
)
from illinois_lottery_tracker.auth_api import AuthRuntime

from .test_auth_routes import (
    RAW_SESSION,
    FakeAttempts,
    FakeProvider,
    FakeSessions,
    _csrf,
    _principal,
    _settings,
)


@dataclass
class FakeAccounts:
    error: str | None = None
    deleted: bool = False

    def read_account(self, principal):
        if self.error:
            raise AccountDeletionError(self.error)
        return AccountRecord(principal.user_id, principal.email, principal.session_created_at)

    def delete_account(self, _principal) -> None:
        if self.error:
            raise AccountDeletionError(self.error)
        self.deleted = True


class ReauthAttempts(FakeAttempts):
    def start_reauth_delete(self, principal, previous_binding):
        self.starts.append((str(principal.user_id), previous_binding))
        return LoginStart(
            "https://accounts.google.com/o/oauth2/v2/auth?prompt=select_account",
            "reauth-browser-binding",
            principal.session_id,
        )

    def claim_callback(self, **values):
        self.claims.append(values)
        principal = _principal()
        return ClaimedAttempt(
            attempt_id=principal.session_id,
            code=str(values["code"]),
            code_verifier="verifier",
            nonce_digest=bytes([2]) * 32,
            return_path="/account",
            intent="reauth_delete",
            expected_user_id=principal.user_id,
            expected_session_id=principal.session_id,
        )


class ReauthSessions(FakeSessions):
    def finalize_reauthentication(self, claimed, identity):
        return self.finalize_login(claimed, identity)


@pytest.fixture(autouse=True)
def clear_runtime():
    yield
    if hasattr(api.app.state, "auth_runtime"):
        del api.app.state.auth_runtime


def _runtime(accounts: FakeAccounts | None = None):
    settings = _settings()
    attempts = ReauthAttempts()
    sessions = ReauthSessions(_principal())
    runtime = AuthRuntime(
        settings=settings,
        provider=FakeProvider(),  # type: ignore[arg-type]
        attempts=attempts,  # type: ignore[arg-type]
        sessions=sessions,  # type: ignore[arg-type]
        accounts=accounts or FakeAccounts(),  # type: ignore[arg-type]
    )
    return runtime, attempts, sessions


def _headers(runtime: AuthRuntime) -> dict[str, str]:
    return {
        "Origin": runtime.settings.public_base_url or "",
        "X-CSRF-Token": _csrf(runtime.settings, _principal()),
        "Content-Type": "application/json",
    }


def test_account_read_exact_contract() -> None:
    runtime, _attempts, _sessions = _runtime()
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        response = client.get("/api/v1/account")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(_principal().user_id),
        "email": "player@example.test",
        "emailVerified": True,
        "createdAt": "2026-08-10T18:30:00Z",
    }
    assert response.headers["cache-control"] == "no-store"


def test_reauth_initializer_requires_csrf_and_returns_one_pinned_url() -> None:
    runtime, attempts, _sessions = _runtime()
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        missing = client.post("/api/v1/auth/google/reauth-delete", json={})
        assert missing.status_code == 403
        response = client.post(
            "/api/v1/auth/google/reauth-delete", content=b"{}", headers=_headers(runtime)
        )
    assert response.status_code == 200
    assert set(response.json()) == {"authorizationUrl"}
    assert response.json()["authorizationUrl"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )
    assert runtime.settings.login_cookie_name in response.headers["set-cookie"]
    assert attempts.starts[0][0] == str(_principal().user_id)


def test_reauth_callback_rotates_cookie_and_returns_clean_account_path() -> None:
    runtime, attempts, _sessions = _runtime()
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        client.cookies.set(runtime.settings.login_cookie_name, "reauth-browser-binding")
        response = client.get(
            "/api/v1/auth/google/callback?state=state&code=provider-code",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/account"
    assert runtime.settings.session_cookie_name in response.headers["set-cookie"]
    assert attempts.claims[0]["principal"] == _principal()
    assert "provider-code" not in response.headers["location"]


def test_delete_contract_confirmation_recent_auth_and_commit() -> None:
    accounts = FakeAccounts(error="RECENT_AUTH_REQUIRED")
    runtime, _attempts, _sessions = _runtime(accounts)
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        mismatch = client.request(
            "DELETE",
            "/api/v1/account",
            content=b'{"confirmation":"no"}',
            headers=_headers(runtime),
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["code"] == "CONFIRMATION_REQUIRED"

        stale = client.request(
            "DELETE",
            "/api/v1/account",
            content=b'{"confirmation":"DELETE MY ACCOUNT"}',
            headers=_headers(runtime),
        )
        assert stale.status_code == 403
        assert stale.json()["code"] == "RECENT_AUTH_REQUIRED"

        accounts.error = None
        deleted = client.request(
            "DELETE",
            "/api/v1/account",
            content=b'{"confirmation":"DELETE MY ACCOUNT"}',
            headers=_headers(runtime),
        )
    assert deleted.status_code == 204
    assert accounts.deleted is True
    assert runtime.settings.session_cookie_name in deleted.headers["set-cookie"]
    assert "Max-Age=0" in deleted.headers["set-cookie"]


def test_disabled_account_routes_do_not_touch_services() -> None:
    api.app.state.auth_runtime = AuthRuntime(settings=AuthSettings(enabled=False))
    with TestClient(api.app) as client:
        assert client.get("/api/v1/account").status_code == 503
        assert client.delete("/api/v1/account").status_code == 503
