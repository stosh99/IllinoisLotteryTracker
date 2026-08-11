"""Login-attempt orchestration with short caller-owned database contexts."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_models import AppUser, OidcLoginAttempt, UserIdentity, UserSession
from .config import AuthSettings
from .crypto import AttemptCipher, pkce_challenge, pkce_verifier, random_token, token_digest
from .deletion import delete_user_owned_data
from .provider import OidcProvider
from .repository import AuthRepository
from .types import AuthPrincipal, VerifiedIdentity

SessionContextFactory = Callable[[], AbstractContextManager[Session]]


class LoginAttemptError(RuntimeError):
    def __init__(
        self,
        public_result: str,
        reason_code: str = "invalid_callback",
        *,
        return_path: str = "/",
    ):
        self.public_result = public_result
        self.reason_code = reason_code
        self.return_path = return_path
        super().__init__(reason_code)


@dataclass(frozen=True)
class LoginStart:
    authorization_url: str
    browser_binding: str
    attempt_id: uuid.UUID


@dataclass(frozen=True)
class ClaimedAttempt:
    attempt_id: uuid.UUID
    code: str
    code_verifier: str
    nonce_digest: bytes
    return_path: str
    intent: str
    expected_user_id: uuid.UUID | None
    expected_session_id: uuid.UUID | None


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True)
class AccountRecord:
    user_id: uuid.UUID
    email: str
    created_at: datetime


class AccountDeletionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _is_pinned_authorization_url(value: str) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "accounts.google.com"
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/o/oauth2/v2/auth"
        and bool(parsed.query)
        and not parsed.fragment
    )


class LoginAttemptService:
    def __init__(
        self,
        settings: AuthSettings,
        provider: OidcProvider,
        sessions: SessionContextFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.settings = settings
        self.provider = provider
        self.sessions = sessions
        self.clock = clock
        self.cipher = AttemptCipher(settings.root_keys)

    def start_login(self, return_path: str, previous_binding: str | None = None) -> LoginStart:
        now = self.clock()
        attempt_id = uuid.uuid4()
        state, nonce, binding = random_token(), random_token(), random_token()
        verifier = pkce_verifier()
        authorization_url = self.provider.build_authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=pkce_challenge(verifier),
            redirect_uri=self.settings.callback_url,
        )
        with self.sessions() as session:
            repository = AuthRepository(session)
            if previous_binding:
                try:
                    previous_digest = token_digest(previous_binding)
                except ValueError:
                    previous_digest = None
                if previous_digest:
                    previous = repository.attempt_by_binding_for_update(previous_digest)
                    if previous and previous.status == "pending":
                        previous.status = "superseded"
                        previous.completed_at = now
                        previous.failure_code = "attempt_superseded"
                        repository.append_event(
                            event_type=(
                                "reauth_failed"
                                if previous.intent == "reauth_delete"
                                else "login_failed"
                            ),
                            outcome="failure",
                            occurred_at=now,
                            attempt_id=previous.id,
                            reason_code="attempt_superseded",
                        )
                    elif (
                        previous
                        and previous.status == "exchanging"
                        and now < previous.expires_at + timedelta(seconds=30)
                    ):
                        raise LoginAttemptError("in_progress", "exchange_abandoned")
                    elif previous and previous.status == "exchanging":
                        previous.status = "failed"
                        previous.completed_at = now
                        previous.failure_code = "exchange_abandoned"
                        repository.append_event(
                            event_type=(
                                "reauth_failed"
                                if previous.intent == "reauth_delete"
                                else "login_failed"
                            ),
                            outcome="failure",
                            occurred_at=now,
                            attempt_id=previous.id,
                            reason_code="exchange_abandoned",
                        )
            row = OidcLoginAttempt(
                id=attempt_id,
                provider="google",
                state_digest=token_digest(state),
                browser_binding_digest=token_digest(binding),
                nonce_digest=token_digest(nonce),
                pkce_verifier_ciphertext=self.cipher.encrypt(attempt_id, verifier),
                return_path=return_path,
                intent="login",
                status="pending",
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.login_attempt_seconds),
            )
            repository.add(row)
            repository.append_event(
                event_type="login_started",
                outcome="info",
                occurred_at=now,
                attempt_id=attempt_id,
                details={"provider": "google", "intent": "login"},
            )
        return LoginStart(authorization_url, binding, attempt_id)

    def start_reauth_delete(
        self,
        principal: AuthPrincipal,
        previous_binding: str | None = None,
    ) -> LoginStart:
        """Build a same-identity reauth URL, then atomically persist its binding."""

        now = self.clock()
        attempt_id = uuid.uuid4()
        state, nonce, binding = random_token(), random_token(), random_token()
        verifier = pkce_verifier()
        authorization_url = self.provider.build_authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=pkce_challenge(verifier),
            redirect_uri=self.settings.callback_url,
            prompt="select_account",
        )
        if not _is_pinned_authorization_url(authorization_url):
            raise LoginAttemptError("failed", "provider_unavailable")
        with self.sessions() as session:
            repository = AuthRepository(session)
            user = repository.lock_user(principal.user_id)
            expected_session = repository.session_by_id_owned_for_update(
                principal.session_id, principal.user_id
            )
            if (
                user is None
                or user.status != "active"
                or expected_session is None
                or expected_session.revoked_at is not None
                or now >= expected_session.idle_expires_at
                or now >= expected_session.absolute_expires_at
            ):
                raise LoginAttemptError("failed", "account_unavailable")
            if previous_binding:
                try:
                    previous_digest = token_digest(previous_binding)
                except ValueError:
                    previous_digest = None
                if previous_digest:
                    previous = repository.attempt_by_binding_for_update(previous_digest)
                    if previous and previous.status == "pending":
                        previous.status = "superseded"
                        previous.completed_at = now
                        previous.failure_code = "attempt_superseded"
                        repository.append_event(
                            event_type=(
                                "reauth_failed"
                                if previous.intent == "reauth_delete"
                                else "login_failed"
                            ),
                            outcome="failure",
                            occurred_at=now,
                            attempt_id=previous.id,
                            reason_code="attempt_superseded",
                        )
                    elif (
                        previous
                        and previous.status == "exchanging"
                        and now < previous.expires_at + timedelta(seconds=30)
                    ):
                        raise LoginAttemptError("in_progress", "exchange_abandoned")
                    elif previous and previous.status == "exchanging":
                        previous.status = "failed"
                        previous.completed_at = now
                        previous.failure_code = "exchange_abandoned"
                        repository.append_event(
                            event_type=(
                                "reauth_failed"
                                if previous.intent == "reauth_delete"
                                else "login_failed"
                            ),
                            outcome="failure",
                            occurred_at=now,
                            attempt_id=previous.id,
                            reason_code="exchange_abandoned",
                        )
            row = OidcLoginAttempt(
                id=attempt_id,
                provider="google",
                state_digest=token_digest(state),
                browser_binding_digest=token_digest(binding),
                nonce_digest=token_digest(nonce),
                pkce_verifier_ciphertext=self.cipher.encrypt(attempt_id, verifier),
                return_path="/account",
                intent="reauth_delete",
                expected_user_id=principal.user_id,
                expected_session_id=principal.session_id,
                status="pending",
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.login_attempt_seconds),
            )
            repository.add(row)
            repository.append_event(
                event_type="reauth_started",
                outcome="info",
                occurred_at=now,
                user_id=principal.user_id,
                session_id=principal.session_id,
                attempt_id=attempt_id,
                details={"provider": "google", "intent": "reauth_delete"},
            )
        return LoginStart(authorization_url, binding, attempt_id)

    def claim_callback(
        self,
        *,
        state: str,
        browser_binding: str,
        code: str | None,
        error: str | None,
        issuer: str | None,
        principal: AuthPrincipal | None = None,
    ) -> ClaimedAttempt:
        try:
            state_digest = token_digest(state)
            binding_digest = token_digest(browser_binding)
        except ValueError as exc:
            raise LoginAttemptError("failed") from exc
        now = self.clock()
        terminal_error: LoginAttemptError | None = None
        claimed: ClaimedAttempt | None = None
        with self.sessions() as session:
            repository = AuthRepository(session)
            attempt = repository.attempt_by_state_for_update(state_digest)
            if (
                attempt is None
                or attempt.status != "pending"
                or not hmac.compare_digest(attempt.browser_binding_digest, binding_digest)
            ):
                raise LoginAttemptError("expired")
            event_type = "reauth_failed" if attempt.intent == "reauth_delete" else "login_failed"
            if now >= attempt.expires_at:
                self._fail_attempt(
                    repository, attempt, now, "expired", "attempt_expired", event_type
                )
                terminal_error = LoginAttemptError(
                    "expired", "attempt_expired", return_path=attempt.return_path
                )
            elif attempt.intent == "reauth_delete" and (
                principal is None
                or principal.user_id != attempt.expected_user_id
                or principal.session_id != attempt.expected_session_id
            ):
                self._fail_attempt(
                    repository,
                    attempt,
                    now,
                    "failed",
                    "invalid_callback",
                    event_type,
                    claimed=True,
                )
                terminal_error = LoginAttemptError(
                    "failed", return_path=attempt.return_path
                )
            elif issuer not in {None, "https://accounts.google.com", "accounts.google.com"}:
                self._fail_attempt(
                    repository,
                    attempt,
                    now,
                    "failed",
                    "invalid_callback",
                    event_type,
                    claimed=True,
                )
                terminal_error = LoginAttemptError(
                    "failed", return_path=attempt.return_path
                )
            elif error is not None:
                if code is not None:
                    reason, public, status = "invalid_callback", "failed", "failed"
                elif error == "access_denied":
                    reason, public, status = "user_denied", "cancelled", "denied"
                else:
                    reason, public, status = "provider_unavailable", "failed", "failed"
                self._fail_attempt(
                    repository, attempt, now, status, reason, event_type, claimed=True
                )
                terminal_error = LoginAttemptError(
                    public, reason, return_path=attempt.return_path
                )
            elif (
                not isinstance(code, str)
                or not 1 <= len(code) <= 4096
                or any(ord(character) < 0x20 for character in code)
            ):
                self._fail_attempt(
                    repository,
                    attempt,
                    now,
                    "failed",
                    "invalid_callback",
                    event_type,
                    claimed=True,
                )
                terminal_error = LoginAttemptError(
                    "failed", return_path=attempt.return_path
                )
            else:
                try:
                    verifier = self.cipher.decrypt(attempt.id, attempt.pkce_verifier_ciphertext)
                except ValueError:
                    self._fail_attempt(
                        repository,
                        attempt,
                        now,
                        "failed",
                        "attempt_decryption_failed",
                        event_type,
                        claimed=True,
                    )
                    terminal_error = LoginAttemptError(
                        "failed",
                        "attempt_decryption_failed",
                        return_path=attempt.return_path,
                    )
                else:
                    attempt.status = "exchanging"
                    attempt.claimed_at = now
                    session.flush()
                    claimed = ClaimedAttempt(
                        attempt_id=attempt.id,
                        code=code,
                        code_verifier=verifier,
                        nonce_digest=attempt.nonce_digest,
                        return_path=attempt.return_path,
                        intent=attempt.intent,
                        expected_user_id=attempt.expected_user_id,
                        expected_session_id=attempt.expected_session_id,
                    )
        if terminal_error:
            raise terminal_error
        if claimed is None:
            raise LoginAttemptError("failed")
        return claimed

    @staticmethod
    def _fail_attempt(
        repository: AuthRepository,
        attempt: OidcLoginAttempt,
        now: datetime,
        status: str,
        reason: str,
        event_type: str,
        *,
        claimed: bool = False,
    ) -> None:
        attempt.status = status
        if claimed:
            attempt.claimed_at = now
        attempt.completed_at = now
        attempt.failure_code = reason
        repository.append_event(
            event_type=event_type,
            outcome="failure",
            occurred_at=now,
            attempt_id=attempt.id,
            reason_code=reason,
        )


class SessionService:
    def __init__(
        self,
        settings: AuthSettings,
        sessions: SessionContextFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.settings = settings
        self.sessions = sessions
        self.clock = clock

    def finalize_login(
        self, claimed: ClaimedAttempt, identity: VerifiedIdentity
    ) -> IssuedSession:
        """Finalize a claimed ordinary login; retry one canonical-identity race."""

        for attempt_number in range(2):
            token = random_token()
            now = self.clock()
            issued: IssuedSession | None = None
            terminal_error: LoginAttemptError | None = None
            try:
                with self.sessions() as session:
                    repository = AuthRepository(session)
                    attempt = repository.attempt_by_id_for_update(claimed.attempt_id)
                    if (
                        attempt is None
                        or attempt.status != "exchanging"
                        or attempt.intent != "login"
                        or claimed.intent != "login"
                    ):
                        raise LoginAttemptError("expired")
                    external = repository.identity_by_subject(identity.issuer, identity.subject)
                    if external is None:
                        user = repository.add(
                            AppUser(
                                id=uuid.uuid4(),
                                status="active",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        external = repository.add(
                            UserIdentity(
                                id=uuid.uuid4(),
                                user_id=user.id,
                                provider="google",
                                issuer=identity.issuer,
                                subject=identity.subject,
                                email=identity.email,
                                email_verified=True,
                                last_authenticated_at=now,
                                created_at=now,
                            )
                        )
                    user = repository.lock_user(external.user_id)
                    if user is None:
                        raise LoginAttemptError("failed")
                    external.email = identity.email
                    external.email_verified = True
                    external.last_authenticated_at = now
                    if user.status != "active":
                        attempt.status = "failed"
                        attempt.completed_at = now
                        attempt.failure_code = "account_unavailable"
                        repository.append_event(
                            event_type="login_failed",
                            outcome="failure",
                            occurred_at=now,
                            user_id=user.id,
                            attempt_id=attempt.id,
                            reason_code="account_unavailable",
                        )
                        terminal_error = LoginAttemptError(
                            "account_unavailable", "account_unavailable"
                        )
                    else:
                        active = repository.active_sessions_for_update(user.id, now)
                        while len(active) >= self.settings.max_active_sessions:
                            oldest = active.pop(0)
                            oldest.revoked_at = now
                            oldest.revocation_reason = "session_limit"
                            repository.append_event(
                                event_type="session_revoked",
                                outcome="info",
                                occurred_at=now,
                                user_id=user.id,
                                session_id=oldest.id,
                                reason_code="session_limit",
                            )
                        row = repository.add(
                            UserSession(
                                id=uuid.uuid4(),
                                user_id=user.id,
                                token_digest=token_digest(token),
                                created_at=now,
                                last_seen_at=now,
                                idle_expires_at=now
                                + timedelta(seconds=self.settings.session_idle_seconds),
                                absolute_expires_at=now
                                + timedelta(seconds=self.settings.session_absolute_seconds),
                            )
                        )
                        user.last_login_at = now
                        user.updated_at = now
                        attempt.status = "succeeded"
                        attempt.completed_at = now
                        repository.append_event(
                            event_type="login_succeeded",
                            outcome="success",
                            occurred_at=now,
                            user_id=user.id,
                            session_id=row.id,
                            attempt_id=attempt.id,
                            details={"provider": "google", "intent": "login"},
                        )
                        issued = IssuedSession(
                            token=token,
                            session_id=row.id,
                            user_id=user.id,
                            email=external.email,
                            created_at=now,
                            idle_expires_at=row.idle_expires_at,
                            absolute_expires_at=row.absolute_expires_at,
                        )
            except IntegrityError:
                if attempt_number == 0:
                    continue
                raise
            if terminal_error:
                raise terminal_error
            if issued:
                return issued
            raise LoginAttemptError("failed")
        raise LoginAttemptError("failed")

    def finalize_reauthentication(
        self, claimed: ClaimedAttempt, identity: VerifiedIdentity
    ) -> IssuedSession:
        token = random_token()
        now = self.clock()
        issued: IssuedSession | None = None
        terminal_error: LoginAttemptError | None = None
        with self.sessions() as session:
            repository = AuthRepository(session)
            attempt = repository.attempt_by_id_for_update(claimed.attempt_id)
            if (
                attempt is None
                or attempt.status != "exchanging"
                or attempt.intent != "reauth_delete"
                or claimed.intent != "reauth_delete"
                or attempt.expected_user_id != claimed.expected_user_id
                or attempt.expected_session_id != claimed.expected_session_id
                or claimed.expected_user_id is None
                or claimed.expected_session_id is None
            ):
                raise LoginAttemptError("expired", return_path="/account")
            user = repository.lock_user(claimed.expected_user_id)
            external = repository.identity_by_subject(identity.issuer, identity.subject)
            prior = repository.session_by_id_owned_for_update(
                claimed.expected_session_id, claimed.expected_user_id
            )
            if (
                user is None
                or user.status != "active"
                or external is None
                or external.user_id != claimed.expected_user_id
                or prior is None
                or prior.revoked_at is not None
                or now >= prior.idle_expires_at
                or now >= prior.absolute_expires_at
            ):
                attempt.status = "failed"
                attempt.completed_at = now
                attempt.failure_code = "identity_mismatch"
                repository.append_event(
                    event_type="reauth_failed",
                    outcome="failure",
                    occurred_at=now,
                    user_id=claimed.expected_user_id,
                    attempt_id=attempt.id,
                    reason_code="identity_mismatch",
                )
                terminal_error = LoginAttemptError(
                    "failed", "identity_mismatch", return_path="/account"
                )
            else:
                prior.revoked_at = now
                prior.revocation_reason = "replaced"
                external.email = identity.email
                external.email_verified = True
                external.last_authenticated_at = now
                row = repository.add(
                    UserSession(
                        id=uuid.uuid4(),
                        user_id=user.id,
                        token_digest=token_digest(token),
                        created_at=now,
                        last_seen_at=now,
                        idle_expires_at=now
                        + timedelta(seconds=self.settings.session_idle_seconds),
                        absolute_expires_at=now
                        + timedelta(seconds=self.settings.session_absolute_seconds),
                    )
                )
                user.last_login_at = now
                user.updated_at = now
                attempt.status = "succeeded"
                attempt.completed_at = now
                repository.append_event(
                    event_type="reauth_succeeded",
                    outcome="success",
                    occurred_at=now,
                    user_id=user.id,
                    session_id=row.id,
                    attempt_id=attempt.id,
                    details={"provider": "google", "intent": "reauth_delete"},
                )
                issued = IssuedSession(
                    token=token,
                    session_id=row.id,
                    user_id=user.id,
                    email=external.email,
                    created_at=now,
                    idle_expires_at=row.idle_expires_at,
                    absolute_expires_at=row.absolute_expires_at,
                )
        if terminal_error:
            raise terminal_error
        if issued is None:
            raise LoginAttemptError("failed", return_path="/account")
        return issued

    def mark_exchange_failed(self, attempt_id: uuid.UUID, reason: str) -> None:
        if reason not in {
            "provider_unavailable",
            "token_exchange_failed",
            "token_validation_failed",
            "identity_mismatch",
            "account_unavailable",
        }:
            reason = "token_validation_failed"
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            attempt = repository.attempt_by_id_for_update(attempt_id)
            if attempt is None or attempt.status != "exchanging":
                return
            attempt.status = "failed"
            attempt.completed_at = now
            attempt.failure_code = reason
            repository.append_event(
                event_type="reauth_failed" if attempt.intent == "reauth_delete" else "login_failed",
                outcome="failure",
                occurred_at=now,
                attempt_id=attempt.id,
                reason_code=reason,
            )

    def resolve_principal(self, encoded_token: str | None) -> AuthPrincipal | None:
        if not encoded_token:
            return None
        try:
            digest = token_digest(encoded_token)
        except ValueError:
            return None
        now = self.clock()
        principal: AuthPrincipal | None = None
        with self.sessions() as session:
            repository = AuthRepository(session)
            result = repository.principal_rows(digest)
            if result is None:
                return None
            row, user, identity = result
            if row.revoked_at is not None or user.status != "active" or row.created_at > now:
                return None
            if now >= row.absolute_expires_at or now >= row.idle_expires_at:
                row.revoked_at = now
                row.revocation_reason = (
                    "expired_absolute" if now >= row.absolute_expires_at else "expired_idle"
                )
                repository.append_event(
                    event_type="session_rejected",
                    outcome="failure",
                    occurred_at=now,
                    user_id=user.id,
                    session_id=row.id,
                    reason_code=row.revocation_reason,
                )
                return None
            if now - row.last_seen_at >= timedelta(seconds=self.settings.session_touch_seconds):
                row.last_seen_at = now
                row.idle_expires_at = min(
                    now + timedelta(seconds=self.settings.session_idle_seconds),
                    row.absolute_expires_at,
                )
            principal = AuthPrincipal(
                user_id=user.id,
                session_id=row.id,
                email=identity.email,
                session_created_at=row.created_at,
                idle_expires_at=row.idle_expires_at,
                absolute_expires_at=row.absolute_expires_at,
            )
        return principal

    def revoke_current(self, principal: AuthPrincipal, reason: str = "logout") -> bool:
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            repository.lock_user(principal.user_id)
            row = repository.session_by_id_owned_for_update(
                principal.session_id, principal.user_id
            )
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = now
            row.revocation_reason = reason
            repository.append_event(
                event_type="logout" if reason == "logout" else "session_revoked",
                outcome="success" if reason == "logout" else "info",
                occurred_at=now,
                user_id=principal.user_id,
                session_id=row.id,
                reason_code=None if reason == "logout" else reason,
            )
        return True

    def revoke_all(self, principal: AuthPrincipal) -> int:
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            repository.lock_user(principal.user_id)
            count = repository.revoke_active_sessions(principal.user_id, now, "logout_all")
            repository.append_event(
                event_type="logout_all",
                outcome="success",
                occurred_at=now,
                user_id=principal.user_id,
                session_id=principal.session_id,
                details={"sessions_revoked": count},
            )
        return count

    def list_active(self, principal: AuthPrincipal) -> list[UserSession]:
        with self.sessions() as session:
            return AuthRepository(session).active_sessions(principal.user_id, self.clock())

    def revoke_owned(self, principal: AuthPrincipal, session_id: uuid.UUID) -> bool:
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            repository.lock_user(principal.user_id)
            row = repository.session_by_id_owned_for_update(session_id, principal.user_id)
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = now
            row.revocation_reason = "security_event"
            repository.append_event(
                event_type="session_revoked",
                outcome="info",
                occurred_at=now,
                user_id=principal.user_id,
                session_id=row.id,
                reason_code="security_event",
            )
        return True

    def record_rate_limited(self, principal: AuthPrincipal) -> None:
        """Append one caller-coalesced event for a known-user bucket rejection."""

        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            user = repository.lock_user(principal.user_id)
            row = repository.session_by_id_owned_for_update(
                principal.session_id, principal.user_id
            )
            if user is None or row is None:
                return
            repository.append_event(
                event_type="session_rejected",
                outcome="failure",
                occurred_at=now,
                user_id=principal.user_id,
                session_id=principal.session_id,
                reason_code="rate_limited",
            )


class AccountService:
    def __init__(
        self,
        settings: AuthSettings,
        sessions: SessionContextFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.settings = settings
        self.sessions = sessions
        self.clock = clock

    def read_account(self, principal: AuthPrincipal) -> AccountRecord:
        with self.sessions() as session:
            repository = AuthRepository(session)
            user = repository.user_by_id(principal.user_id)
            if user is None or user.status != "active":
                raise AccountDeletionError("AUTH_REQUIRED")
            return AccountRecord(principal.user_id, principal.email, user.created_at)

    def delete_account(self, principal: AuthPrincipal) -> None:
        now = self.clock()
        with self.sessions() as session:
            repository = AuthRepository(session)
            user = repository.lock_user(principal.user_id)
            current = repository.session_by_id_owned_for_update(
                principal.session_id, principal.user_id
            )
            if (
                user is None
                or user.status != "active"
                or current is None
                or current.revoked_at is not None
                or now >= current.idle_expires_at
                or now >= current.absolute_expires_at
            ):
                raise AccountDeletionError("AUTH_REQUIRED")
            if (
                current.created_at > now
                or now - current.created_at
                > timedelta(seconds=self.settings.recent_login_seconds)
            ):
                raise AccountDeletionError("RECENT_AUTH_REQUIRED")
            delete_user_owned_data(session, user.id)
            repository.append_event(
                event_type="account_deleted",
                outcome="success",
                occurred_at=now,
                user_id=user.id,
                session_id=current.id,
                reason_code="user_request",
            )
            repository.delete_user(user)
