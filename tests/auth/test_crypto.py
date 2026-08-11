from __future__ import annotations

import uuid

import pytest

from illinois_lottery_tracker.auth.crypto import (
    CSRF_INFO,
    OIDC_INFO,
    AttemptCipher,
    derive_key,
    pkce_challenge,
    pkce_verifier,
    random_token,
    strict_b64url_decode,
    token_digest,
)


def test_exact_token_encodings_and_digest() -> None:
    value = random_token()
    assert len(value) == 43
    decoded = strict_b64url_decode(value, decoded_length=32)
    assert len(decoded) == 32
    assert len(token_digest(value)) == 32


@pytest.mark.parametrize("value", ["a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "+"])
def test_strict_decoder_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError):
        strict_b64url_decode(value, decoded_length=32)


def test_pkce_matches_rfc_7636_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert len(pkce_verifier()) == 86


def test_attempt_cipher_round_trip_rotation_and_aad() -> None:
    old_root = bytes([1]) * 32
    new_root = bytes([2]) * 32
    attempt_id = uuid.uuid4()
    verifier = pkce_verifier()
    envelope = AttemptCipher((old_root,)).encrypt(attempt_id, verifier)
    assert len(envelope) == 155
    assert AttemptCipher((new_root, old_root)).decrypt(attempt_id, envelope) == verifier
    with pytest.raises(ValueError):
        AttemptCipher((new_root, old_root)).decrypt(uuid.uuid4(), envelope)
    with pytest.raises(ValueError):
        AttemptCipher((new_root,)).decrypt(attempt_id, envelope)


def test_attempt_cipher_rejects_modification() -> None:
    attempt_id = uuid.uuid4()
    cipher = AttemptCipher((bytes([3]) * 32,))
    envelope = cipher.encrypt(attempt_id, pkce_verifier())
    replacement = "A" if envelope[-1] != "A" else "B"
    with pytest.raises(ValueError):
        cipher.decrypt(attempt_id, envelope[:-1] + replacement)


def test_purpose_separation() -> None:
    root = bytes([4]) * 32
    assert derive_key(root, OIDC_INFO) != derive_key(root, CSRF_INFO)
