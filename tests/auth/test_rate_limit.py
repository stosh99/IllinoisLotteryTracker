from __future__ import annotations

from fastapi import Request

from illinois_lottery_tracker.auth.config import AuthSettings
from illinois_lottery_tracker.auth.rate_limit import (
    TokenBucketLimiter,
    resolved_client_source,
    route_policy,
)


class Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


def test_token_bucket_enforces_burst_refill_cap_and_idle_eviction() -> None:
    clock = Clock()
    limiter = TokenBucketLimiter(b"k" * 32, clock=clock, max_buckets=1)
    assert [limiter.consume_source("192.0.2.1", "login_start").allowed for _ in range(3)] == [
        True,
        True,
        True,
    ]
    rejected = limiter.consume_source("192.0.2.1", "login_start")
    assert not rejected.allowed and rejected.retry_after == 60 and rejected.notify
    assert not limiter.consume_source("192.0.2.1", "login_start").notify
    assert not limiter.consume_source("192.0.2.2", "login_start").allowed
    clock.value = 60
    assert limiter.consume_source("192.0.2.1", "login_start").allowed
    clock.value = 3_661
    assert limiter.consume_source("192.0.2.2", "login_start").allowed


def _request(peer: str, forwarded: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": forwarded,
            "client": (peer, 1234),
        }
    )


def test_client_source_ignores_untrusted_forwarding_and_walks_trusted_chain() -> None:
    forwarded = [(b"x-forwarded-for", b"198.51.100.8, 10.0.0.8")]
    assert resolved_client_source(_request("203.0.113.4", forwarded), AuthSettings()) == (
        "203.0.113.4"
    )
    settings = AuthSettings(trusted_proxy_hops=("10.0.0.0/8",))
    assert resolved_client_source(_request("10.0.0.9", forwarded), settings) == (
        "198.51.100.8"
    )


def test_route_policy_separates_callback_and_destructive_routes() -> None:
    assert route_policy("/api/v1/auth/google/callback", "GET") == "callback"
    assert route_policy("/api/v1/auth/google/reauth-delete", "POST") == "destructive"
    assert route_policy("/api/v1/account", "DELETE") == "destructive"
    assert route_policy("/api/v1/auth/session", "GET") == "read"
    assert route_policy("/api/v1/auth/logout", "POST") == "write"
    assert route_policy("/api/v1/rankings", "GET") is None
