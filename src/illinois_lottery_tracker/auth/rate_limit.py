"""Bounded, process-local authentication rate-limit backstop."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Request

from .config import AuthSettings
from .crypto import TELEMETRY_INFO, derive_key

MAX_BUCKETS = 20_000
IDLE_EVICTION_SECONDS = 3_600.0


@dataclass(frozen=True)
class RatePolicy:
    requests: int
    window_seconds: int
    burst: int | None = None

    @property
    def capacity(self) -> int:
        return self.requests if self.burst is None else self.burst


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after: int = 0
    notify: bool = False


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    used_at: float
    last_notification: float | None = None


POLICIES = {
    "login_start": RatePolicy(10, 600, 3),
    "callback": RatePolicy(30, 600, 10),
    "read": RatePolicy(120, 600, 30),
    "write": RatePolicy(60, 600),
    "destructive": RatePolicy(5, 3_600),
}


class TokenBucketLimiter:
    """Concurrency-safe limiter with pseudonymous source keys and a hard cap."""

    def __init__(
        self,
        root_key: bytes,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = MAX_BUCKETS,
    ):
        self._telemetry_key = derive_key(root_key, TELEMETRY_INFO)
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[bytes, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def consume_source(
        self, source: str, policy_name: str, *, cost: int = 1
    ) -> RateDecision:
        canonical = str(ipaddress.ip_address(source))
        digest = hmac.new(
            self._telemetry_key,
            f"source\0{canonical}\0{policy_name}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return self._consume(digest, POLICIES[policy_name], cost)

    def consume_user(
        self, user_id: str, policy_name: str, *, cost: int = 1
    ) -> RateDecision:
        digest = hmac.new(
            self._telemetry_key,
            f"user\0{user_id}\0{policy_name}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return self._consume(digest, POLICIES[policy_name], cost)

    def _consume(self, key: bytes, policy: RatePolicy, cost: int) -> RateDecision:
        if cost <= 0:
            raise ValueError("rate-limit cost must be positive")
        now = self._clock()
        with self._lock:
            self._evict_expired(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_buckets:
                    return RateDecision(False, 1, False)
                bucket = _Bucket(float(policy.capacity), now, now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                refill = elapsed * policy.requests / policy.window_seconds
                bucket.tokens = min(float(policy.capacity), bucket.tokens + refill)
                bucket.updated_at = now
                bucket.used_at = now
                self._buckets.move_to_end(key)
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return RateDecision(True)
            seconds_per_token = policy.window_seconds / policy.requests
            retry_after = max(1, math.ceil((cost - bucket.tokens) * seconds_per_token))
            notify = (
                bucket.last_notification is None
                or now - bucket.last_notification >= policy.window_seconds
            )
            if notify:
                bucket.last_notification = now
            return RateDecision(False, retry_after, notify)

    def _evict_expired(self, now: float) -> None:
        while self._buckets:
            key, bucket = next(iter(self._buckets.items()))
            if now - bucket.used_at <= IDLE_EVICTION_SECONDS:
                break
            self._buckets.pop(key)


@lru_cache(maxsize=3)
def default_limiter(root_key: bytes) -> TokenBucketLimiter:
    return TokenBucketLimiter(root_key)


def resolved_client_source(request: Request, settings: AuthSettings) -> str:
    """Resolve a canonical address, trusting forwarding only from reviewed peers."""

    peer = request.client.host if request.client is not None else "0.0.0.0"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return "0.0.0.0"
    networks = tuple(ipaddress.ip_network(value) for value in settings.trusted_proxy_hops)
    if not networks or not any(peer_address in network for network in networks):
        return str(peer_address)
    forwarded = request.headers.getlist("x-forwarded-for")
    if len(forwarded) != 1:
        return str(peer_address)
    try:
        chain = [ipaddress.ip_address(value.strip()) for value in forwarded[0].split(",")]
    except ValueError:
        return str(peer_address)
    if not chain or any(not value.strip() for value in forwarded[0].split(",")):
        return str(peer_address)
    for address in reversed(chain):
        if not any(address in network for network in networks):
            return str(address)
    return str(chain[0])


def route_policy(path: str, method: str) -> str | None:
    if path == "/api/v1/auth/google/callback":
        return "callback"
    if path == "/api/v1/auth/google/start":
        return "login_start"
    if path in {"/api/v1/auth/google/reauth-delete", "/api/v1/account"} and method in {
        "POST",
        "DELETE",
    }:
        return "destructive"
    if not path.startswith(
        ("/api/v1/auth", "/api/v1/account", "/api/v1/ticket-entries")
    ):
        return None
    return "read" if method in {"GET", "HEAD"} else "write"
