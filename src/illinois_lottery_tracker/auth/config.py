"""Strict, fail-closed authentication configuration."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .crypto import strict_b64url_decode

DEFAULT_LOGIN_ATTEMPT_SECONDS = 600
DEFAULT_SESSION_IDLE_SECONDS = 86_400
DEFAULT_SESSION_ABSOLUTE_SECONDS = 604_800
DEFAULT_SESSION_TOUCH_SECONDS = 300
DEFAULT_MAX_ACTIVE_SESSIONS = 5
DEFAULT_RECENT_LOGIN_SECONDS = 600


class AuthConfigurationError(RuntimeError):
    """Raised when enabled authentication configuration is unsafe."""


def _exact_bool(value: str | None) -> bool:
    if value is None:
        return False
    if value == "true":
        return True
    if value == "false":
        return False
    raise AuthConfigurationError("AUTH_ENABLED must be exactly 'true' or 'false'")


def _bounded_int(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = env.get(name, str(default))
    if not raw.isascii() or not raw.isdecimal():
        raise AuthConfigurationError(f"{name} must be a base-10 integer")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise AuthConfigurationError(f"{name} is outside its reviewed bounds")
    return value


def _nonsecret_text(value: str | None, name: str, *, limit: int = 512) -> str:
    if value is None or not value or value != value.strip():
        raise AuthConfigurationError(f"{name} is required and may not have outer whitespace")
    if len(value) > limit or any(ord(character) < 0x20 for character in value):
        raise AuthConfigurationError(f"{name} is malformed")
    return value


def _secret_text(value: str | None, name: str, *, minimum: int, maximum: int) -> str:
    text = _nonsecret_text(value, name, limit=maximum)
    if len(text) < minimum or text.lower() in {"replace-me", "example", "changeme"}:
        raise AuthConfigurationError(f"{name} is missing or an example value")
    return text


def _parse_root_keys(value: str | None) -> tuple[bytes, ...]:
    text = _nonsecret_text(value, "AUTH_SECRET_KEYS", limit=131)
    parts = text.split(",")
    if not 1 <= len(parts) <= 3 or len(set(parts)) != len(parts):
        raise AuthConfigurationError("AUTH_SECRET_KEYS must contain one to three unique keys")
    try:
        keys = tuple(strict_b64url_decode(part, decoded_length=32) for part in parts)
    except ValueError as exc:
        raise AuthConfigurationError("AUTH_SECRET_KEYS contains a malformed key") from exc
    return keys


def _validate_public_origin(value: str, environment: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AuthConfigurationError("PUBLIC_BASE_URL has a malformed port") from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not parsed.hostname
    ):
        raise AuthConfigurationError("PUBLIC_BASE_URL must be an origin only")
    if environment == "production":
        if parsed.scheme != "https" or port not in {None, 443}:
            raise AuthConfigurationError("production PUBLIC_BASE_URL must use default-port HTTPS")
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise AuthConfigurationError("production PUBLIC_BASE_URL may not use an IP literal")
        if parsed.hostname.lower() == "localhost":
            raise AuthConfigurationError("production PUBLIC_BASE_URL may not use localhost")
    else:
        if parsed.scheme not in {"http", "https"}:
            raise AuthConfigurationError("development PUBLIC_BASE_URL must use HTTP(S)")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if not loopback:
            raise AuthConfigurationError("development HTTP(S) is loopback-only")
    return value[:-1] if value.endswith("/") else value


def _trusted_proxies(value: str | None) -> tuple[str, ...]:
    text = _nonsecret_text(value, "AUTH_TRUSTED_PROXY_HOPS", limit=1024)
    if text == "none":
        return ()
    networks: list[str] = []
    for part in text.split(","):
        if not part or part != part.strip():
            raise AuthConfigurationError("AUTH_TRUSTED_PROXY_HOPS is malformed")
        try:
            networks.append(str(ipaddress.ip_network(part, strict=False)))
        except ValueError as exc:
            raise AuthConfigurationError("AUTH_TRUSTED_PROXY_HOPS is malformed") from exc
    return tuple(networks)


@dataclass(frozen=True)
class AuthSettings:
    """Validated authentication settings with secret-safe representation."""

    enabled: bool = False
    app_env: str | None = None
    public_base_url: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = field(default=None, repr=False)
    root_keys: tuple[bytes, ...] = field(default=(), repr=False)
    trusted_proxy_hops: tuple[str, ...] = ()
    session_idle_seconds: int = DEFAULT_SESSION_IDLE_SECONDS
    session_absolute_seconds: int = DEFAULT_SESSION_ABSOLUTE_SECONDS
    session_touch_seconds: int = DEFAULT_SESSION_TOUCH_SECONDS
    login_attempt_seconds: int = DEFAULT_LOGIN_ATTEMPT_SECONDS
    max_active_sessions: int = DEFAULT_MAX_ACTIVE_SESSIONS
    recent_login_seconds: int = DEFAULT_RECENT_LOGIN_SECONDS

    @property
    def callback_url(self) -> str:
        if not self.public_base_url:
            raise AuthConfigurationError("authentication public origin is unavailable")
        return f"{self.public_base_url}/api/v1/auth/google/callback"

    @property
    def session_cookie_name(self) -> str:
        return "__Host-ilt_session" if self.app_env == "production" else "ilt_session_dev"

    @property
    def login_cookie_name(self) -> str:
        return "__Host-ilt_login" if self.app_env == "production" else "ilt_login_dev"

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production"


def load_auth_settings(environ: Mapping[str, str] | None = None) -> AuthSettings:
    """Load authentication configuration without requiring it while disabled."""

    env = os.environ if environ is None else environ
    enabled = _exact_bool(env.get("AUTH_ENABLED"))
    if not enabled:
        return AuthSettings(enabled=False)

    app_env = _nonsecret_text(env.get("APP_ENV"), "APP_ENV", limit=32)
    if app_env not in {"development", "test", "production"}:
        raise AuthConfigurationError("APP_ENV must be development, test, or production")
    public_base_url = _validate_public_origin(
        _nonsecret_text(env.get("PUBLIC_BASE_URL"), "PUBLIC_BASE_URL"), app_env
    )
    client_id = _nonsecret_text(
        env.get("GOOGLE_OIDC_CLIENT_ID"), "GOOGLE_OIDC_CLIENT_ID", limit=255
    )
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise AuthConfigurationError("GOOGLE_OIDC_CLIENT_ID is malformed")
    client_secret = _secret_text(
        env.get("GOOGLE_OIDC_CLIENT_SECRET"), "GOOGLE_OIDC_CLIENT_SECRET", minimum=8, maximum=512
    )
    root_keys = _parse_root_keys(env.get("AUTH_SECRET_KEYS"))
    idle = _bounded_int(env, "AUTH_SESSION_IDLE_SECONDS", DEFAULT_SESSION_IDLE_SECONDS, 900, 86_400)
    absolute = _bounded_int(
        env, "AUTH_SESSION_ABSOLUTE_SECONDS", DEFAULT_SESSION_ABSOLUTE_SECONDS, 3_600, 2_592_000
    )
    touch = _bounded_int(env, "AUTH_SESSION_TOUCH_SECONDS", DEFAULT_SESSION_TOUCH_SECONDS, 60, 900)
    attempt = _bounded_int(
        env, "AUTH_LOGIN_ATTEMPT_SECONDS", DEFAULT_LOGIN_ATTEMPT_SECONDS, 300, 900
    )
    maximum = _bounded_int(env, "AUTH_MAX_ACTIVE_SESSIONS", DEFAULT_MAX_ACTIVE_SESSIONS, 1, 10)
    recent = _bounded_int(env, "AUTH_RECENT_LOGIN_SECONDS", DEFAULT_RECENT_LOGIN_SECONDS, 300, 900)
    if idle >= absolute:
        raise AuthConfigurationError("session idle lifetime must be shorter than absolute lifetime")
    if touch > idle // 4:
        raise AuthConfigurationError("session touch interval exceeds one quarter of idle lifetime")
    return AuthSettings(
        enabled=True,
        app_env=app_env,
        public_base_url=public_base_url,
        google_client_id=client_id,
        google_client_secret=client_secret,
        root_keys=root_keys,
        trusted_proxy_hops=_trusted_proxies(env.get("AUTH_TRUSTED_PROXY_HOPS")),
        session_idle_seconds=idle,
        session_absolute_seconds=absolute,
        session_touch_seconds=touch,
        login_attempt_seconds=attempt,
        max_active_sessions=maximum,
        recent_login_seconds=recent,
    )
