# Authentication Implementation Work Packets

## Execution rules

These packets are ordered for a lower-effort implementation agent. Complete
one packet, run its acceptance checks, and record the exact result before
starting the next.

- Read this blueprint's README and every document referenced by the packet.
- Inspect the current working tree before every packet; the API/data
  integration may have changed paths or dependencies.
- Preserve unrelated and uncommitted work.
- Attach to the existing API server; never create a second web application.
- At the design cutoff the app is `src/illinois_lottery_tracker/api.py`; do not
  create a colliding `api/` package unless intervening integration work has
  already and deliberately converted the layout.
- Add tests in the same packet as behavior.
- Use the then-current single Alembic head. Never create a branch head.
- Never call live Google from unit/CI tests.
- Never log or persist a provider/application credential.
- Never weaken a negative test to make an implementation pass.
- Record progress in
  `docs/authentication_blueprint/IMPLEMENTATION_STATUS.md`, created by AU-01.
- Stop only for a genuine external blocker or a conflict the blueprint does
  not resolve.

Dependency flow:

```text
AU-01 -> AU-02 -> AU-03 -> AU-04 -> AU-05 -> AU-06 -> AU-07 -> AU-08 -> AU-09
```

The status file contains: current packet/state; integration path mapping;
files changed; migrations/config/dependencies added; exact acceptance commands
with exit/result counts; security-relevant deviations and their blueprint
resolution; and external public-enable prerequisites. Never paste environment
values, URLs containing OAuth parameters, emails, tokens, or other secrets into
it. Mark only one packet in progress and do not mark complete on code presence
without acceptance evidence.

## AU-01 — Integration boundary, configuration, and crypto primitives

### Read first

- `README.md`
- `01_architecture_and_decisions.md`
- cryptographic/configuration sections of
  `03_oidc_and_session_flows.md` and
  `05_security_privacy_and_operations.md`

### Scope

- Record the API application object/factory, router, database-session, error, request
  ID, and deployment conventions produced by the data-integration work.
- Add validated auth configuration to the existing settings system.
- Add framework-neutral auth types, provider protocol, and cryptographic
  primitives.
- Add the implementation-status file and dependencies needed by this packet.
- Do not add routes, database tables, or frontend authentication UI.

### Expected files

```text
pyproject.toml / dependency lock or requirements mirror
.env.example
src/illinois_lottery_tracker/auth/__init__.py
src/illinois_lottery_tracker/auth/config.py
src/illinois_lottery_tracker/auth/types.py
src/illinois_lottery_tracker/auth/crypto.py
src/illinois_lottery_tracker/auth/provider.py
tests/auth/test_config.py
tests/auth/test_crypto.py
tests/auth/test_return_paths.py
docs/authentication_blueprint/IMPLEMENTATION_STATUS.md
```

Use the actual API paths if they differ; record the mapping rather than
duplicating infrastructure.

### Required behavior

- Production config fails every unsafe case in the configuration test matrix.
- Auth defaults disabled so the existing rankings deployment needs no Google
  secret; enabling it activates the complete config/schema readiness gate.
- Development HTTP is loopback-only and uses separate cookie names.
- Google discovery is a production code constant.
- Root secrets support newest-first rotation and purpose-separated keys.
- State/nonce/binding/session generation and digest rules are exact.
- PKCE is S256 and matches a published test vector.
- Return paths use an exact allowlist and reject all documented bypasses.
- Secret settings have redacted representations.

### Acceptance

```text
pytest tests/auth/test_config.py tests/auth/test_crypto.py tests/auth/test_return_paths.py
ruff check src/illinois_lottery_tracker/auth tests/auth
pytest
```

Review the built frontend and repository text to confirm no `AUTH_SECRET_KEYS`
or Google client secret value is present.

## AU-02 — Authentication schema, migration, and repository

### Read first

- `02_schema_and_lifecycle.md`
- migration requirements in `06_testing_and_acceptance.md`

### Scope

- Add all five auth ORM tables and one linear Alembic revision.
- Ensure Alembic/schema tests load full metadata.
- Add repository methods with no provider or HTTP logic.
- Add retention query primitives, but not the maintenance CLI.

### Expected files

```text
src/illinois_lottery_tracker/auth_models.py
src/illinois_lottery_tracker/auth/repository.py
alembic/env.py
alembic/versions/<next>_authentication.py
tests/auth/test_repository.py
tests/postgres/test_auth_schema.py
tests/postgres/test_auth_migration.py
tests/postgres/test_auth_concurrency.py
tests/postgres/test_migration_smoke.py
```

### Required behavior

- ORM and migration match every column, FK, check, unique key, and index in the
  schema specification.
- No email unique constraint exists.
- No OAuth/provider token column exists.
- Fresh and populated migrations preserve existing data.
- Concurrent identity creation leaves one identity/user and no orphan user.
- Attempt claim and session-limit repository operations use row locking and
  deterministic transactions.
- Repository methods accept an injected clock/service data and never commit
  invisibly inside a larger service transaction unless explicitly named.

### Acceptance

```text
alembic heads
alembic upgrade head
pytest tests/auth/test_repository.py
pytest tests/postgres/test_auth_schema.py tests/postgres/test_auth_migration.py tests/postgres/test_auth_concurrency.py
pytest
ruff check .
```

Run `auth_audit_queries.sql` against the migrated development database; empty
auth tables should produce zero invariant failures.

## AU-03 — Google OIDC provider and one-time login attempts

### Read first

- Google minimization and identity decisions in
  `01_architecture_and_decisions.md`
- Flows A and B in `03_oidc_and_session_flows.md`
- provider/OIDC and login-attempt tests in
  `06_testing_and_acceptance.md`

### Scope

- Implement the Google provider adapter using the selected maintained OIDC
  library.
- Implement authorization URL construction, token exchange, and strict claim
  validation.
- Implement start/claim/finalize attempt service logic without HTTP routes.
- Add a fake provider and local/mock OIDC server tests.

### Expected files

```text
src/illinois_lottery_tracker/auth/google_oidc.py
src/illinois_lottery_tracker/auth/service.py
tests/auth/fakes.py
tests/auth/test_google_oidc.py
tests/auth/test_login_service.py
```

### Required behavior

- Authorization URL requests exactly `openid email`, code flow, state, nonce,
  and PKCE S256.
- Callback URI comes from validated configuration only.
- Attempt is committed as `exchanging` before any network request.
- Every ID-token rejection case fails closed.
- Issuer/subject is the identity; email collision never links.
- Access/refresh/raw ID tokens disappear at the provider boundary.
- Provider timeout/error text maps to bounded internal codes and is redacted.
- Callback/attempt replay performs no second token exchange.

### Acceptance

```text
pytest tests/auth/test_google_oidc.py tests/auth/test_login_service.py
pytest tests/postgres/test_auth_concurrency.py
ruff check .
pytest
```

Run a captured-log scan using distinctive fake credentials and verify zero
matches outside test inputs/assertions.

## AU-04 — Session service, principal, and CSRF enforcement

### Read first

- session schema in `02_schema_and_lifecycle.md`
- Flows C and D in `03_oidc_and_session_flows.md`
- session/CSRF tests in `06_testing_and_acceptance.md`

### Scope

- Complete first/returning login finalization and session issuance.
- Implement optional/required principal resolution for the existing API
  framework.
- Implement idle/absolute expiration, throttled touches, session cap, and
  revocation.
- Implement derived session-bound CSRF tokens and unsafe-method enforcement.
- Do not add public routes or frontend UI yet.

### Expected files

```text
src/illinois_lottery_tracker/auth/service.py
src/illinois_lottery_tracker/auth/csrf.py
src/illinois_lottery_tracker/api_dependencies.py  # or newer existing equivalent
tests/auth/test_session_service.py
tests/auth/test_csrf.py
tests/api/test_auth_middleware.py
```

### Required behavior

- Database sees only session-token digest.
- Active principal checks session state, deadlines, and current user status.
- Expired/revoked/invalid cookie never authenticates.
- Touches are throttled and cannot extend absolute expiry.
- Sixth session revokes the oldest under concurrency.
- CSRF validates HMAC, exact origin/referrer, Fetch Metadata, and content type.
- Public rankings remain unchanged and receive no global/optional auth-table
  lookup; session initialization is a separate frontend request.
- No session is hard-bound to raw IP/user agent.

### Acceptance

```text
pytest tests/auth/test_session_service.py tests/auth/test_csrf.py
pytest tests/api/test_auth_middleware.py
pytest tests/postgres/test_auth_concurrency.py
ruff check .
pytest
```

## AU-05 — Core authentication API routes

### Read first

- Flows A through F in `03_oidc_and_session_flows.md`
- login/session portions of `04_api_and_frontend_contract.md`

### Scope

- Add Google start/callback, session, logout, session-list/revoke, and logout-all
  endpoints to the existing API server.
- Apply cookie, cache, error, redirect, and header contracts.
- Add route-level contract and redaction tests.
- Do not add account deletion or frontend UI yet.

### Expected files

```text
src/illinois_lottery_tracker/auth_api.py  # or newer existing router convention
src/illinois_lottery_tracker/api.py       # minimal router/middleware wiring only
tests/api/test_auth_routes.py
tests/api/test_auth_redaction.py
```

### Required behavior

- Start/callback are clean 303 redirects with one-time browser binding.
- Start/callback parse bounded raw query parameters so duplicate/malformed
  security keys follow the documented result contract instead of FastAPI 422.
- Callback sets cookies only after commit and never renders provider values.
- Session response exactly matches the discriminated contract and returns 503
  when state cannot be determined.
- Logout behavior distinguishes no/invalid session from active-session CSRF.
- Unsafe FastAPI routes enforce auth/rate/CSRF and the 1 KiB strict JSON parser
  in blueprint order; default pre-dependency body parsing/422 responses do not
  bypass that contract.
- Session management is strictly owner-scoped.
- Every auth response is no-store and cookies have exact environment-specific
  attributes.
- Callback query strings and cookies are absent from access/application logs.
- Existing rankings endpoint behavior and contract tests remain unchanged.
- Disabled auth makes session return the disabled 200 contract, callback return
  a clean 303, and the remaining auth/account routes return bounded 503s; it
  does no auth lookup and leaves rankings normal.

### Acceptance

```text
pytest tests/api/test_auth_routes.py tests/api/test_auth_redaction.py
pytest
ruff check .
```

Use an HTTP client to inspect every `Location`, `Set-Cookie`, cache, and Vary
header in both development and production-configured test applications.

## AU-06 — Frontend authentication seam

### Read first

- frontend state/UI sections of `04_api_and_frontend_contract.md`
- frontend/browser tests in `06_testing_and_acceptance.md`
- current frontend integration documentation and design system

### Scope

- Add typed session loading and in-memory CSRF state.
- Add/reuse the minimal `/` and `/account` client routing seam and static SPA
  fallback without rewriting `/api/*`.
- Add accessible disabled/anonymous/loading/authenticated/unavailable header
  states.
- Add account menu, sign-in navigation, logout, and sessions view.
- Replace the two existing inline-width ranking bars with semantic progress or
  stylesheet-only equivalents so the production CSP needs no `unsafe-inline`.
- Add the Vite `/api` development proxy without disturbing live rankings.
- Do not add personal ticket/outcome tracking.

### Expected files

```text
frontend/package.json
frontend/package-lock.json
frontend/src/types/auth.ts
frontend/src/services/auth.ts
frontend/src/context/AuthSessionProvider.tsx
frontend/src/hooks/useAuthSession.ts
frontend/src/components/SignInControl.tsx
frontend/src/components/AccountMenu.tsx
frontend/src/components/SessionList.tsx
frontend/src/pages/AccountPage.tsx
frontend/src/**/*.test.ts(x)
frontend/playwright.config.ts
frontend/e2e/auth.spec.ts
frontend/vite.config.ts
frontend/README.md
```

### Required behavior

- Public rankings load regardless of auth disabled/anonymous/unavailable state.
- `/` remains the ranking route; `/account` is protected in the UI and works
  on direct load/refresh; `/api/*` is never served SPA HTML.
- Google provider logic/tokens never enter React.
- CSRF token remains in memory and is attached only to unsafe same-origin
  application requests.
- Cross-tab/lifecycle coordination uses only fixed nonsecret BroadcastChannel
  signals plus bounded BFCache/visibility revalidation.
- Unsafe writes are not automatically replayed after 401.
- Auth result code is bounded, displayed accessibly, then removed from URL.
- Account controls work by keyboard/screen reader and at mobile widths.
- No session/CSRF/provider credential enters storage, a service-worker cache,
  local URL state, telemetry, or console. The returned reauth authorization
  URL is used once for immediate top-level Google navigation and is never
  placed in application storage, telemetry, or logs.

### Acceptance

```text
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e
pytest
```

Run browser checks at desktop and 390-pixel mobile widths with the fake local
provider. Assert no unexpected console/page/network errors.

## AU-07 — Account lifecycle and recent reauthentication

### Read first

- Flow G in `03_oidc_and_session_flows.md`
- account endpoints in `04_api_and_frontend_contract.md`
- lifecycle/deletion tests in `06_testing_and_acceptance.md`

### Scope

- Add account read, reauth-delete, and delete endpoints.
- Implement same-identity reauthentication and session replacement.
- Add frontend confirmation/recent-auth recovery UI.
- Prove future user-owned tables have an explicit deletion integration seam,
  but do not create personal tracking tables.

### Expected files

```text
src/illinois_lottery_tracker/account_api.py
src/illinois_lottery_tracker/auth/service.py
tests/auth/test_account_lifecycle.py
tests/api/test_account_routes.py
frontend/src/components/AccountSettings.tsx
frontend/src/components/AccountSettings.test.tsx
```

### Required behavior

- Reauth attempt records expected local user and exact initiating session.
- Reauth initialization is POST-only, requires CSRF, and returns the bounded
  pinned Google authorization URL used for top-level navigation; frontend
  validates its exact scheme, host, path, and no credentials/fragment.
- Callback issuer/subject must match; same email is insufficient.
- Successful reauth replaces/revokes old session.
- Delete requires exact confirmation, CSRF, and ten-minute recent auth.
- Committed delete cascades auth data, anonymizes event links, and clears
  cookies.
- Login after deletion creates a new unrelated account.

### Acceptance

```text
pytest tests/auth/test_account_lifecycle.py tests/api/test_account_routes.py
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e
pytest
ruff check .
```

## AU-08 — Operations, retention, suspension, and production hardening

### Read first

- all of `05_security_privacy_and_operations.md`
- audit SQL and operational tests in `06_testing_and_acceptance.md`

### Scope

- Add auth retention maintenance and guarded user-management CLI.
- Configure exact security/cache/proxy/access-log behavior in the existing
  deployment.
- Extend backup/restore documentation and checks for personal-data storage,
  isolated restores, and mandatory restored-session/attempt invalidation.
- Add rate limiting at the appropriate existing proxy/application layer.
- Implement the bounded in-process limiter backstop and document the external
  TLS-proxy limit as a public-enable prerequisite.
- Document Google development/production setup, secret rotation, privacy/terms
  prerequisites, and incident procedures.
- Add CI dependency-audit reporting and scheduled/explicit auth maintenance.

### Expected files

```text
scripts/maintain_authentication.py
scripts/manage_user_account.py
tests/auth/test_maintenance.py
tests/test_auth_scripts.py
deploy/*
.github/workflows/ci.yml
.env.example
README.md
docs/authentication_blueprint/IMPLEMENTATION_STATUS.md
```

Preserve and integrate with deployment/API changes already present; do not
replace the working data pipeline service.

### Required behavior

- Maintenance defaults dry-run and enforces all retention windows.
- User mutations require UUID plus an allowlisted explicit reason code and
  append events.
- Operator deletion requires matching UUID confirmation, reviewed reason code,
  dry-run/apply, and the same complete cascade as self-service deletion.
- Suspension/revocation are one transaction; reactivation issues no session.
- Proxy omits callback query/cookie logging and trusts only configured hops.
- Production headers, exact-origin policy, HTTPS, and startup failures match
  the blueprint.
- Rate limits return bounded 429 without PII.
- No secret appears in unit files, Git diff, built frontend, or logs.

### Acceptance

```text
pytest tests/auth/test_maintenance.py tests/test_auth_scripts.py
ruff check .
pytest
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e
```

Run maintenance dry-run then apply in a disposable PostgreSQL database and run
all audit queries. Record counts.

## AU-09 — End-to-end security and release gate

### Read first

- all blueprint documents;
- every prior packet entry in `IMPLEMENTATION_STATUS.md`.

### Scope

- Run the complete automated fake-provider browser journey.
- Run all negative claim/CSRF/concurrency/redaction tests.
- Perform backup/restore and restored-environment safety checks.
- Perform the manual designated real-Google smoke test when credentials/domain
  are available.
- Make only fixes required by the gate; do not add product features.

### Required behavior

- Every final acceptance item in `06_testing_and_acceptance.md` has evidence.
- `auth_audit_queries.sql` returns zero invariant failures after maintenance.
- Browser holds only the opaque HttpOnly local cookie; no provider token.
- Public rankings work while auth-disabled, anonymous, authenticated, and
  auth-unavailable.
- One Alembic head, full Python/frontend suites, build, Ruff, and migration
  checks pass.
- Production sign-in remains disabled if Google console/privacy/domain/manual
  prerequisites are incomplete.

### Acceptance

Record exact outputs for:

```text
alembic heads
alembic current
ruff check .
pytest
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e
```

Also record:

- disposable PostgreSQL migration/concurrency results;
- dependency-audit report and disposition;
- browser E2E report;
- audit SQL results;
- secret/log scan result;
- backup/restore check;
- manual Google smoke result or the explicit external prerequisite that keeps
  public sign-in disabled.

Only then mark authentication implemented. Do not mark a packet complete based
on code presence without its acceptance evidence.
