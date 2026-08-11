"""Framework-neutral authentication value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str
    email_verified: bool = True


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    session_created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str


@dataclass(frozen=True)
class ProviderExchangeRequest:
    code: str
    code_verifier: str
    redirect_uri: str
    expected_nonce_digest: bytes
