"""OIDC provider seam used by services and deterministic tests."""

from __future__ import annotations

from typing import Protocol

from .types import ProviderExchangeRequest, VerifiedIdentity


class OidcProvider(Protocol):
    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        prompt: str | None = None,
    ) -> str: ...

    def exchange(self, request: ProviderExchangeRequest) -> VerifiedIdentity: ...
