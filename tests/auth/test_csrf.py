from __future__ import annotations

import uuid

from illinois_lottery_tracker.auth.csrf import (
    canonical_origin,
    csrf_token,
    validate_csrf_token,
    validate_request_origin,
)


def test_csrf_is_session_bound_and_supports_key_rotation() -> None:
    session_one, session_two = uuid.uuid4(), uuid.uuid4()
    digest = bytes([1]) * 32
    old_key, new_key = bytes([2]) * 32, bytes([3]) * 32
    old_token = csrf_token(session_one, digest, old_key)
    assert len(old_token) == 43
    assert validate_csrf_token(old_token, session_one, digest, (new_key, old_key))
    assert not validate_csrf_token(old_token, session_two, digest, (new_key, old_key))
    assert not validate_csrf_token(old_token, session_one, bytes([4]) * 32, (new_key, old_key))
    assert not validate_csrf_token(old_token[:-1] + "!", session_one, digest, (old_key,))


def test_origin_comparison_is_exact_and_canonical() -> None:
    assert canonical_origin("https://example.test") == ("https", "example.test", 443)
    assert validate_request_origin(
        public_origin="https://example.test",
        origin="https://example.test",
        referer=None,
        fetch_site="same-origin",
    )
    assert not validate_request_origin(
        public_origin="https://example.test",
        origin="https://example.test.attacker.invalid",
        referer=None,
        fetch_site="same-site",
    )
    assert not validate_request_origin(
        public_origin="https://example.test",
        origin="null",
        referer=None,
        fetch_site=None,
    )
    assert not validate_request_origin(
        public_origin="https://example.test",
        origin="https://example.test",
        referer=None,
        fetch_site="cross-site",
    )


def test_referer_fallback_requires_same_origin() -> None:
    assert validate_request_origin(
        public_origin="http://localhost:5173",
        origin=None,
        referer="http://localhost:5173/account",
        fetch_site=None,
    )
    assert not validate_request_origin(
        public_origin="http://localhost:5173",
        origin=None,
        referer="http://localhost.attacker.test/account",
        fetch_site=None,
    )
