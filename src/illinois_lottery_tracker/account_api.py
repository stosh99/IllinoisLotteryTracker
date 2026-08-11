"""Authenticated local-account read and deletion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .auth.service import AccountDeletionError
from .auth_api import (
    _clear_cookie,
    _known_user_rate_limit,
    _principal,
    _problem,
    _timestamp,
    _unavailable,
    _validate_unsafe,
    auth_runtime,
)

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.get("")
def get_account(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if not runtime.settings.enabled or runtime.accounts is None:
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
        account = runtime.accounts.read_account(principal)
    except AccountDeletionError:
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    except Exception:
        return _unavailable(request)
    return JSONResponse(
        {
            "id": str(account.user_id),
            "email": account.email,
            "emailVerified": True,
            "createdAt": _timestamp(account.created_at),
        },
        headers={"Cache-Control": "no-store", "Vary": "Cookie"},
    )


@router.delete("")
async def delete_account(request: Request) -> Response:
    try:
        runtime = auth_runtime(request)
    except Exception:
        return _unavailable(request)
    if (
        not runtime.settings.enabled
        or runtime.accounts is None
        or runtime.sessions is None
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
        request,
        runtime,
        principal,
        raw,
        require_empty_json=False,
        json_keys=frozenset({"confirmation"}),
    )
    if problem:
        return problem
    document = request.state.auth_document
    if document["confirmation"] != "DELETE MY ACCOUNT":
        return _problem(
            request, 400, "CONFIRMATION_REQUIRED", "Confirmation required"
        )
    try:
        runtime.accounts.delete_account(principal)
    except AccountDeletionError as exc:
        if exc.code == "RECENT_AUTH_REQUIRED":
            return _problem(
                request,
                403,
                "RECENT_AUTH_REQUIRED",
                "Recent authentication required",
            )
        return _problem(request, 401, "AUTH_REQUIRED", "Authentication required")
    except Exception:
        return _unavailable(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    _clear_cookie(response, runtime.settings, runtime.settings.session_cookie_name)
    _clear_cookie(response, runtime.settings, runtime.settings.login_cookie_name)
    return response
