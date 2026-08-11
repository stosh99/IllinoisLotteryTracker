"""Purpose-separated authentication cryptography."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PKCE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
OIDC_INFO = b"illinois-lottery-tracker/auth/oidc-attempt/v1"
CSRF_INFO = b"illinois-lottery-tracker/auth/csrf/v1"
TELEMETRY_INFO = b"illinois-lottery-tracker/auth/telemetry/v1"
ATTEMPT_AAD_PREFIX = b"ilt-oidc-attempt-v1\x00"


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def strict_b64url_decode(value: str, *, decoded_length: int) -> bytes:
    expected_length = (decoded_length * 8 + 5) // 6
    if len(value) != expected_length or not BASE64URL_RE.fullmatch(value):
        raise ValueError("invalid unpadded base64url value")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid unpadded base64url value") from exc
    if len(decoded) != decoded_length or b64url_encode(decoded) != value:
        raise ValueError("noncanonical base64url value")
    return decoded


def random_token(byte_count: int = 32) -> str:
    return b64url_encode(secrets.token_bytes(byte_count))


def token_digest(encoded_value: str, *, decoded_length: int = 32) -> bytes:
    return hashlib.sha256(
        strict_b64url_decode(encoded_value, decoded_length=decoded_length)
    ).digest()


def pkce_verifier() -> str:
    return random_token(64)


def pkce_challenge(verifier: str) -> str:
    if not verifier.isascii() or not PKCE_RE.fullmatch(verifier):
        raise ValueError("invalid PKCE verifier")
    return b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def derive_key(root_key: bytes, info: bytes) -> bytes:
    if len(root_key) != 32 or info not in {OIDC_INFO, CSRF_INFO, TELEMETRY_INFO}:
        raise ValueError("invalid root key or purpose")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(root_key)


class AttemptCipher:
    """AES-GCM envelope with newest-first key rotation."""

    def __init__(self, root_keys: tuple[bytes, ...]):
        if not root_keys:
            raise ValueError("at least one root key is required")
        self._keys = tuple(derive_key(key, OIDC_INFO) for key in root_keys)

    def encrypt(self, attempt_id: uuid.UUID, verifier: str) -> str:
        strict_b64url_decode(verifier, decoded_length=64)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._keys[0]).encrypt(
            nonce, verifier.encode("ascii"), ATTEMPT_AAD_PREFIX + attempt_id.bytes
        )
        envelope = "v1." + b64url_encode(nonce + ciphertext)
        if len(envelope) != 155:
            raise AssertionError("unexpected OIDC envelope length")
        return envelope

    def decrypt(self, attempt_id: uuid.UUID, envelope: str) -> str:
        if not envelope.startswith("v1.") or len(envelope) != 155:
            raise ValueError("invalid OIDC envelope")
        payload = strict_b64url_decode(envelope[3:], decoded_length=114)
        nonce, ciphertext = payload[:12], payload[12:]
        for key in self._keys:
            try:
                plaintext = AESGCM(key).decrypt(
                    nonce, ciphertext, ATTEMPT_AAD_PREFIX + attempt_id.bytes
                )
            except Exception:
                continue
            try:
                verifier = plaintext.decode("ascii")
                strict_b64url_decode(verifier, decoded_length=64)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError("invalid decrypted verifier") from exc
            return verifier
        raise ValueError("OIDC envelope authentication failed")
