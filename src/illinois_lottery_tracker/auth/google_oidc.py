"""Pinned Google OpenID Connect provider adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet

from .config import AuthSettings
from .crypto import b64url_encode, strict_b64url_decode, token_digest
from .types import ProviderExchangeRequest, VerifiedIdentity

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ISSUER = "https://accounts.google.com"
LEGACY_ISSUER = "accounts.google.com"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
ALLOWED_ALGORITHM = "RS256"


class OidcProviderError(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _strict_json(content: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    parsed = json.loads(content, object_pairs_hook=pairs)
    if not isinstance(parsed, dict):
        raise ValueError("JSON document must be an object")
    return parsed


def _verified_email(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 320:
        raise OidcProviderError("token_validation_failed")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        raise OidcProviderError("token_validation_failed")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip() or len(normalized) > 320:
        raise OidcProviderError("token_validation_failed")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in normalized):
        raise OidcProviderError("token_validation_failed")
    return normalized


class GoogleOidcProvider:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        client: httpx.Client | None = None,
        clock=lambda: datetime.now(UTC),
        monotonic=time.monotonic,
    ):
        if (
            not settings.enabled
            or not settings.google_client_id
            or not settings.google_client_secret
        ):
            raise ValueError("enabled Google configuration is required")
        self.settings = settings
        self._clock = clock
        self._monotonic = monotonic
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=3, read=5, write=5, pool=2),
            follow_redirects=False,
            verify=True,
            trust_env=False,
        )
        self._metadata_cache: tuple[float, dict[str, Any]] | None = None
        self._jwks_cache: tuple[float, KeySet] | None = None

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        limit: int,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            with self._client.stream(method, url, data=data) as response:
                if response.status_code != 200:
                    raise OidcProviderError("provider_unavailable")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > limit:
                        raise OidcProviderError("provider_unavailable")
        except OidcProviderError:
            raise
        except Exception as exc:
            raise OidcProviderError("provider_unavailable") from exc
        try:
            return _strict_json(bytes(content))
        except (ValueError, UnicodeError) as exc:
            raise OidcProviderError("provider_unavailable") from exc

    def _metadata(self) -> dict[str, Any]:
        now = self._monotonic()
        if self._metadata_cache and now < self._metadata_cache[0]:
            return self._metadata_cache[1]
        document = self._request_json("GET", DISCOVERY_URL, limit=256 * 1024)
        if (
            document.get("issuer") != ISSUER
            or document.get("authorization_endpoint") != AUTHORIZATION_ENDPOINT
            or document.get("token_endpoint") != TOKEN_ENDPOINT
            or document.get("jwks_uri") != JWKS_ENDPOINT
            or ALLOWED_ALGORITHM not in document.get("id_token_signing_alg_values_supported", [])
        ):
            raise OidcProviderError("provider_unavailable")
        self._metadata_cache = (now + 3600, document)
        return document

    def _jwks(self) -> KeySet:
        self._metadata()
        now = self._monotonic()
        if self._jwks_cache and now < self._jwks_cache[0]:
            return self._jwks_cache[1]
        document = self._request_json("GET", JWKS_ENDPOINT, limit=256 * 1024)
        try:
            key_set = KeySet.import_key_set(document)
        except Exception as exc:
            raise OidcProviderError("provider_unavailable") from exc
        self._jwks_cache = (now + 3600, key_set)
        return key_set

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        prompt: str | None = None,
    ) -> str:
        self._metadata()
        strict_b64url_decode(state, decoded_length=32)
        strict_b64url_decode(nonce, decoded_length=32)
        strict_b64url_decode(code_challenge, decoded_length=32)
        if redirect_uri != self.settings.callback_url or prompt not in {None, "select_account"}:
            raise ValueError("invalid authorization request")
        parameters = {
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "client_id": self.settings.google_client_id or "",
            "redirect_uri": redirect_uri,
        }
        if prompt:
            parameters["prompt"] = prompt
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"

    def exchange(self, request: ProviderExchangeRequest) -> VerifiedIdentity:
        self._metadata()
        if (
            request.redirect_uri != self.settings.callback_url
            or not 1 <= len(request.code) <= 4096
            or any(ord(character) < 0x20 for character in request.code)
        ):
            raise OidcProviderError("token_exchange_failed")
        document = self._request_json(
            "POST",
            TOKEN_ENDPOINT,
            limit=64 * 1024,
            data={
                "code": request.code,
                "client_id": self.settings.google_client_id or "",
                "client_secret": self.settings.google_client_secret or "",
                "redirect_uri": request.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": request.code_verifier,
            },
        )
        access_token = document.get("access_token")
        id_token = document.get("id_token")
        token_type = document.get("token_type")
        if (
            not isinstance(access_token, str)
            or not 1 <= len(access_token) <= 8192
            or not access_token.isascii()
            or any(ord(character) < 0x20 for character in access_token)
            or not isinstance(id_token, str)
            or not 1 <= len(id_token) <= 16 * 1024
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise OidcProviderError("token_validation_failed")
        return self._validate_id_token(id_token, access_token, request.expected_nonce_digest)

    def _validate_id_token(
        self, encoded: str, access_token: str, expected_nonce_digest: bytes
    ) -> VerifiedIdentity:
        try:
            token = jwt.decode(encoded, self._jwks(), algorithms=[ALLOWED_ALGORITHM])
            claims = token.claims
        except Exception as exc:
            raise OidcProviderError("token_validation_failed") from exc
        now = int(self._clock().timestamp())
        issuer = claims.get("iss")
        issued_at, expires_at = claims.get("iat"), claims.get("exp")
        not_before = claims.get("nbf")
        if (
            issuer not in {ISSUER, LEGACY_ISSUER}
            or isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= issued_at
            or expires_at <= now - 60
            or issued_at > now + 60
            or (
                not_before is not None
                and (
                    isinstance(not_before, bool)
                    or not isinstance(not_before, int)
                    or not_before > now + 60
                )
            )
        ):
            raise OidcProviderError("token_validation_failed")
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        client_id = self.settings.google_client_id
        if (
            not isinstance(audiences, list)
            or not audiences
            or any(not isinstance(value, str) for value in audiences)
            or client_id not in audiences
            or (len(audiences) > 1 and claims.get("azp") != client_id)
            or ("azp" in claims and claims.get("azp") != client_id)
        ):
            raise OidcProviderError("token_validation_failed")
        nonce = claims.get("nonce")
        try:
            nonce_matches = hmac.compare_digest(
                token_digest(nonce) if isinstance(nonce, str) else b"", expected_nonce_digest
            )
        except ValueError:
            nonce_matches = False
        subject = claims.get("sub")
        if (
            not nonce_matches
            or not isinstance(subject, str)
            or not 1 <= len(subject.encode("utf-8")) <= 255
            or any(not 0x21 <= ord(character) <= 0x7E for character in subject)
            or claims.get("email_verified") is not True
        ):
            raise OidcProviderError("token_validation_failed")
        at_hash = claims.get("at_hash")
        if at_hash is not None:
            calculated = b64url_encode(hashlib.sha256(access_token.encode("ascii")).digest()[:16])
            if not isinstance(at_hash, str) or not hmac.compare_digest(at_hash, calculated):
                raise OidcProviderError("token_validation_failed")
        return VerifiedIdentity(
            issuer=ISSUER,
            subject=subject,
            email=_verified_email(claims.get("email")),
            email_verified=True,
        )
