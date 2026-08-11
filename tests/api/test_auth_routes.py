from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from illinois_lottery_tracker import api
from illinois_lottery_tracker.auth.config import AuthSettings, load_auth_settings
from illinois_lottery_tracker.auth.crypto import token_digest
from illinois_lottery_tracker.auth.csrf import csrf_token
from illinois_lottery_tracker.auth.service import ClaimedAttempt, IssuedSession, LoginStart
from illinois_lottery_tracker.auth.types import AuthPrincipal, VerifiedIdentity
from illinois_lottery_tracker.auth_api import AuthRuntime

NOW = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)
RAW_SESSION = base64.urlsafe_b64encode(bytes([4]) * 32).rstrip(b"=").decode()


def _settings(*, production: bool = False) -> AuthSettings:
    root = base64.urlsafe_b64encode(bytes([8]) * 32).rstrip(b"=").decode()
    return load_auth_settings(
        {
            "AUTH_ENABLED": "true",
            "APP_ENV": "production" if production else "test",
            "PUBLIC_BASE_URL": (
                "https://lottery.example" if production else "http://localhost:5173"
            ),
            "GOOGLE_OIDC_CLIENT_ID": "client.apps.googleusercontent.com",
            "GOOGLE_OIDC_CLIENT_SECRET": "test-secret",
            "AUTH_SECRET_KEYS": root,
            "AUTH_TRUSTED_PROXY_HOPS": "none",
        }
    )


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid.UUID("08ec5c00-cdf8-487a-8db4-31f19be30f59"),
        session_id=uuid.UUID("988977c9-3aa0-4de8-933a-d4454d707413"),
        email="player@example.test",
        session_created_at=NOW,
        idle_expires_at=NOW + timedelta(days=1),
        absolute_expires_at=NOW + timedelta(days=7),
    )


class FakeAttempts:
    def __init__(self) -> None:
        self.starts: list[tuple[str, str | None]] = []
        self.claims: list[dict[str, object]] = []

    def start_login(self, return_path: str, previous_binding: str | None) -> LoginStart:
        self.starts.append((return_path, previous_binding))
        return LoginStart(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=safe",
            base64.urlsafe_b64encode(bytes([5]) * 32).rstrip(b"=").decode(),
            uuid.uuid4(),
        )

    def claim_callback(self, **values) -> ClaimedAttempt:
        self.claims.append(values)
        return ClaimedAttempt(
            attempt_id=uuid.uuid4(),
            code=str(values["code"]),
            code_verifier="verifier",
            nonce_digest=bytes([2]) * 32,
            return_path="/account",
            intent="login",
            expected_user_id=None,
            expected_session_id=None,
        )


class FakeProvider:
    def exchange(self, _request) -> VerifiedIdentity:
        return VerifiedIdentity(
            issuer="https://accounts.google.com",
            subject="123456789",
            email="player@example.test",
        )


class FakeSessions:
    def __init__(self, principal: AuthPrincipal | None = None) -> None:
        self.principal = principal
        self.revoked: list[uuid.UUID] = []
        self.revoked_all = False
        self.resolve_calls: list[str | None] = []

    def resolve_principal(self, raw: str | None) -> AuthPrincipal | None:
        self.resolve_calls.append(raw)
        return self.principal if raw == RAW_SESSION else None

    def finalize_login(self, _claimed, _identity) -> IssuedSession:
        principal = _principal()
        return IssuedSession(
            token=RAW_SESSION,
            session_id=principal.session_id,
            user_id=principal.user_id,
            email=principal.email,
            created_at=principal.session_created_at,
            idle_expires_at=principal.idle_expires_at,
            absolute_expires_at=principal.absolute_expires_at,
        )

    def mark_exchange_failed(self, _attempt_id, _reason) -> None:
        return None

    def revoke_current(self, principal: AuthPrincipal) -> bool:
        self.revoked.append(principal.session_id)
        return True

    def list_active(self, principal: AuthPrincipal):
        return [
            SimpleNamespace(
                id=principal.session_id,
                created_at=principal.session_created_at,
                last_seen_at=principal.session_created_at,
                idle_expires_at=principal.idle_expires_at,
                absolute_expires_at=principal.absolute_expires_at,
            )
        ]

    def revoke_owned(self, _principal: AuthPrincipal, session_id: uuid.UUID) -> bool:
        self.revoked.append(session_id)
        return True

    def revoke_all(self, _principal: AuthPrincipal) -> int:
        self.revoked_all = True
        return 1


@pytest.fixture(autouse=True)
def clear_runtime():
    if hasattr(api.app.state, "auth_runtime"):
        del api.app.state.auth_runtime
    yield
    if hasattr(api.app.state, "auth_runtime"):
        del api.app.state.auth_runtime


def _runtime(
    *,
    settings: AuthSettings | None = None,
    principal: AuthPrincipal | None = None,
) -> tuple[AuthRuntime, FakeAttempts, FakeSessions]:
    auth_settings = settings or _settings()
    attempts = FakeAttempts()
    sessions = FakeSessions(principal)
    runtime = AuthRuntime(
        settings=auth_settings,
        provider=FakeProvider(),  # type: ignore[arg-type]
        attempts=attempts,  # type: ignore[arg-type]
        sessions=sessions,  # type: ignore[arg-type]
    )
    return runtime, attempts, sessions


def _assert_common(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert uuid.UUID(response.headers["x-request-id"]).version == 4


def _csrf(settings: AuthSettings, principal: AuthPrincipal) -> str:
    return csrf_token(
        principal.session_id,
        token_digest(RAW_SESSION),
        settings.root_keys[0],
    )


def test_disabled_contract_does_no_service_lookup() -> None:
    api.app.state.auth_runtime = AuthRuntime(settings=AuthSettings(enabled=False))
    with TestClient(api.app) as client:
        session = client.get("/api/v1/auth/session")
        assert session.json() == {
            "authenticationAvailable": False,
            "authenticated": False,
            "user": None,
            "session": None,
            "csrfToken": None,
        }
        assert session.headers["vary"] == "Cookie"
        _assert_common(session)

        start = client.get("/api/v1/auth/google/start", follow_redirects=False)
        assert start.status_code == 503
        assert start.json()["code"] == "AUTH_UNAVAILABLE"
        _assert_common(start)

        callback = client.get(
            "/api/v1/auth/google/callback?state=secret&code=secret",
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == "/?authResult=failed"
        assert "secret" not in callback.text
        _assert_common(callback)


def test_session_contracts_and_invalid_cookie_clearing() -> None:
    runtime, _attempts, sessions = _runtime()
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        anonymous = client.get("/api/v1/auth/session")
        assert anonymous.status_code == 200
        assert anonymous.json()["authenticationAvailable"] is True
        assert anonymous.json()["authenticated"] is False

        client.cookies.set(runtime.settings.session_cookie_name, "invalid")
        stale = client.get("/api/v1/auth/session")
        assert runtime.settings.session_cookie_name in stale.headers["set-cookie"]
        assert "Max-Age=0" in stale.headers["set-cookie"]

        sessions.principal = _principal()
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        authenticated = client.get("/api/v1/auth/session")
        assert authenticated.json() == {
            "authenticationAvailable": True,
            "authenticated": True,
            "user": {
                "id": str(_principal().user_id),
                "email": "player@example.test",
                "emailVerified": True,
            },
            "session": {
                "authenticatedAt": "2026-08-10T18:30:00Z",
                "idleExpiresAt": "2026-08-11T18:30:00Z",
                "absoluteExpiresAt": "2026-08-17T18:30:00Z",
            },
            "csrfToken": _csrf(runtime.settings, _principal()),
        }
        assert authenticated.headers["vary"] == "Cookie"
        _assert_common(authenticated)


def test_google_start_validates_return_path_and_cookie_attributes() -> None:
    runtime, attempts, _sessions = _runtime(settings=_settings(production=True))
    api.app.state.auth_runtime = runtime
    with TestClient(api.app, base_url="https://lottery.example") as client:
        invalid = client.get(
            "/api/v1/auth/google/start?returnTo=//attacker.test",
            follow_redirects=False,
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "INVALID_RETURN_PATH"
        assert attempts.starts == []

        duplicate = client.get(
            "/api/v1/auth/google/start?returnTo=%2F&returnTo=%2Faccount",
            follow_redirects=False,
        )
        assert duplicate.status_code == 400
        assert attempts.starts == []

        started = client.get(
            "/api/v1/auth/google/start?returnTo=%2Faccount",
            follow_redirects=False,
        )
        assert started.status_code == 303
        assert started.headers["location"].startswith("https://accounts.google.com/")
        cookie = started.headers["set-cookie"]
        assert "__Host-ilt_login=" in cookie
        assert "HttpOnly" in cookie
        assert "Max-Age=600" in cookie
        assert "Path=/" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" in cookie
        assert "Domain=" not in cookie
        assert attempts.starts == [("/account", None)]
        _assert_common(started)


def test_callback_rejects_duplicates_and_issues_cookie_after_success() -> None:
    runtime, attempts, _sessions = _runtime()
    api.app.state.auth_runtime = runtime
    binding = base64.urlsafe_b64encode(bytes([5]) * 32).rstrip(b"=").decode()
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.login_cookie_name, binding)
        duplicate = client.get(
            "/api/v1/auth/google/callback?state=a&state=b&code=private",
            follow_redirects=False,
        )
        assert duplicate.status_code == 303
        assert duplicate.headers["location"] == "/?authResult=failed"
        assert attempts.claims == []

        success = client.get(
            "/api/v1/auth/google/callback?state=state&code=private&iss="
            "https%3A%2F%2Faccounts.google.com&error_description=ignore-me",
            follow_redirects=False,
        )
        assert success.status_code == 303
        assert success.headers["location"] == "/account"
        assert "ilt_session_dev=" in success.headers["set-cookie"]
        assert "ilt_login_dev" not in success.headers["set-cookie"]
        assert attempts.claims[0]["code"] == "private"
        assert "private" not in success.text
        assert "state" not in success.headers["location"]
        _assert_common(success)


def test_logout_contract_and_csrf_order() -> None:
    principal = _principal()
    runtime, _attempts, sessions = _runtime(principal=principal)
    api.app.state.auth_runtime = runtime
    origin = runtime.settings.public_base_url
    with TestClient(api.app) as client:
        no_cookie = client.post("/api/v1/auth/logout", json={})
        assert no_cookie.status_code == 204
        assert sessions.revoked == []

        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        missing = client.post("/api/v1/auth/logout", json={}, headers={"Origin": origin})
        assert missing.status_code == 403
        assert missing.json()["code"] == "CSRF_INVALID"
        assert sessions.revoked == []

        valid = client.post(
            "/api/v1/auth/logout",
            json={},
            headers={"Origin": origin, "X-CSRF-Token": _csrf(runtime.settings, principal)},
        )
        assert valid.status_code == 204
        assert sessions.revoked == [principal.session_id]
        assert "Max-Age=0" in valid.headers["set-cookie"]


def test_session_management_is_owner_scoped_and_strict() -> None:
    principal = _principal()
    runtime, _attempts, sessions = _runtime(principal=principal)
    api.app.state.auth_runtime = runtime
    headers = {
        "Origin": runtime.settings.public_base_url,
        "X-CSRF-Token": _csrf(runtime.settings, principal),
    }
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        listed = client.get("/api/v1/auth/sessions")
        assert listed.json()["sessions"][0]["current"] is True
        assert set(listed.json()["sessions"][0]) == {
            "id",
            "current",
            "createdAt",
            "lastSeenAt",
            "idleExpiresAt",
            "absoluteExpiresAt",
        }

        malformed = client.delete("/api/v1/auth/sessions/not-a-uuid", headers=headers)
        assert malformed.status_code == 404
        assert malformed.json()["code"] == "SESSION_NOT_FOUND"

        revoked = client.delete(
            f"/api/v1/auth/sessions/{principal.session_id}", headers=headers
        )
        assert revoked.status_code == 204
        assert sessions.revoked == [principal.session_id]


def test_strict_bounded_json_parser() -> None:
    principal = _principal()
    runtime, _attempts, sessions = _runtime(principal=principal)
    api.app.state.auth_runtime = runtime
    headers = {
        "Origin": runtime.settings.public_base_url,
        "X-CSRF-Token": _csrf(runtime.settings, principal),
        "Content-Type": "application/json",
    }
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.session_cookie_name, RAW_SESSION)
        duplicate = client.post(
            "/api/v1/auth/logout-all", content=b'{"a":1,"a":1}', headers=headers
        )
        assert duplicate.status_code == 400
        assert sessions.revoked_all is False

        oversized = client.post(
            "/api/v1/auth/logout-all", content=b"{" + b" " * 1024, headers=headers
        )
        assert oversized.status_code == 413

        valid = client.post("/api/v1/auth/logout-all", content=b"{}", headers=headers)
        assert valid.status_code == 204
        assert sessions.revoked_all is True


def test_problem_request_id_ignores_caller_value() -> None:
    runtime, _attempts, _sessions = _runtime()
    api.app.state.auth_runtime = runtime
    supplied = str(uuid.uuid4())
    with TestClient(api.app) as client:
        response = client.get(
            "/api/v1/auth/sessions", headers={"X-Request-ID": supplied}
        )
        payload = response.json()
        assert response.status_code == 401
        assert payload["requestId"] == response.headers["x-request-id"]
        assert payload["requestId"] != supplied
        assert set(payload) == {"type", "title", "status", "code", "requestId"}
