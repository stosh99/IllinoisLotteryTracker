from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from joserfc import jwt
from joserfc.jwk import RSAKey

from illinois_lottery_tracker.auth.config import load_auth_settings
from illinois_lottery_tracker.auth.crypto import pkce_verifier, random_token, token_digest
from illinois_lottery_tracker.auth.google_oidc import (
    AUTHORIZATION_ENDPOINT,
    DISCOVERY_URL,
    ISSUER,
    JWKS_ENDPOINT,
    TOKEN_ENDPOINT,
    GoogleOidcProvider,
    OidcProviderError,
)
from illinois_lottery_tracker.auth.types import ProviderExchangeRequest

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _settings():
    root = base64.urlsafe_b64encode(bytes([9]) * 32).rstrip(b"=").decode()
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


class OidcFixture:
    def __init__(self, claims_override: dict | None = None):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key = RSAKey.import_key(private)
        self.public_jwk = self.key.as_dict(kid="test-key", use="sig", alg="RS256")
        self.nonce = random_token()
        self.access_token = "access-token"
        claims = {
            "iss": ISSUER,
            "sub": "1234567890",
            "aud": "client.apps.googleusercontent.com",
            "iat": int(NOW.timestamp()),
            "exp": int((NOW + timedelta(minutes=10)).timestamp()),
            "nonce": self.nonce,
            "email": "player@example.test",
            "email_verified": True,
        }
        claims.update(claims_override or {})
        self.id_token = jwt.encode(
            {"alg": "RS256", "kid": "test-key"},
            claims,
            self.key,
            algorithms=["RS256"],
        )
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": AUTHORIZATION_ENDPOINT,
                    "token_endpoint": TOKEN_ENDPOINT,
                    "jwks_uri": JWKS_ENDPOINT,
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if str(request.url) == JWKS_ENDPOINT:
            return httpx.Response(200, json={"keys": [self.public_jwk]})
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": self.access_token,
                    "token_type": "Bearer",
                    "id_token": self.id_token,
                },
            )
        raise AssertionError("unexpected network request")

    def provider(self) -> GoogleOidcProvider:
        client = httpx.Client(transport=httpx.MockTransport(self.handler), trust_env=False)
        return GoogleOidcProvider(_settings(), client=client, clock=lambda: NOW)


def test_authorization_url_has_exact_minimal_contract() -> None:
    fixture = OidcFixture()
    provider = fixture.provider()
    url = provider.build_authorization_url(
        state=random_token(),
        nonce=fixture.nonce,
        code_challenge=random_token(),
        redirect_uri=_settings().callback_url,
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZATION_ENDPOINT
    assert query["scope"] == ["openid email"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert not ({"access_type", "hd", "include_granted_scopes"} & query.keys())


def test_exchange_validates_and_returns_only_identity() -> None:
    fixture = OidcFixture()
    identity = fixture.provider().exchange(
        ProviderExchangeRequest(
            code="one-time-code",
            code_verifier=pkce_verifier(),
            redirect_uri=_settings().callback_url,
            expected_nonce_digest=token_digest(fixture.nonce),
        )
    )
    assert identity.issuer == ISSUER
    assert identity.subject == "1234567890"
    assert identity.email == "player@example.test"
    assert not hasattr(identity, "access_token")
    assert {request.url.host for request in fixture.requests} <= {
        "accounts.google.com",
        "oauth2.googleapis.com",
        "www.googleapis.com",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "https://attacker.example"},
        {"aud": "other-client"},
        {"email_verified": False},
        {"sub": "bad subject"},
        {"exp": int((NOW - timedelta(minutes=1)).timestamp())},
        {"iat": int((NOW + timedelta(minutes=2)).timestamp())},
        {"nonce": random_token()},
    ],
)
def test_invalid_claims_fail_closed(override: dict) -> None:
    fixture = OidcFixture(override)
    with pytest.raises(OidcProviderError, match="token_validation_failed"):
        fixture.provider().exchange(
            ProviderExchangeRequest(
                code="code",
                code_verifier=pkce_verifier(),
                redirect_uri=_settings().callback_url,
                expected_nonce_digest=token_digest(fixture.nonce),
            )
        )


def test_discovery_endpoint_substitution_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DISCOVERY_URL
        return httpx.Response(
            200,
            json={
                "issuer": ISSUER,
                "authorization_endpoint": "https://attacker.example/auth",
                "token_endpoint": TOKEN_ENDPOINT,
                "jwks_uri": JWKS_ENDPOINT,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
        )

    provider = GoogleOidcProvider(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    )
    with pytest.raises(OidcProviderError, match="provider_unavailable"):
        provider.build_authorization_url(
            state=random_token(),
            nonce=random_token(),
            code_challenge=random_token(),
            redirect_uri=_settings().callback_url,
        )
