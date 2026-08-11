"""FastAPI routes for Google login and local session management."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import inspect

from .api_dependencies import raw_cookie_values
from .auth.config import AuthSettings, load_auth_settings
from .auth.crypto import token_digest
from .auth.csrf import csrf_token, validate_csrf_token, validate_request_origin
from .auth.google_oidc import GoogleOidcProvider, OidcProviderError
from .auth.rate_limit import default_limiter
from .auth.return_paths import validate_return_path
from .auth.service import (
    AccountService,
    LoginAttemptError,
    LoginAttemptService,
    SessionService,
)
from .auth.types import AuthPrincipal, ProviderExchangeRequest
from .db import get_engine, get_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
AUTH_TABLES = {
    "app_users",
    "user_identities",
    "user_sessions",
    "oidc_login_attempts",
    "auth_events",
}


@dataclass(frozen=True)
class AuthRuntime:
    settings: AuthSettings
    provider: GoogleOidcProvider | None = None
    attempts: LoginAttemptService | None = None
    sessions: SessionService | None = None
    accounts: AccountService | None = None


@lru_cache(maxsize=1)
def default_auth_runtime() -> AuthRuntime:
    settings = load_auth_settings()
    if not settings.enabled:
        return AuthRuntime(settings=settings)
    if not AUTH_TABLES <= set(inspect(get_engine()).get_table_names()):
        raise RuntimeError("enabled authentication schema is not ready")
    provider = GoogleOidcProvider(settings)
    return AuthRuntime(
        settings=settings,
        provider=provider,
        attempts=LoginAttemptService(settings, provider, get_session),
        sessions=SessionService(settings, get_session),
        accounts=AccountService(settings, get_session),
    )


def auth_runtime(request: Request) -> AuthRuntime:
    injected = getattr(request.app.state, "auth_runtime", None)
    return injected if injected is not None else default_auth_runtime()


def _problem(request: Request, status: int, code: str, title: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid.uuid4())
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "code": code,
            "requestId": str(request_id),
        },
        media_type="application/problem+json",
        headers={"Cache-Control": "no-store"},
    )


def _unavailable(request: Request) -> JSONResponse:
    return _problem(request, 503, "AUTH_UNAVAILABLE", "Authentication unavailable")


def _timestamp(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _set_cookie(
    response: Response, settings: AuthSettings, name: str, value: str, age: int
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=age,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response, settings: AuthSettings, name: str) -> None:
    response.set_cookie(
        key=name,
        value="",
        max_age=0,
        expires=0,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(
        location,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _local_result(return_path: str, result: str) -> str:
    separator = "&" if "?" in return_path else "?"
    return f"{return_path}{separator}authResult={result}"


def _query_pairs(request: Request, *, callback: bool = False) -> list[tuple[str, str]]:
    raw = (
        getattr(request.state, "oauth_query_string", None)
        if callback
        else request.scope.get("query_string", b"")
    )
    if raw is None:
        raw = request.scope.get("query_string", b"")
    if not isinstance(raw, bytes) or len(raw) > 8192:
        raise ValueError("invalid query")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid query") from exc
    for index, character in enumerate(text):
        if character == "%" and (
            index + 2 >= len(text)
            or any(digit not in "0123456789abcdefABCDEF" for digit in text[index + 1 : index + 3])
        ):
            raise ValueError("invalid query")
    try:
        return parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=False,
            encoding="utf-8",
            errors="strict",
            max_num_fields=32,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid query") from exc


def _single_query(
    request: Request,
    name: str,
    *,
    required: bool = False,
    callback: bool = False,
    maximum: int = 256,
) -> str | None:
    values = [value for key, value in _query_pairs(request, callback=callback) if key == name]
    if len(values) > 1 or (required and len(values) != 1):
        raise ValueError("invalid query")
    value = values[0] if values else None
    if value is not None and (
        len(value) > maximum or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError("invalid query")
    return value


def _session_cookie(request: Request, settings: AuthSettings) -> tuple[str | None, bool]:
    values = raw_cookie_values(request, settings.session_cookie_name)
    return (values[0], False) if len(values) == 1 else (None, len(values) > 1)


def _principal(
    request: Request, runtime: AuthRuntime
) -> tuple[AuthPrincipal | None, str | None, bool]:
    raw, duplicate = _session_cookie(request, runtime.settings)
    if runtime.sessions is None:
        return None, raw, duplicate
    return runtime.sessions.resolve_principal(raw), raw, duplicate


def _known_user_rate_limit(
    request: Request,
    runtime: AuthRuntime,
    principal: AuthPrincipal,
    policy: str,
) -> JSONResponse | None:
    injected = getattr(request.app.state, "auth_limiter", None)
    if runtime.settings.app_env == "test" and injected is None:
        return None
    limiter = injected or default_limiter(runtime.settings.root_keys[0])
    decision = limiter.consume_user(str(principal.user_id), policy)
    if decision.allowed:
        return None
    if decision.notify and runtime.sessions is not None:
        try:
            runtime.sessions.record_rate_limited(principal)
        except Exception:
            pass
    response = _problem(request, 429, "RATE_LIMITED", "Too many requests")
    response.headers["Retry-After"] = str(decision.retry_after)
    return response


def _raw_header_values(request: Request, name: str) -> list[str]:
    lowered = name.lower().encode("ascii")
    return [
        value.decode("latin-1")
        for key, value in request.scope.get("headers", [])
        if key.lower() == lowered
    ]


async def _validate_unsafe(
    request: Request,
    runtime: AuthRuntime,
    principal: AuthPrincipal,
    raw_session: str,
    *,
    require_empty_json: bool,
    json_keys: frozenset[str] | None = None,
) -> JSONResponse | None:
    header_names = ["x-csrf-token", "origin", "referer", "sec-fetch-site", "content-type"]
    headers = {name: _raw_header_values(request, name) for name in header_names}
    if any(len(values) > 1 for values in headers.values()):
        return _problem(request, 403, "CSRF_INVALID", "Request verification failed")
    supplied = headers["x-csrf-token"][0] if headers["x-csrf-token"] else ""
    try:
        digest = token_digest(raw_session)
    except ValueError:
        return _problem(request, 403, "CSRF_INVALID", "Request verification failed")
    if not validate_csrf_token(
        supplied, principal.session_id, digest, runtime.settings.root_keys
    ) or not validate_request_origin(
        public_origin=runtime.settings.public_base_url or "",
        origin=headers["origin"][0] if headers["origin"] else None,
        referer=headers["referer"][0] if headers["referer"] else None,
        fetch_site=headers["sec-fetch-site"][0] if headers["sec-fetch-site"] else None,
    ):
        return _problem(request, 403, "CSRF_INVALID", "Request verification failed")
    body = await request.body()
    if len(body) > 1024:
        return _problem(request, 413, "REQUEST_TOO_LARGE", "Request too large")
    if require_empty_json or json_keys is not None:
        content_type = headers["content-type"][0] if headers["content-type"] else ""
        normalized = content_type.lower().replace(" ", "")
        if normalized not in {"application/json", "application/json;charset=utf-8"}:
            return _problem(
                request, 415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported media type"
            )
        try:
            document = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=lambda pairs: _unique_object(pairs),
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return _problem(request, 400, "INVALID_REQUEST", "Invalid request")
        if not isinstance(document, dict):
            return _problem(request, 400, "INVALID_REQUEST", "Invalid request")
        if require_empty_json and document != {}:
            return _problem(request, 400, "INVALID_REQUEST", "Invalid request")
        if json_keys is not None and set(document) != json_keys:
            return _problem(request, 400, "INVALID_REQUEST", "Invalid request")
        request.state.auth_document = document
    elif body:
        return _problem(request, 400, "INVALID_REQUEST", "Invalid request")
    return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@router.get("/session")
def get_auth_session(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled:
        return JSONResponse(
            {
                "authenticationAvailable": False,
                "authenticated": False,
                "user": None,
                "session": None,
                "csrfToken": None,
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Vary": "Cookie",
                "Referrer-Policy": "no-referrer",
            },
        )
    try:
        principal, raw, duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        response = JSONResponse(
            {
                "authenticationAvailable": True,
                "authenticated": False,
                "user": None,
                "session": None,
                "csrfToken": None,
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache", "Vary": "Cookie"},
        )
        if duplicate or raw:
            _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
        return response
    if problem := _known_user_rate_limit(request, runtime, principal, "read"):
        return problem
    digest = token_digest(raw)
    response = JSONResponse(
        {
            "authenticationAvailable": True,
            "authenticated": True,
            "user": {
                "id": str(principal.user_id),
                "email": principal.email,
                "emailVerified": True,
            },
            "session": {
                "authenticatedAt": _timestamp(principal.session_created_at),
                "idleExpiresAt": _timestamp(principal.idle_expires_at),
                "absoluteExpiresAt": _timestamp(principal.absolute_expires_at),
            },
            "csrfToken": csrf_token(
                principal.session_id, digest, runtime.settings.root_keys[0]
            ),
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache", "Vary": "Cookie"},
    )
    return response


@router.get("/google/start")
def google_start(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.attempts is None:
        return _unavailable(request)
    try:
        return_path = validate_return_path(
            _single_query(request, "returnTo", maximum=128)
        )
    except ValueError:
        return _problem(request, 400, "INVALID_RETURN_PATH", "Invalid return path")
    try:
        principal, raw_session, duplicate = _principal(request, runtime)
        if principal:
            return _redirect(return_path)
        binding_values = raw_cookie_values(request, runtime.settings.login_cookie_name)
        prior_binding = binding_values[0] if len(binding_values) == 1 else None
        started = runtime.attempts.start_login(return_path, prior_binding)
    except LoginAttemptError as exc:
        return _redirect(_local_result(return_path, exc.public_result))
    except Exception:
        return _unavailable(request)
    response = _redirect(started.authorization_url)
    _set_cookie(
        response,
        runtime.settings,
        runtime.settings.login_cookie_name,
        started.browser_binding,
        runtime.settings.login_attempt_seconds,
    )
    if duplicate or raw_session is not None:
        _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
    return response


@router.get("/google/callback")
def google_callback(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _redirect("/?authResult=failed")
    if (
        not runtime.settings.enabled
        or runtime.attempts is None
        or runtime.sessions is None
        or runtime.provider is None
    ):
        return _redirect("/?authResult=failed")
    try:
        state = _single_query(
            request, "state", required=True, callback=True, maximum=128
        )
        code = _single_query(request, "code", callback=True, maximum=4096)
        error = _single_query(request, "error", callback=True, maximum=256)
        issuer = _single_query(request, "iss", callback=True, maximum=256)
        binding_values = raw_cookie_values(request, runtime.settings.login_cookie_name)
        if state is None or len(binding_values) != 1:
            raise LoginAttemptError("failed")
        principal, _raw_session, _duplicate_session = _principal(request, runtime)
        claimed = runtime.attempts.claim_callback(
            state=state,
            browser_binding=binding_values[0],
            code=code,
            error=error,
            issuer=issuer,
            principal=principal,
        )
    except (ValueError, LoginAttemptError) as exc:
        result = exc.public_result if isinstance(exc, LoginAttemptError) else "failed"
        return_path = exc.return_path if isinstance(exc, LoginAttemptError) else "/"
        return _redirect(_local_result(return_path, result))
    except Exception:
        return _redirect(_local_result("/", "failed"))
    try:
        identity = runtime.provider.exchange(
            ProviderExchangeRequest(
                code=claimed.code,
                code_verifier=claimed.code_verifier,
                redirect_uri=runtime.settings.callback_url,
                expected_nonce_digest=claimed.nonce_digest,
            )
        )
        issued = (
            runtime.sessions.finalize_reauthentication(claimed, identity)
            if claimed.intent == "reauth_delete"
            else runtime.sessions.finalize_login(claimed, identity)
        )
    except LoginAttemptError as exc:
        _mark_exchange_failed(runtime.sessions, claimed.attempt_id, exc.reason_code)
        return _redirect(_local_result(claimed.return_path, exc.public_result))
    except OidcProviderError as exc:
        _mark_exchange_failed(runtime.sessions, claimed.attempt_id, exc.reason_code)
        return _redirect(_local_result(claimed.return_path, "failed"))
    except Exception:
        _mark_exchange_failed(
            runtime.sessions, claimed.attempt_id, "token_validation_failed"
        )
        return _redirect(_local_result(claimed.return_path, "failed"))
    response = _redirect(claimed.return_path)
    _set_cookie(
        response,
        runtime.settings,
        runtime.settings.session_cookie_name,
        issued.token,
        runtime.settings.session_absolute_seconds,
    )
    return response


@router.post("/google/reauth-delete")
async def reauth_delete(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if (
        not runtime.settings.enabled
        or runtime.sessions is None
        or runtime.attempts is None
    ):
        return _unavailable(request)
    try:
        principal, raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    if problem := _known_user_rate_limit(request, runtime, principal, "destructive"):
        return problem
    problem = await _validate_unsafe(
        request, runtime, principal, raw, require_empty_json=True
    )
    if problem:
        return problem
    binding_values = raw_cookie_values(request, runtime.settings.login_cookie_name)
    prior_binding = binding_values[0] if len(binding_values) == 1 else None
    try:
        started = runtime.attempts.start_reauth_delete(principal, prior_binding)
    except LoginAttemptError as exc:
        if exc.public_result == "in_progress":
            return _problem(
                request, 409, "AUTH_IN_PROGRESS", "Authentication in progress"
            )
        return _unavailable(request)
    except Exception:
        return _unavailable(request)
    response = JSONResponse(
        {"authorizationUrl": started.authorization_url},
        headers={"Cache-Control": "no-store"},
    )
    _set_cookie(
        response,
        runtime.settings,
        runtime.settings.login_cookie_name,
        started.browser_binding,
        runtime.settings.login_attempt_seconds,
    )
    return response


def _mark_exchange_failed(
    sessions: SessionService, attempt_id: uuid.UUID, reason: str
) -> None:
    try:
        sessions.mark_exchange_failed(attempt_id, reason)
    except Exception:
        # The browser still receives the bounded local failure redirect. A
        # maintenance pass can terminalize an abandoned exchanging attempt.
        return


@router.post("/logout")
async def logout(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.sessions is None:
        return _unavailable(request)
    try:
        principal, raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
        _clear_cookie(response, runtime.settings, runtime.settings.login_cookie_name)
        return response
    if problem := _known_user_rate_limit(request, runtime, principal, "write"):
        return problem
    problem = await _validate_unsafe(
        request, runtime, principal, raw, require_empty_json=True
    )
    if problem:
        return problem
    try:
        runtime.sessions.revoke_current(principal)
    except Exception:
        return _unavailable(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
    _clear_cookie(response, runtime.settings, runtime.settings.login_cookie_name)
    return response


@router.get("/sessions")
def list_sessions(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.sessions is None:
        return _unavailable(request)
    try:
        principal, _raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    if problem := _known_user_rate_limit(request, runtime, principal, "read"):
        return problem
    try:
        rows = runtime.sessions.list_active(principal)
    except Exception:
        return _unavailable(request)
    rows.sort(
        key=lambda row: (
            row.id != principal.session_id,
            -row.created_at.timestamp(),
            str(row.id),
        )
    )
    return JSONResponse(
        {
            "sessions": [
                {
                    "id": str(row.id),
                    "current": row.id == principal.session_id,
                    "createdAt": _timestamp(row.created_at),
                    "lastSeenAt": _timestamp(row.last_seen_at),
                    "idleExpiresAt": _timestamp(row.idle_expires_at),
                    "absoluteExpiresAt": _timestamp(row.absolute_expires_at),
                }
                for row in rows
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/sessions/{session_id}")
async def revoke_session(request: Request, session_id: str) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.sessions is None:
        return _unavailable(request)
    try:
        principal, raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    if problem := _known_user_rate_limit(request, runtime, principal, "write"):
        return problem
    problem = await _validate_unsafe(
        request, runtime, principal, raw, require_empty_json=False
    )
    if problem:
        return problem
    try:
        parsed_id = uuid.UUID(session_id)
        if str(parsed_id) != session_id:
            raise ValueError
    except ValueError:
        return _problem(request, 404, "SESSION_NOT_FOUND", "Session not found")
    try:
        revoked = runtime.sessions.revoke_owned(principal, parsed_id)
    except Exception:
        return _unavailable(request)
    if not revoked:
        return _problem(request, 404, "SESSION_NOT_FOUND", "Session not found")
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    if parsed_id == principal.session_id:
        _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
    return response


@router.post("/logout-all")
async def logout_all(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.sessions is None:
        return _unavailable(request)
    try:
        principal, raw, _duplicate = _principal(request, runtime)
    except Exception:
        return _unavailable(request)
    if principal is None or raw is None:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    if problem := _known_user_rate_limit(request, runtime, principal, "write"):
        return problem
    problem = await _validate_unsafe(
        request, runtime, principal, raw, require_empty_json=True
    )
    if problem:
        return problem
    try:
        runtime.sessions.revoke_all(principal)
    except Exception:
        return _unavailable(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
    _clear_cookie(response, runtime.settings, runtime.settings.login_cookie_name)
    return response
