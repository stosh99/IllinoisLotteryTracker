# API and Frontend Contract

## General HTTP rules

- Authentication endpoints live under the existing versioned API at
  `/api/v1/auth`.
- Account deletion lives at `/api/v1/account` because it acts on the local
  account, not the Google provider.
- All authentication responses use `Cache-Control: no-store`.
- JSON responses use UTF-8 `application/json`.
- Timestamps are UTC RFC 3339 strings with `Z`; UUIDs use canonical lowercase
  text. Request models reject unknown properties.
- State-changing JSON routes reject unsupported/simple body content types.
- Authentication JSON request bodies are limited to 1 KiB before parsing;
  require one JSON object with UTF-8, no BOM/duplicate keys/non-finite values,
  and reject malformed JSON or unknown fields through the bounded problem
  contract.
- Server-issued OAuth redirect responses use `303 See Other`. The
  CSRF-protected recent-auth initializer returns a bounded authorization URL
  in JSON so frontend code can perform a top-level navigation without asking
  fetch to follow a cross-origin redirect.
- No endpoint accepts an application session through `Authorization`, a query
  parameter, or a JSON body.
- The OpenAPI description documents cookie authentication and CSRF header
  requirements, but never displays a real token example.

## Session response

### `GET /api/v1/auth/session`

This endpoint intentionally returns `200` for disabled, anonymous, and
authenticated auth states so the public application can initialize without
using exceptions as normal control flow.

Disabled by operator configuration:

```json
{
  "authenticationAvailable": false,
  "authenticated": false,
  "user": null,
  "session": null,
  "csrfToken": null
}
```

Anonymous:

```json
{
  "authenticationAvailable": true,
  "authenticated": false,
  "user": null,
  "session": null,
  "csrfToken": null
}
```

Authenticated:

```json
{
  "authenticationAvailable": true,
  "authenticated": true,
  "user": {
    "id": "08ec5c00-cdf8-487a-8db4-31f19be30f59",
    "email": "player@example.com",
    "emailVerified": true
  },
  "session": {
    "authenticatedAt": "2026-08-10T18:30:00Z",
    "idleExpiresAt": "2026-08-11T18:30:00Z",
    "absoluteExpiresAt": "2026-08-17T18:30:00Z"
  },
  "csrfToken": "<session-bound opaque value>"
}
```

Do not return Google subject, session UUID, token digest,
provider token, account status, internal reason, or role. The service may add a
display name later only after a deliberate `profile`-scope decision.

`session.authenticatedAt` is the session row's `created_at`; version 1 issues a
new session for every completed login/reauthentication and never carries an old
authentication time into a new row.

Required headers:

```text
Cache-Control: no-store
Pragma: no-cache
Vary: Cookie
```

An invalid or expired cookie is cleared. An unavailable authentication
database is a `503`, not an anonymous response, so the frontend can distinguish
"signed out" from "cannot determine session safely."

When `AUTH_ENABLED=false`, the session endpoint returns the disabled `200`
shape without reading a cookie or touching auth state; the callback always
returns a clean no-store local `303 failed` without lookup, and every other
auth/account endpoint returns `503 AUTH_UNAVAILABLE`. The frontend hides the
sign-in control rather than presenting an outage. No endpoint or frontend
control can enable authentication at runtime.

## Login endpoints

### `GET /api/v1/auth/google/start`

Query:

| Name | Required | Rule |
|---|---:|---|
| `returnTo` | no | exact internal allowlist; defaults to `/` |

Duplicate `returnTo` keys are invalid. Callback security parameters likewise
reject duplicates; they are never silently collapsed by FastAPI/query helpers.

Response: `303` to Google and transient browser-binding cookie.

If an active local session is already present, respond `303` to the validated
local return path without contacting Google or creating an attempt. Version 1
does not expose account switching; the user signs out first. A stale cookie is
cleared before normal login proceeds.

Stable failures:

- `400 INVALID_RETURN_PATH` only when an API client explicitly requests an
  invalid path; normal UI should never do so;
- clean local `303` with `authResult=in_progress` when the browser's prior
  attempt is already in token exchange;
- `429 AUTH_RATE_LIMITED`;
- `503 AUTH_UNAVAILABLE` for invalid server configuration, provider discovery
  failure with no valid cache, or database failure.

The public error body does not contain a generated Google URL or configuration
detail.

### `GET /api/v1/auth/google/callback`

This endpoint is invoked by Google, not frontend fetch code. It accepts the
standard bounded query parameters needed for code or denial processing and
ignores unknown OAuth response parameters as required by the protocol.

Success:

```text
303 Location: <validated return path>
Set-Cookie: __Host-ilt_session=...
```

Failure:

```text
ordinary login: 303 Location: /?authResult=<stable-code>
delete reauth:  303 Location: /account?authResult=<stable-code>
```

Allowed public result codes are deliberately generic:

```text
cancelled
expired
failed
account_unavailable
in_progress
```

Never include the provider error description, email, subject, state, code, or
attempt ID in the redirect. The frontend displays one bounded message and
immediately removes `authResult` with `history.replaceState` so it is not
preserved in copied URLs.

Exact version-1 message map (unknown values display nothing and are removed):

| Result | Message |
|---|---|
| `cancelled` | Sign-in was cancelled. |
| `expired` | That sign-in attempt expired. Please try again. |
| `failed` | We could not complete sign-in. Please try again. |
| `account_unavailable` | This account cannot sign in. |
| `in_progress` | Sign-in is already finishing in another tab. |

Callback responses intentionally do not expire the transient login cookie;
see the multi-tab race rationale in the flow document. Its maximum age is ten
minutes, and logout may clear it early.

## Session management endpoints

### `POST /api/v1/auth/logout`

Requires an active session and `X-CSRF-Token`. Send an empty JSON object.

```text
204 No Content
```

If there is no cookie or the cookie cannot identify an active session, the
route clears authentication cookies and returns `204` without changing an
active account. If an active session is found, a missing/invalid CSRF token is
`403 CSRF_INVALID` and the session is not revoked.

### `GET /api/v1/auth/sessions`

Requires authentication. Returns only sessions belonging to the principal:

```json
{
  "sessions": [
    {
      "id": "988977c9-3aa0-4de8-933a-d4454d707413",
      "current": true,
      "createdAt": "2026-08-10T18:30:00Z",
      "lastSeenAt": "2026-08-10T19:05:00Z",
      "idleExpiresAt": "2026-08-11T19:05:00Z",
      "absoluteExpiresAt": "2026-08-17T18:30:00Z"
    }
  ]
}
```

No raw IP address, user agent, token, digest, or Google identifier is returned.
Return only currently active rows (`revoked_at IS NULL` and both deadlines in
the future), with the current session first and the remainder ordered by
`created_at DESC, id`. Retained revoked/expired history is operational data and
is not exposed through this endpoint.

The sessions UI labels the current row and shows created/last-active/deadline
times in the user's locale with machine-readable timestamps. Because the
privacy design intentionally stores no device/IP fingerprint, other rows have
no invented device/location label; when uncertain, the user can choose
`Sign out all sessions`.

### `DELETE /api/v1/auth/sessions/{sessionId}`

Requires authentication and CSRF. The lookup includes
`user_id = principal.user_id`. A nonexistent or foreign UUID returns the same
`404 SESSION_NOT_FOUND`. A malformed/noncanonical UUID returns that same 404,
not FastAPI's default validation body. Revoking the current session also clears
its cookie. The request has no body.

### `POST /api/v1/auth/logout-all`

Requires authentication and CSRF. Revokes all sessions including the current
session, clears its cookie, and returns `204`. Send an empty JSON object.

## Account endpoints

### `GET /api/v1/account`

Requires authentication. Exact version-1 response:

```json
{
  "id": "08ec5c00-cdf8-487a-8db4-31f19be30f59",
  "email": "player@example.com",
  "emailVerified": true,
  "createdAt": "2026-08-10T18:30:00Z"
}
```

It does not return Google subject, account status, session
credential, or internal audit data.

### `POST /api/v1/auth/google/reauth-delete`

Requires an active session, valid CSRF header, and an empty JSON object. Creates
a browser-bound attempt with intent `reauth_delete`, stores the principal user
as `expected_user_id` and the initiating session as `expected_session_id`, and
builds a Google URL with
`prompt=select_account`. The return path is fixed to the account-deletion
confirmation view; the browser cannot supply it.

Build/validate the provider URL outside a database transaction. The insert
transaction then locks the expected parent user/session, revalidates that the
session is active, supersedes any pending browser-bound attempt, and inserts
the attempt plus `reauth_started` event atomically. An exchanging attempt still
inside its 30-second post-expiry grace is never superseded and returns
`409 AUTH_IN_PROGRESS`. A logout/revocation during URL construction therefore
prevents attempt creation.

Response:

```json
{
  "authorizationUrl": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

The response is `200`, `Cache-Control: no-store`, has a fixed one-property
shape with a maximum 4,096-character URL, sets the transient browser-binding
cookie, and is never cached. The frontend immediately calls
`window.location.assign(authorizationUrl)` after verifying HTTPS and exact
host `accounts.google.com`, path `/o/oauth2/v2/auth`, and no credentials or
fragment; application code does not modify it or put it in storage, telemetry,
or logs. The standards-based provider navigation itself may appear in normal
browser history and contains only bounded short-lived OIDC request values, not
an application session or provider token.
Returning a URL here is intentional: a fetch-followed cross-origin 303 is not a
portable browser navigation mechanism, while a plain form cannot provide the
required custom CSRF header. `GET` is not supported for this operation.

On callback, the verified issuer/subject must match the expected user's
identity, and the same active initiating local session must still be present.
Success revokes/replaces that application session; failure creates no identity
and links no account.

This confirms recent control of the selected Google session; it must not be
described as a fresh password/MFA challenge.

### `DELETE /api/v1/account`

Requires authentication, CSRF, and recent authentication. Body:

```json
{
  "confirmation": "DELETE MY ACCOUNT"
}
```

Responses:

- `204` after committed deletion and cookie clearing;
- `400 CONFIRMATION_REQUIRED` for a mismatch;
- `403 RECENT_AUTH_REQUIRED` when `authenticatedAt` is older than the
  configured recent-login window (ten minutes initially);
- `401 AUTH_REQUIRED` when no current session exists.

The deletion transaction owns the future cascade into personal play data.
Authentication implementation must not invent or partially delete those
future tables.

The request body is limited to 1 KiB before JSON parsing and rejects unknown
properties. A successful recent-auth callback rotates the session and CSRF
token but does not itself delete the account; the person must still submit the
explicit delete request.

## Problem response

Non-redirect API failures use one consistent problem envelope, aligned with
the API framework selected by the data-integration work:

```json
{
  "type": "about:blank",
  "title": "Authentication required",
  "status": 401,
  "code": "AUTH_REQUIRED",
  "requestId": "f6fab598-51c0-422e-8e4b-bad21851d45a"
}
```

Use `application/problem+json`; never place these auth errors inside FastAPI's
default `{"detail": ...}` wrapper. AU-01 records whether a shared project
problem model already exists before adding the narrow auth exception handler.
The exact keys are `type`, allowlisted `title`, numeric `status`, `code`, and
server `requestId`; no free-form `detail`, provider field, validation echo, or
stack extension is returned.

Authentication codes:

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `INVALID_REQUEST` | malformed JSON/query shape or unknown field |
| 400 | `INVALID_RETURN_PATH` | login destination rejected |
| 400 | `CONFIRMATION_REQUIRED` | deletion confirmation mismatch |
| 401 | `AUTH_REQUIRED` | missing, expired, revoked, or invalid session |
| 403 | `CSRF_INVALID` | unsafe request failed CSRF/origin checks |
| 403 | `RECENT_AUTH_REQUIRED` | destructive action needs fresh Google auth |
| 404 | `SESSION_NOT_FOUND` | session absent or not owned by caller |
| 409 | `AUTH_IN_PROGRESS` | reauth POST found a claimed OAuth attempt |
| 413 | `REQUEST_TOO_LARGE` | authentication request exceeds its bound |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | required JSON content type absent/wrong |
| 429 | `AUTH_RATE_LIMITED` | bounded authentication rate exceeded |
| 503 | `AUTH_UNAVAILABLE` | auth disabled for this route or state cannot be determined safely |

Responses do not reveal whether an email, subject, or user exists.

## Frontend state model

Authentication state is independent of ranking-data state:

```text
unknown -> anonymous
unknown -> authenticated
unknown -> disabled
unknown -> unavailable
authenticated -> anonymous       (logout/expiry)
anonymous -> browser redirect     (Google sign-in)
```

`disabled` is the deliberate server configuration and is not an error.
`unavailable` means the enabled frontend could not safely determine the
session. It must not display another user's cached data or assume anonymous for
a protected write, but public rankings continue to work.

The auth service should expose:

```ts
type AuthState =
  | { status: "loading" }
  | { status: "disabled" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: AuthUser; session: AuthSession; csrfToken: string }
  | { status: "unavailable"; message: string };
```

Rules:

- one `AuthSessionProvider` above the route tree owns this state; components do
  not independently fetch or cache session data;
- fetch session during application initialization and on the bounded
  invalidation/revalidation triggers below;
- treat network JSON as `unknown` and runtime-validate the exact discriminants,
  UUIDs, bounded email, timestamps/deadline ordering, nullability, and CSRF
  syntax before it reaches React; reject contradictory/extra-sensitive fields;
- bound auth/problem response reads to 16 KiB and session initialization to a
  ten-second client timeout with abort cleanup;
- keep the CSRF token in React memory only;
- refetch once after `401` or `CSRF_INVALID` before showing a durable error;
- clear user/CSRF state immediately after logout begins and reconcile on
  response;
- never persist the auth response in local/session storage, IndexedDB, a
  service-worker cache, or URL state;
- never include session/CSRF data in analytics or error-reporting payloads;
- never block public rankings because auth initialization failed.

For same-origin tab coordination, use `BroadcastChannel("ilt-auth-v1")` with
only `{ type: "session-changed" }` or `{ type: "session-invalidated" }`—no
user/session/CSRF/provider value. Login/reauth return, logout, logout-all,
current-session revocation, and deletion broadcast the appropriate signal;
other tabs clear sensitive state immediately and refetch once. Also refetch on
`pageshow` when restored from back/forward cache and when the application
becomes visible after more than five minutes. If BroadcastChannel is
unsupported, these lifecycle refetches remain the fallback. Do not use a
storage event/localStorage for coordination.

An initial authenticated page load may broadcast `session-changed` once so a
Google callback return updates existing tabs. A refetch caused by a channel or
lifecycle signal never rebroadcasts. Coalesce signals while one session request
is in flight (and for a short 250 ms burst window) to prevent tab feedback
loops/request storms.

Frontend routing is deliberately small: `/` renders the existing ranking
experience and `/account` renders account/session/deletion controls. Reuse an
intervening established router; otherwise add a pinned current stable
`react-router-dom`. An anonymous `/account` view offers sign-in with
`returnTo=/account`; a disabled view explains that accounts are not enabled,
and an auth-unavailable view shows retry; none exposes cached account data. The
production static server returns the SPA entry point for these frontend paths
while preserving real JSON status codes under `/api/*`.

## Sign-in and account UI

The site header should show one of:

- no account control while authentication is deliberately disabled;
- `Sign in with Google` for anonymous users;
- a bounded loading placeholder while unknown;
- the verified email plus account menu for authenticated users;
- `Sign-in unavailable` with a retry action when auth alone is unavailable.

The button is a normal same-window navigation to the backend start endpoint,
not a provider SDK popup and not a fetch that handles Google tokens. Follow
Google's current sign-in branding requirements without using "Gmail" branding
or implying access to the inbox.

The account menu includes:

- signed-in email;
- future `My tickets` link only when implemented;
- `Sessions`;
- `Sign out` implemented as a CSRF-protected POST;
- `Delete account` behind an explicit confirmation and recent-auth flow.

The `/account` page displays verified email, creation time, and the nonsecret
local account UUID with an accessible copy action so the user can identify the
account in a support request. It does not display Google subject, audit events,
or inferred profile/device data.

Deletion UI explains that the local account, sessions, and future user-entered
records are removed; the Google Account is not. It requires typing the exact
phrase and a separate destructive button. On `RECENT_AUTH_REQUIRED`, discard
the typed phrase and show a deliberate `Continue with Google` action that calls
the reauth POST. After return, require the phrase and delete action again—never
auto-delete merely because reauthentication succeeded. Cancellation leaves the
account/session unchanged.

All controls require keyboard access, visible focus, accessible names, and
screen-reader status announcements. Error text is specific enough to recover
but does not expose provider internals.

## Protected frontend requests

A single fetch wrapper handles future authenticated writes:

- relative same-origin URLs only;
- authentication/account endpoints are literal relative `/api/v1/...` paths
  and never use `VITE_RANKINGS_URL` or another runtime/build URL override;
- `credentials: "same-origin"`;
- JSON content type;
- current in-memory `X-CSRF-Token` on unsafe methods;
- no `Authorization` header;
- bounded problem-response parsing;
- one session refresh on `401`, never an automatic replay of a non-idempotent
  write unless the caller supplies an idempotency key and opts in.

Authentication writes and future ticket writes are not service-worker cached.

## CORS and proxy contract

Production should need no credentialed CORS because frontend and API share an
origin. Version 1 does not support a separate browser API origin and emits no
credentialed CORS headers. Splitting origins is an architecture/security
change requiring a revised cookie, CORS, CSRF, and browser-test design; it is
not enabled through an environment variable.

Development uses the Vite `/api` proxy and registers this callback (or the
actual chosen dev port) with Google:

```text
http://localhost:5173/api/v1/auth/google/callback
```

Production uses exactly:

```text
https://<owned-domain>/api/v1/auth/google/callback
```

No wildcard redirect URI and no request-supplied callback are permitted.
