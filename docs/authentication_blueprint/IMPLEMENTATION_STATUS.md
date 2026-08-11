# Authentication Implementation Status

Status: code complete through AU-09; public enablement blocked by external release prerequisites

## Integration mapping

- FastAPI application: `src/illinois_lottery_tracker/api.py`, global `app`
- Authentication/account routers: sibling `auth_api.py` and `account_api.py`
- Database convention: synchronous SQLAlchemy; short explicit contexts around
  provider calls
- Public rankings: `/api/v1/rankings`; no authentication dependency or lookup
- Frontend: Vite/React with an existing `/api` development proxy
- Alembic head at start: `0008_review_remediations`

## Security-relevant rollout state

- `AUTH_ENABLED` defaults to `false`.
- Google production client/domain/policy/proxy/manual-smoke prerequisites remain
  external release gates and do not block automated implementation.
- No secrets, OAuth URLs, emails, subjects, or tokens are recorded here.

## Packet evidence

### AU-01

State: complete

- Added strict disabled-by-default auth configuration, purpose-separated crypto,
  provider/value-object seams, return-path allowlist, and pinned dependencies.
- `pytest tests/auth/test_config.py tests/auth/test_crypto.py tests/auth/test_return_paths.py -q`:
  46 passed.
- `ruff check src/illinois_lottery_tracker/auth tests/auth`: passed.
- `pytest -q`: 500 passed, 25 PostgreSQL-only skipped.

### AU-02

State: complete

- Added all five ORM tables and linear `0009_authentication` migration, full
  metadata registration, transaction-owned repository primitives, and
  PostgreSQL schema/migration/concurrency tests.
- `alembic heads`: `0009_authentication (head)`.
- Guarded disposable PostgreSQL run: 30 passed.
- Development database upgraded to `0009_authentication`; read-only auth audit:
  zero failures/backlogs in every invariant category.
- `pytest tests/auth/test_repository.py -q`: 2 passed.
- `ruff check .`: passed at packet boundary.

### AU-03

State: complete

- Added pinned Google discovery/authorization/token/JWKS validation, bounded
  transport, strict RS256 ID-token claims, verified-email normalization, and a
  token-free provider result.
- Added encrypted one-time attempt creation, supersession, atomic claim,
  cancellation/expiry/replay behavior, and fake-provider seams.
- `pytest tests/auth/test_google_oidc.py tests/auth/test_login_service.py -q`:
  15 passed.
- `ruff check src/illinois_lottery_tracker/auth tests/auth`: passed.

### AU-04

State: complete

- Added first/returning login finalization, canonical-identity conflict retry,
  stable parent-row session-cap locking, opaque session issuance, principal
  reconstruction, idle/absolute expiry, throttled touch, and revocation methods.
- Added purpose-separated session-bound CSRF tokens and exact-origin validation.
- `pytest tests/auth/test_session_service.py tests/auth/test_csrf.py -q`: 7 passed.
- Guarded disposable PostgreSQL concurrency target: 2 passed, including
  simultaneous first login with one user/identity and no orphan.
- Unrelated analytics integration currently has two import-collection failures;
  no analytics files were changed by authentication work.

### AU-05

State: complete

- Added disabled-by-default startup readiness, Google start/callback, exact
  session initialization, logout, session-list/revoke, and logout-all routes
  to the existing FastAPI app.
- Added bounded duplicate-aware callback/query and strict 1 KiB JSON parsing,
  session-bound CSRF/origin enforcement, exact cookie/cache/redirect behavior,
  server-owned request IDs, and callback query scrubbing before access logging.
- `pytest tests/api/test_auth_routes.py tests/api/test_auth_redaction.py -q`:
  10 passed.
- Combined login/middleware/auth-route/rankings regression target: 21 passed.
- Representative shared-metadata SQLite regression target after making ORM
  PostgreSQL checks conditional: 159 passed.
- `ruff check .`: passed.

- The full suite now reaches test execution without auth-created setup errors;
  seven analytics/catalog tests remain failing in concurrent data-integration
  changes and are outside authentication files.

### AU-06

State: complete

- Added typed in-memory session/CSRF state, bounded lifecycle and cross-tab
  revalidation, disabled/anonymous/authenticated/unavailable header controls,
  protected `/account` routing, session management, and Vite `/api` integration.
- Replaced CSP-incompatible inline metric widths with native progress elements
  while preserving visible values and mobile ranking order.
- Added reviewed static SPA fallback for `/` and `/account`; `/api/*` misses
  never receive SPA HTML.
- `npm test`: 25 passed at packet boundary.
- `npm run build`: passed.
- `npm run test:e2e`: 6 passed across desktop and 390-pixel mobile projects.
- Integrated auth API/static fallback target: 13 passed.

### AU-07

State: complete

- Added account read/delete routes, exact confirmation and recent-auth gates,
  same-user/session `reauth_delete` attempts, strict issuer/subject matching,
  session replacement, anonymized security events, and the explicit future
  user-data deletion hook.
- Added deletion/recent-identity-confirmation UI; confirmation text is discarded
  across reauthentication and the pinned Google URL is used only for immediate
  top-level navigation.
- Complete authentication service/API target: 92 passed.
- Disposable PostgreSQL schema/concurrency/cascade target: 6 passed.
- `npm test`: 29 passed; production build passed.
- `npm run test:e2e`: 8 passed across desktop and 390-pixel mobile projects.
- `ruff check .`: passed.

### AU-08

State: complete

- Added bounded concurrency-safe HMAC-pseudonymous source and local-user token
  buckets with exact reviewed route groups, one-hour idle eviction, 20,000-key
  cap, trusted-proxy resolution, pre-lookup 429s, clean callback 303s, and
  coalesced known-user rejection events.
- Added positive auth-event detail validation and production HSTS/CSP/no-sniff/
  referrer/permissions headers without CORS or `unsafe-inline`.
- Added deterministic 1,000-row maintenance batches, exact attempt/session/event
  retention, stuck-exchange recovery, original-inactivity session timestamps,
  counts-only dry-run/apply output, daily systemd units, and guarded UUID-only
  operator suspension/reactivation/revocation/deletion controls.
- Added backup/restore auth audits and isolation markers, CI Python/Node
  vulnerability reports plus browser E2E, and the production Google/proxy/
  privacy/secret/restore/incident runbook. Authentication remains disabled
  pending the external release gate.
- Focused AU-08 lint and acceptance target: 26 passed.
- Disposable PostgreSQL schema/concurrency/maintenance target: 7 passed.
- Disposable PostgreSQL maintenance dry-run and apply each reported zero
  remaining actions after the seeded retention test; every auth audit invariant,
  retention backlog, and detail-allowlist count was zero.
- `ruff check .`: passed.

### AU-09

State: code complete; public release intentionally disabled

- Added a continuous stateful fake-provider browser journey covering approved
  scope/PKCE, login/callback, refresh, HttpOnly cookie and empty storage,
  logout, callback replay rejection, recent-auth session rotation, confirmation
  discard, and account deletion. No request escapes the loopback/Google
  interception harness.
- The backup/restore gate exposed trigger-order-dependent event anonymization;
  added forward migration `0011_defer_auth_event_links` and proved user deletion
  on both fresh and restored PostgreSQL schemas. Development DB, `alembic heads`,
  and `alembic current` are all at the single `0011_defer_auth_event_links` head.
- `pytest -q`: 566 passed, 31 PostgreSQL-gated skipped, 3 dependency warnings.
- Guarded fresh PostgreSQL suite: 31 passed. Maintenance dry-run/apply each
  reported zero backlog after tests; every authentication audit invariant was
  zero. Guarded backup/restore then ran the complete restored PostgreSQL suite
  successfully and removed both disposable databases.
- `ruff check .` and `git diff --check`: passed.
- `npm test`: 40 passed across 11 files; `npm run build`: passed;
  `npm run test:e2e`: 10 passed across desktop and 390-pixel mobile projects.
- Python audit initially found patched-version advisories in cryptography,
  idna, soupsieve, urllib3, and the environment's installer. Constraints were
  reviewed/upgraded, the full suite passed with cryptography 50, and the final
  `pip-audit` reported no known vulnerabilities (the local package is not on
  PyPI). `npm audit --audit-level=high` reported zero vulnerabilities.
- Development maintenance dry-run reported zero eligible rows; the read-only
  development auth audit returned zero for every invariant, backlog, and
  detail-key check. Built-frontend secret/token identifier scan was clean.
- The designated real-Google smoke test was not run because no approved owned
  production domain, production Google client, published privacy/terms/contact
  set, or verified TLS-proxy rate-limit configuration was supplied. Per the
  blueprint, `AUTH_ENABLED` remains false and public sign-in must not be enabled.
