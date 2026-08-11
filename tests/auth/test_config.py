from __future__ import annotations

import base64

import pytest

from illinois_lottery_tracker.auth.config import AuthConfigurationError, load_auth_settings


def _key(byte: int = 7) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()


def _enabled(**overrides: str) -> dict[str, str]:
    values = {
        "AUTH_ENABLED": "true",
        "APP_ENV": "production",
        "PUBLIC_BASE_URL": "https://lottery.example",
        "GOOGLE_OIDC_CLIENT_ID": "client.apps.googleusercontent.com",
        "GOOGLE_OIDC_CLIENT_SECRET": "a-real-secret",
        "AUTH_SECRET_KEYS": _key(),
        "AUTH_TRUSTED_PROXY_HOPS": "none",
    }
    values.update(overrides)
    return values


def test_disabled_auth_requires_no_other_settings() -> None:
    settings = load_auth_settings({})
    assert not settings.enabled
    assert settings.google_client_secret is None
    assert "secret" not in repr(settings).lower()


@pytest.mark.parametrize("value", ["TRUE", "False", "1", "yes", ""])
def test_auth_enabled_is_exact(value: str) -> None:
    with pytest.raises(AuthConfigurationError):
        load_auth_settings({"AUTH_ENABLED": value})


def test_valid_production_configuration_is_redacted() -> None:
    settings = load_auth_settings(_enabled())
    assert settings.enabled
    assert settings.callback_url == "https://lottery.example/api/v1/auth/google/callback"
    assert settings.session_cookie_name == "__Host-ilt_session"
    assert "a-real-secret" not in repr(settings)
    assert _key() not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_BASE_URL", "http://lottery.example"),
        ("PUBLIC_BASE_URL", "https://localhost"),
        ("PUBLIC_BASE_URL", "https://127.0.0.1"),
        ("PUBLIC_BASE_URL", "https://lottery.example/path"),
        ("PUBLIC_BASE_URL", "https://lottery.example?x=1"),
        ("GOOGLE_OIDC_CLIENT_ID", "not-google"),
        ("GOOGLE_OIDC_CLIENT_SECRET", "replace-me"),
        ("AUTH_SECRET_KEYS", "short"),
        ("AUTH_SECRET_KEYS", f"{_key()},{_key()}"),
        ("AUTH_SESSION_IDLE_SECONDS", "900"),
        ("AUTH_SESSION_TOUCH_SECONDS", "901"),
        ("AUTH_MAX_ACTIVE_SESSIONS", "11"),
    ],
)
def test_unsafe_enabled_configuration_fails(name: str, value: str) -> None:
    with pytest.raises(AuthConfigurationError):
        load_auth_settings(_enabled(**{name: value}))


def test_loopback_development_uses_distinct_insecure_cookie_names() -> None:
    settings = load_auth_settings(
        _enabled(APP_ENV="development", PUBLIC_BASE_URL="http://localhost:5173")
    )
    assert settings.session_cookie_name == "ilt_session_dev"
    assert settings.login_cookie_name == "ilt_login_dev"
    assert not settings.secure_cookies


def test_root_key_rotation_is_newest_first() -> None:
    settings = load_auth_settings(_enabled(AUTH_SECRET_KEYS=f"{_key(1)},{_key(2)}"))
    assert settings.root_keys == (bytes([1]) * 32, bytes([2]) * 32)
