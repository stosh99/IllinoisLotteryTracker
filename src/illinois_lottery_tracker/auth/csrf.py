"""Session-bound CSRF derivation and same-origin validation."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from urllib.parse import urlsplit

from .crypto import CSRF_INFO, b64url_encode, derive_key, strict_b64url_decode

CSRF_PREFIX = b"ilt-csrf-v1\x00"


def csrf_token(session_id: uuid.UUID, session_digest: bytes, root_key: bytes) -> str:
    if len(session_digest) != 32:
        raise ValueError("invalid session digest")
    message = CSRF_PREFIX + session_id.bytes + session_digest
    digest = hmac.new(derive_key(root_key, CSRF_INFO), message, hashlib.sha256).digest()
    return b64url_encode(digest)


def validate_csrf_token(
    supplied: str,
    session_id: uuid.UUID,
    session_digest: bytes,
    root_keys: tuple[bytes, ...],
) -> bool:
    try:
        strict_b64url_decode(supplied, decoded_length=32)
    except (TypeError, ValueError):
        return False
    return any(
        hmac.compare_digest(supplied, csrf_token(session_id, session_digest, key))
        for key in root_keys
    )


def canonical_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not parsed.hostname
            or parsed.scheme not in {"http", "https"}
        ):
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def validate_request_origin(
    *,
    public_origin: str,
    origin: str | None,
    referer: str | None,
    fetch_site: str | None,
) -> bool:
    expected = canonical_origin(public_origin)
    if expected is None or fetch_site == "cross-site":
        return False
    if origin is not None:
        return origin != "null" and canonical_origin(origin) == expected
    if referer is None:
        return False
    try:
        parsed = urlsplit(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
        return False
    return canonical_origin(referer_origin) == expected
