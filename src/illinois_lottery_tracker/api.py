"""HTTP API for read-only public application data."""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .account_api import router as account_router
from .auth.rate_limit import default_limiter, resolved_client_source, route_policy
from .auth_api import default_auth_runtime
from .auth_api import router as auth_router
from .db import get_engine
from .game_details_api import (
    GameDetailReadError,
    GameDetailResponse,
    read_current_game_detail,
)
from .game_history_api import (
    GameHistoryReadError,
    GameHistoryResponse,
    read_current_game_history,
)
from .rankings_api import (
    RankingDatasetResponse,
    RankingReadError,
    read_current_rankings,
)

logger = logging.getLogger(__name__)

PRODUCTION_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'self'; "
    "object-src 'none'; frame-ancestors 'none'; form-action 'self'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self'; worker-src 'self'"
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail startup when database identity or enabled authentication is not ready."""
    get_engine()
    default_auth_runtime()
    yield


app = FastAPI(
    title="Illinois Lottery Tracker API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
# The project pins concrete API routes on the single application router. Using
# FastAPI's deferred include wrapper here would add a non-route sentinel to
# ``app.routes`` in newer FastAPI releases and break existing route inspection.
app.router.routes.extend(auth_router.routes)
app.router.routes.extend(account_router.routes)


@app.middleware("http")
async def request_id_header(request, call_next):
    """Generate a server-owned correlation ID without trusting inbound values."""
    request.state.request_id = uuid.uuid4()
    if request.url.path == "/api/v1/auth/google/callback":
        # The authorization code and state must not be retained by framework
        # access logging.  The auth router parses this private copy directly.
        request.state.oauth_query_string = request.scope.get("query_string", b"")
        request.scope["query_string"] = b""
    try:
        runtime = (
            request.app.state.auth_runtime
            if hasattr(request.app.state, "auth_runtime")
            else default_auth_runtime()
        )
    except Exception:
        runtime = None
    policy = route_policy(request.url.path, request.method)
    injected_limiter = getattr(request.app.state, "auth_limiter", None)
    if (
        runtime is not None
        and runtime.settings.enabled
        and policy is not None
        and (runtime.settings.app_env != "test" or injected_limiter is not None)
    ):
        limiter = injected_limiter
        if limiter is None:
            limiter = default_limiter(runtime.settings.root_keys[0])
        decision = limiter.consume_source(
            resolved_client_source(request, runtime.settings), policy
        )
        if not decision.allowed:
            if policy == "callback":
                response = RedirectResponse(
                    "/?authResult=failed",
                    status_code=303,
                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
                )
            else:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "type": "about:blank",
                        "title": "Too many requests",
                        "status": 429,
                        "code": "RATE_LIMITED",
                        "requestId": str(request.state.request_id),
                    },
                    media_type="application/problem+json",
                    headers={
                        "Cache-Control": "no-store",
                        "Retry-After": str(decision.retry_after),
                    },
                )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["X-Request-ID"] = str(request.state.request_id)
    if request.url.path.startswith(("/api/v1/auth", "/api/v1/account")):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
    if os.environ.get("APP_ENV") == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Content-Security-Policy", PRODUCTION_CSP)
    return response


@app.get(
    "/api/v1/rankings",
    response_model=RankingDatasetResponse,
    response_model_by_alias=True,
)
def get_rankings(response: Response) -> RankingDatasetResponse:
    """Return only the current ranking surface that passed publication gates."""
    try:
        document = read_current_rankings(get_engine())
    except (RankingReadError, SQLAlchemyError, ValidationError, RuntimeError):
        logger.exception("Unable to build the current rankings response")
        raise HTTPException(
            status_code=503,
            detail="Current ranking data is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from None

    response.headers["Cache-Control"] = "no-store"
    return document


@app.get(
    "/api/v1/games/{game_id}",
    response_model=GameDetailResponse,
    response_model_by_alias=True,
)
def get_game_detail(game_id: int, response: Response) -> GameDetailResponse:
    """Return current published prize-tier detail for one ranked game."""
    try:
        document = read_current_game_detail(get_engine(), game_id)
    except (GameDetailReadError, SQLAlchemyError, ValidationError, RuntimeError):
        logger.exception("Unable to build the current game-detail response")
        raise HTTPException(
            status_code=503,
            detail="Current game detail is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from None
    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Game not found in the current published comparison.",
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = "no-store"
    return document


@app.get(
    "/api/v1/games/{game_id}/history",
    response_model=GameHistoryResponse,
    response_model_by_alias=True,
)
def get_game_history(game_id: int, response: Response) -> GameHistoryResponse:
    """Return dated sales estimates and official tier-claim history."""
    try:
        document = read_current_game_history(get_engine(), game_id)
    except (GameHistoryReadError, SQLAlchemyError, ValidationError, RuntimeError):
        logger.exception("Unable to build the current game-history response")
        raise HTTPException(
            status_code=503,
            detail="Current game history is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from None
    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Game not found in the current published comparison.",
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = "no-store"
    return document


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.joinpath("index.html").is_file():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_frontend(spa_path: str) -> FileResponse:
        """Serve only reviewed SPA routes; never rewrite an API miss to HTML."""
        if spa_path not in {"", "account"} and re.fullmatch(
            r"games/[1-9][0-9]*", spa_path
        ) is None:
            raise HTTPException(status_code=404)
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
