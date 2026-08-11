from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from illinois_lottery_tracker import api
from illinois_lottery_tracker.auth.rate_limit import RateDecision
from illinois_lottery_tracker.auth_api import AuthRuntime
from illinois_lottery_tracker.rankings_api import RankingDatasetResponse

from .test_auth_routes import RAW_SESSION, FakeSessions, _principal, _settings


class ExplodingSessions(FakeSessions):
    def resolve_principal(self, _raw):
        raise AssertionError("public rankings must never resolve an auth principal")


def test_public_rankings_has_no_optional_auth_lookup(monkeypatch) -> None:
    api.app.state.auth_runtime = AuthRuntime(
        settings=_settings(), sessions=ExplodingSessions()  # type: ignore[arg-type]
    )
    document = RankingDatasetResponse.model_validate(
        {
            "mode": "live",
            "generatedAt": "2026-08-10T20:00:00Z",
            "status": {
                "available": False,
                "reasonCode": "ANALYTICS_MODEL_UNAVAILABLE",
                "sourceRunId": 1,
                "sourceObservedAt": "2026-08-10T19:00:00Z",
                "catalogRunId": 2,
                "catalogObservedAt": "2026-08-10T19:05:00Z",
                "analyticsRunId": None,
                "modelVersion": None,
            },
            "rankings": [],
        }
    )
    monkeypatch.setattr(api, "get_engine", lambda: object())
    monkeypatch.setattr(api, "read_current_rankings", lambda _engine: document)
    with TestClient(api.app) as client:
        response = client.get(
            "/api/v1/rankings", cookies={_settings().session_cookie_name: "invalid"}
        )
    assert response.status_code == 200
    assert response.json()["rankings"] == []


def test_auth_middleware_replaces_inbound_request_id() -> None:
    api.app.state.auth_runtime = AuthRuntime(settings=_settings())
    supplied = str(uuid.uuid4())
    with TestClient(api.app) as client:
        response = client.get(
            "/api/v1/auth/session", headers={"X-Request-ID": supplied}
        )
    generated = response.headers["x-request-id"]
    assert generated != supplied
    assert uuid.UUID(generated).version == 4
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_static_account_fallback_never_rewrites_api_misses() -> None:
    if not api.FRONTEND_DIST.joinpath("index.html").is_file():
        pytest.skip("frontend production build is not present")
    with TestClient(api.app) as client:
        account = client.get("/account")
        missing_api = client.get("/api/v1/not-a-real-route")
    assert account.status_code == 200
    assert account.headers["content-type"].startswith("text/html")
    assert missing_api.status_code == 404
    assert not missing_api.headers["content-type"].startswith("text/html")


class RejectingLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def consume_source(self, source, policy):
        self.calls.append((source, policy))
        return RateDecision(False, 37)


def test_rate_limit_rejects_before_auth_lookup_and_scrubs_callback() -> None:
    limiter = RejectingLimiter()
    api.app.state.auth_runtime = AuthRuntime(settings=_settings())
    api.app.state.auth_limiter = limiter
    try:
        with TestClient(api.app) as client:
            regular = client.get("/api/v1/auth/session")
            callback = client.get(
                "/api/v1/auth/google/callback?code=secret-code&state=secret-state",
                follow_redirects=False,
            )
    finally:
        del api.app.state.auth_limiter
    assert regular.status_code == 429
    assert regular.headers["retry-after"] == "37"
    assert regular.json()["code"] == "RATE_LIMITED"
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?authResult=failed"
    assert "secret" not in str(callback.headers)
    assert [policy for _source, policy in limiter.calls] == ["read", "callback"]


def test_production_security_headers_are_applied_without_cors(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    api.app.state.auth_runtime = AuthRuntime(settings=_settings())
    with TestClient(api.app) as client:
        response = client.get("/api/v1/auth/session")
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


class UserRejectingLimiter:
    def consume_source(self, _source, _policy):
        return RateDecision(True)

    def consume_user(self, _user_id, _policy):
        return RateDecision(False, 23, True)


class RecordingSessions(FakeSessions):
    def __init__(self):
        super().__init__(_principal())
        self.rate_events = 0

    def record_rate_limited(self, _principal):
        self.rate_events += 1


def test_known_user_limit_emits_coalesced_event_request() -> None:
    sessions = RecordingSessions()
    api.app.state.auth_runtime = AuthRuntime(
        settings=_settings(), sessions=sessions  # type: ignore[arg-type]
    )
    api.app.state.auth_limiter = UserRejectingLimiter()
    try:
        with TestClient(api.app) as client:
            response = client.get(
                "/api/v1/auth/session",
                cookies={_settings().session_cookie_name: RAW_SESSION},
            )
    finally:
        del api.app.state.auth_limiter
    assert response.status_code == 429
    assert response.headers["retry-after"] == "23"
    assert sessions.rate_events == 1
