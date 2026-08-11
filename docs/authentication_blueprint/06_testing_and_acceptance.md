# Testing and Acceptance

## Test philosophy

Authentication tests must prove rejection behavior, not only successful login.
CI never depends on live Google, a real user account, or wall-clock sleeps.

Use three seams:

1. an injected clock and deterministic random/token source for pure tests;
2. a `GoogleOidcProvider` protocol with a strict fake for service/route tests;
3. a local/mock HTTP OIDC server with discovery, JWK, authorization, and token
   endpoints for protocol integration tests.

The production provider implementation still receives one manual end-to-end
Google smoke test before release.

Use a pinned current stable Playwright release for real-browser automation.
Vitest/jsdom remains the component-test layer but does not substitute for
cookie, redirect, CSP, browser-storage, BFCache, or cross-origin checks. The E2E
harness binds only loopback interfaces, uses the repository's guarded
disposable PostgreSQL mechanism, and injects a test-only provider adapter; no
production setting can select that adapter.

## Suggested test layout

```text
tests/auth/
  test_config.py
  test_crypto.py
  test_return_paths.py
  test_google_oidc.py
  test_login_service.py
  test_session_service.py
  test_csrf.py
  test_account_lifecycle.py
tests/api/
  test_auth_routes.py
  test_auth_middleware.py
tests/postgres/
  test_auth_schema.py
  test_auth_concurrency.py
  test_auth_migration.py
frontend/src/services/auth.test.ts
frontend/src/hooks/useAuthSession.test.tsx
frontend/src/components/AccountMenu.test.tsx
frontend/src/pages/AccountPage.test.tsx
frontend/playwright.config.ts
frontend/e2e/auth.spec.ts
```

Adjust API test paths to the framework the integration agent establishes; do
not duplicate its test application object/factory.

## Configuration tests

With `AUTH_ENABLED=true`, prove production startup rejects:

- missing or example Google client ID/secret;
- missing, malformed, padded, wrong-length, duplicate, whitespace-containing,
  or more than three auth root keys;
- HTTP, loopback/IP-literal, nondefault-port, or malformed public base URL;
- public URL with query, fragment, credentials, or path traversal;
- wildcard allowed origin;
- insecure or non-`__Host-` production cookie settings;
- idle lifetime greater than/equal to absolute lifetime;
- out-of-bounds attempt/session durations;
- untrusted proxy configuration;
- attempts to override Google discovery endpoint in production.

Prove absent/false `AUTH_ENABLED` starts the existing rankings application
without Google/auth secrets, makes the session endpoint return its exact
disabled 200 shape, callback return a clean local 303, and the remaining
auth/account routes return bounded 503. Prove these paths perform no
auth-table/provider lookup and never change ranking route behavior. Prove
true enables validation only when the auth schema and every required setting
are ready; malformed boolean values fail startup.

Prove development accepts only loopback HTTP and uses development cookie
names. Test and production settings must never share cookie names or Google
client values in fixtures. Treat actual domain ownership as a manual release
check, not something a URL parser can prove.

## Crypto tests

- State, nonce, binding, and session tokens have the specified random byte
  count and base64url encoding.
- Repeated generation produces no fixture collision.
- Session/state digests are exactly 32 bytes and deterministic for one input.
- PKCE S256 matches RFC 7636 known vectors.
- Plain PKCE is never emitted or accepted by the provider adapter.
- PKCE ciphertext decrypts only with the configured current/prior key and
  rejects modification/wrong purpose.
- AES-GCM envelope version, 12-byte nonce, attempt-ID AAD, and HKDF labels are
  exact; a wrong attempt ID cannot decrypt another attempt's verifier.
- Purpose-separated key derivation produces different OIDC/CSRF keys.
- CSRF tokens differ across sessions and validate with current/prior key only.
- Comparisons reject wrong length/encoding before constant-time comparison.
- No test helper accidentally becomes production deterministic randomness.

## Return-path tests

Accept only configured exact paths. An absent value defaults to `/`; an
explicitly supplied invalid value returns `INVALID_RETURN_PATH` and creates no
attempt. Test at least:

```text
https://attacker.example/
//attacker.example/
///attacker.example/
\\attacker.example
/%5c%5cattacker.example
/%2f%2fattacker.example
https:%2f%2fattacker.example
/account#fragment
/account?next=https://attacker.example
/%00account
/ACCOUNT                    # unless explicitly allowlisted with this case
/my-tickets/../admin
```

Test decoding/normalization exactly once. A double-encoded value must not
become dangerous after the framework or proxy decodes it again.

## Provider/OIDC tests

The authorization request test asserts exact values:

- `response_type=code`;
- scopes exactly `openid email`;
- configured client ID and callback;
- state and nonce present;
- PKCE challenge and `S256` present;
- no offline access, refresh request, profile, Gmail scope, `hd`, open return
  URL, or provider token in application state.

ID-token rejection matrix:

- unknown signing key or invalid signature;
- `alg=none` or algorithm/key confusion;
- missing/wrong issuer;
- missing/wrong/multiple unexpected audience;
- multi-audience tokens without matching required `azp`;
- wrong `azp` when present;
- missing/noninteger/ill-ordered `iat` or `exp`, and future `nbf`;
- wrong `at_hash` when present, missing/oversized access token, or non-Bearer
  token type;
- expired token;
- issue time too far in future;
- missing/wrong/replayed nonce;
- missing/blank/oversized/non-ASCII/whitespace-or-control subject;
- missing/blank/oversized email;
- false or nonboolean `email_verified`;
- oversized token or provider response.

Positive cases include canonical and Google-supported legacy issuer spellings,
then assert only the canonical issuer is persisted.

The provider adapter tests also prove:

- bounded network timeout;
- no redirect to an unexpected token/JWK host;
- rejection of a discovery document that changes any pinned Google endpoint
  path/host or advertised signing algorithm;
- enforcement of every provider timeout/body/token/query bound;
- TLS verification and `trust_env=False` cannot be disabled through settings;
- cached JWK refresh behavior;
- provider error bodies are mapped to allowlisted reason codes;
- access/refresh/raw ID tokens do not appear in returned domain values, logs,
  database calls, or exception strings;
- no database session/transaction is active during provider network calls;
- network assertions prove no UserInfo/token-info/other Google API request.

## Login-attempt service tests

- Start creates one pending ten-minute attempt and transient cookie.
- Start with an active local session redirects locally and creates no attempt;
  an invalid/expired cookie is cleared and does not block login.
- Second start for the browser marks the first `superseded`.
- An ordinary start racing after callback claim redirects locally with
  `in_progress`; reauth POST receives `AUTH_IN_PROGRESS`. Neither creates an
  attempt nor replaces/clears the claimed flow's binding.
- State mismatch, cookie mismatch, missing cookie, expired attempt, wrong
  provider, and nonpending status all fail.
- Duplicate/polluted callback security parameters and duplicate `returnTo`
  values fail before exchange/redirect construction.
- Google denial consumes the matching attempt and creates no user/session.
- Callback claim uses an atomic state transition; a second/racing callback
  cannot exchange.
- Exchange failure leaves a terminal failed attempt and requires restart.
- A crashed/stuck `exchanging` attempt becomes terminal after the documented
  30-second post-expiry grace and is eventually removed by retention; a live
  bounded exchange may finish just after the claim deadline.
- Successful callback marks one attempt succeeded, sets the new session cookie,
  and redirects to a clean local path.
- Callback completion leaves the short-lived transient cookie to expire; an
  older/superseded callback response cannot erase a newer attempt's cookie.
- Provider call occurs after the claim transaction is committed.
- Cookie/session issuance occurs only after final database commit.
- A response failure after commit cannot retrieve/reissue the raw token.

## Identity and account tests

- First login creates exactly one user, one identity, one session, one success
  event.
- Returning login updates display email and timestamps but preserves user and
  identity IDs.
- Two identities may share an email without linking or conflict.
- Email case/metadata changes do not create another identity.
- Another subject with the same email creates another user.
- Suspended user receives no session and all old sessions are revoked.
- Reactivation creates no session until a later successful Google login.
- Reauth-delete must match expected issuer/subject; same email with another
  subject fails.
- Reauth-delete fails if the initiating local session cookie is missing,
  replaced, revoked, expired, or belongs to another session/user.
- Reauth-delete includes `prompt=select_account`, requests no additional
  scope, and is never labeled as password/MFA verification.
- Reauth-delete initiation is POST-only, requires an active session and CSRF,
  and returns only a bounded pinned-host authorization URL.
- Account deletion requires recent authentication and exact confirmation.
- Guarded operator deletion requires two matching canonical user UUIDs,
  allowlisted reason, dry-run/apply, and the same complete cascade.
- Deletion cascades identity/session and nulls event foreign keys.
- A post-deletion login creates a new unrelated local user.

## Session tests

- Raw token is returned only to cookie construction; repository sees digest.
- Cookie token cannot be recovered from stored digest.
- Missing, malformed, oversized, unknown, revoked, idle-expired,
  absolute-expired, future-dated, or suspended-user session is rejected and
  cookie cleared.
- Exactly-at-deadline is expired; compare using server UTC.
- A normal request before touch threshold performs no session write.
- A touch after threshold advances idle expiry but never beyond absolute.
- Five sessions remain active; creating a sixth revokes the oldest under lock.
- Empty-set and simultaneous sixth/seventh tests prove the stable parent user
  row—not only existing session rows—is locked.
- Logout revokes only current; logout-all revokes every session.
- Logout-all and simultaneous session issuance serialize on the parent user
  lock with a deterministic outcome.
- Foreign session UUID revocation returns the same 404 as nonexistent.
- Session listing returns only the caller's active sessions, current first,
  with no retained revoked/expired rows or device fingerprint data.
- Authentication/privilege changes never reuse an old session token.
- Optional-principal requests remain anonymous after an invalid cookie;
  required-principal requests return standard 401; the existing rankings
  route performs no auth lookup at all.

## CSRF tests

For every unsafe authenticated route, reject:

- missing, malformed, wrong-session, prior-revoked-session, or modified token;
- cross-site Origin;
- deceptive suffix/prefix Origin (`example.com.attacker.test`);
- `Origin: null`;
- missing Origin plus missing/mismatched Referer;
- `Sec-Fetch-Site: cross-site`;
- simple body content types when JSON is required;
- malformed/non-object/duplicate-key/non-finite/BOM/oversized JSON and unknown
  request properties;
- duplicate CSRF/origin/referer/fetch-metadata/content-type headers;
- wildcard credentialed preflight/origin behavior.

Accept exact same origin with a current session-bound token. Verify safe public
GETs do not require CSRF and that the Google callback uses its distinct
state/PKCE protection.

Rate-limit tests use an injected monotonic clock and prove burst/refill,
`Retry-After`, trusted-proxy resolution, forwarding-header rejection, keyed
non-PII cache keys, concurrency, expiry, 20,000-key capacity behavior, bounded
event emission, and disabled-auth bypass without wall-clock sleeps.
The callback limit additionally proves a clean local no-store 303, no
auth-table/provider call, and no code/state in Location or access logs.

## Route-contract tests

- Session endpoint returns exact disabled/anonymous/authenticated discriminated
  shapes and never reports authenticated when availability is false.
- Auth database outage is 503, not anonymous.
- Redirect routes use 303 and clean local destinations.
- Recent-auth initialization rejects GET, requires POST+CSRF, and returns a
  one-property Google authorization URL pinned to HTTPS, accounts.google.com,
  and `/o/oauth2/v2/auth` with no credentials/fragment.
- Callback never renders code/state or returns them in Location.
- Public callback/start results are restricted to the five documented codes.
- Problem responses contain request ID and stable code but no PII/provider
  detail.
- Auth responses carry the same server-generated UUIDv4 in `X-Request-ID` and
  the problem/event correlation field; a client-supplied value is ignored.
- All auth responses are `no-store`; session response varies on Cookie.
- Production cookies assert Secure, HttpOnly, Lax, Path `/`, no Domain, correct
  `__Host-` name, and bounded Max-Age.
- Duplicate configured auth-cookie names are rejected, not silently collapsed
  by the framework parser.
- Logout cookie clearing uses exactly matching name/path/security scope;
  callbacks do not issue a transient-cookie deletion that can race a new tab.
- Logout with active session requires CSRF; absent/invalid session only clears
  cookies and makes no active-account change.
- Public rankings work with auth disabled/unavailable.

## PostgreSQL tests

### Schema constraints

Independently prove rejection of:

- invalid user/attempt/session states;
- active/suspended timestamp inconsistency;
- duplicate issuer/subject or duplicate user/provider;
- false email verification;
- wrong digest length;
- duplicate session digest;
- invalid time ordering;
- revoked timestamp/reason mismatch;
- reauth attempt without expected user/session, mismatched nullability, or
  login attempt with either one;
- every invalid attempt claimed/completed/failure-code shape;
- non-object/oversized auth-event details and unknown event types;
- unknown auth-event reason codes/keys and invalid allowlisted detail value
  types/ranges;
- broken foreign keys.

### Concurrency

Use separate database connections/transactions to prove:

- simultaneous first login for one issuer/subject yields one user/identity and
  no orphan user;
- simultaneous callback claims yield one exchanger;
- simultaneous sixth/seventh session creation never leaves more than five
  active sessions;
- a principal resolution started after committed suspension cannot authorize;
  race tests document that already-running requests are not retroactively
  cancelled;
- account deletion racing with a new session cannot leave an active session
  for a deleted user.

### Migration

- Fresh zero-to-head creates every auth table/constraint/index.
- Prior-head-to-auth-head upgrades a populated analytics database without
  changing any existing row count/value.
- Metadata columns match PostgreSQL columns after explicitly importing
  `auth_models`.
- Upgrade, downgrade on an empty auth schema, and re-upgrade succeed in a
  disposable database.
- `alembic heads` returns one head.

## Frontend tests

- Loading, disabled, anonymous, authenticated, and auth-unavailable states render
  distinctly without hiding rankings.
- Sign-in navigates to the backend start endpoint with an allowlisted return
  path; no Google SDK/token code exists in the bundle.
- `/` remains public; direct load/refresh of `/account` renders the account
  route, while an unknown `/api/*` path remains a JSON 404 rather than SPA HTML.
- Ranking metric bars no longer require inline styles; production CSP has no
  `unsafe-inline`, and browser tests report no CSP violations.
- Email text is escaped by React and safely handles long values.
- Logout sends same-origin credentials, JSON, and current CSRF header.
- CSRF token and auth response never enter local/session storage or URL state.
- Auth requests remain relative same-origin even when a ranking-only URL
  override is present in a test build.
- Malformed, oversized, contradictory, or slow session/problem responses enter
  unavailable state and never leave stale user/CSRF data rendered.
- Cross-tab BroadcastChannel messages contain only fixed event names; login,
  logout, reauth, revocation, deletion, BFCache restore, and bounded visibility
  revalidation clear/refetch correctly without storage or request storms.
- A 401 refreshes session once and does not automatically replay an unsafe
  request.
- Auth result message is bounded and the query parameter is removed.
- Account/session controls are keyboard and screen-reader accessible.
- Delete confirmation and recent-auth response are explicit.
- Delete confirmation is discarded across reauth; callback success never
  auto-deletes, and cancellation leaves the account/session unchanged.
- The frontend validates the returned reauth URL's scheme/host, navigates in
  the same window, and never puts it in application storage, telemetry, or
  logs.

## Browser end-to-end tests

Use Playwright and a local fake OIDC provider for automated browser tests. If
the frontend's reauthentication URL guard requires the pinned
`accounts.google.com` authorization URL, the test provider emits that exact
safe URL and Playwright intercepts the navigation to synthesize the local
callback; do not relax the production frontend allowlist to accept a loopback
provider. Assert that no request escapes the test harness.

The journey is:

1. anonymous page and public rankings load;
2. login redirect includes only approved scopes and PKCE;
3. fake provider callback creates local cookie session;
4. refresh remains authenticated;
5. browser storage contains no auth/provider token;
6. session cookie is not script-readable;
7. a forged cross-origin write fails;
8. logout revokes server session and refresh is anonymous;
9. replaying callback fails;
10. cross-site GET/POST cannot initialize delete reauthentication;
11. same-user reauthentication rotates the local session/CSRF token;
12. account deletion removes the account and session.

Run at desktop and mobile viewport widths. Capture console/page errors and fail
the test on unexpected network requests to Google or third-party origins.

## Logging/redaction tests

Use captured logs plus static scans with distinctive secret fixtures. Assert
none of these appear at any level, including exceptions:

- client secret/auth root;
- code/state/nonce/PKCE/binding/session tokens;
- raw ID/access/refresh token;
- email/subject/hosted-domain claim;
- Cookie/Set-Cookie header;
- callback query string.

Inspect `auth_events.details` keys and values against an allowlist. Redaction
must occur before external error-reporting transport, not only in the console
formatter.

## Manual Google smoke test

This test is required only for a release candidate and uses a designated test
account, never CI:

- actual consent shows only identity/email;
- callback matches exact configured URL;
- app displays verified email;
- browser network/storage inspection finds no provider token;
- session refresh/logout/revocation work;
- switching Google account does not merge by email;
- reauth-delete refuses a different Google account;
- account deletion succeeds;
- Google client secret is absent from build/source/logs.

Record date, environment, client ID suffix (not secret), tester, result, and
commit. Do not record account email or tokens.

## Required validation commands

Exact commands may inherit the API framework's additions, but the final run
must include:

```text
ruff check .
pytest
alembic heads
alembic current
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e
```

Run PostgreSQL tests in the repository's guarded disposable-database harness.
Run a Python dependency vulnerability audit and `npm audit` in report mode;
triage findings rather than applying unreviewed major upgrades.

## Final acceptance gates

The implementation may be marked code-complete only when:

- every work packet's tests pass;
- fresh and populated migrations pass with one head;
- all negative OIDC/session/CSRF/concurrency cases above pass;
- frontend and public ranking behavior pass with auth disabled, anonymous,
  authenticated, and unavailable;
- browser cookie/storage/header assertions pass;
- audit SQL reports zero invariant failures after maintenance;
- logs and database contain no forbidden token/secret material;
- account suspension, session revocation, and deletion are operational;
- production configuration fails closed when any security input is unsafe;
- the manual Google release smoke test is recorded as passed, or its unavailable
  Google/domain prerequisite is explicitly recorded while `AUTH_ENABLED`
  remains `false`;
- implementation status records the commands and exact results.

Public authentication may be enabled only after the manual Google smoke test
passes and every production release prerequisite in the operations document is
recorded. Missing external credentials, domain, policy pages, or proxy setup do
not block completing and accepting the implementation; they keep the secure
rollout flag disabled.
