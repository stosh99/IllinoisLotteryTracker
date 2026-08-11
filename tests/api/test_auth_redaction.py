from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from illinois_lottery_tracker import api
from illinois_lottery_tracker.auth_api import AuthRuntime

from .test_auth_routes import FakeAttempts, FakeProvider, FakeSessions, _settings


class ExplodingAttempts(FakeAttempts):
    def claim_callback(self, **_values):
        raise RuntimeError("database unavailable")


class ExplodingProvider(FakeProvider):
    def exchange(self, _request):
        raise RuntimeError("provider response contained highly-secret-code")


def test_callback_failure_response_and_application_logs_are_redacted(caplog) -> None:
    runtime = AuthRuntime(
        settings=_settings(),
        provider=ExplodingProvider(),  # type: ignore[arg-type]
        attempts=ExplodingAttempts(),  # type: ignore[arg-type]
        sessions=FakeSessions(),  # type: ignore[arg-type]
    )
    api.app.state.auth_runtime = runtime
    with caplog.at_level(logging.DEBUG), TestClient(api.app) as client:
        client.cookies.set(runtime.settings.login_cookie_name, "binding-secret")
        response = client.get(
            "/api/v1/auth/google/callback?state=state-secret&code=code-secret",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/?authResult=failed"
    application_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("illinois_lottery_tracker")
        or record.name.startswith("uvicorn")
    )
    captured = application_logs + response.text + str(response.headers)
    assert "state-secret" not in captured
    assert "code-secret" not in captured
    assert "binding-secret" not in captured


def test_callback_database_failure_is_always_a_clean_local_redirect() -> None:
    runtime = AuthRuntime(
        settings=_settings(),
        provider=FakeProvider(),  # type: ignore[arg-type]
        attempts=ExplodingAttempts(),  # type: ignore[arg-type]
        sessions=FakeSessions(),  # type: ignore[arg-type]
    )
    api.app.state.auth_runtime = runtime
    with TestClient(api.app) as client:
        client.cookies.set(runtime.settings.login_cookie_name, "binding")
        response = client.get(
            "/api/v1/auth/google/callback?state=state&code=code",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/?authResult=failed"
    assert response.headers["cache-control"] == "no-store"
