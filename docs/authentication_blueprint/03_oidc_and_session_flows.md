# OIDC and Session Flows

## Cryptographic primitives

All randomness comes from the operating system CSPRNG (`secrets` in Python).
Base64url values omit `=` padding.

| Value | Random input | Persisted form | Lifetime |
|---|---:|---|---:|
| OIDC state | 32 bytes | SHA-256 digest | 10 minutes, one use |
| OIDC nonce | 32 bytes | SHA-256 digest | 10 minutes, one use |
| Browser binding | 32 bytes | SHA-256 digest | 10 minutes, one active flow |
| PKCE verifier | 64 bytes/base64url | authenticated ciphertext | 10 minutes, one use |
| Application session token | 32 bytes | SHA-256 digest | up to 7 days |

PKCE uses:

```text
code_challenge = base64url(SHA-256(ASCII(code_verifier)))
code_challenge_method = S256
```

Digest comparisons use `hmac.compare_digest` or an equivalent constant-time
primitive after fixed-length validation.

The encodings are exact: a 32-byte state, nonce, binding, or session token is
43 unpadded base64url characters; the 64-byte PKCE verifier is 86. Reject
padding, non-base64url characters, or any other decoded length for locally
generated values. Provider authorization codes are opaque: accept 1–4096
non-control characters without interpreting their format.

For every locally generated opaque token, the stored digest is exactly
`SHA-256(strict_base64url_decode(encoded_value))`, not a digest of the encoded
ASCII text. Strict decoding and decoded-length validation happen before the
digest. PKCE is the exception: its challenge follows the standard formula above
and hashes the ASCII verifier string.

### Root authentication secrets

Configure `AUTH_SECRET_KEYS` as a comma-separated, newest-first list of one to
three independently generated 32-byte values, each encoded as exactly 43
unpadded base64url characters. Reject whitespace, empty/duplicate entries,
padding, other alphabets, and any decoded length other than 32. A maintained
cryptography library derives separate, domain-labelled keys for:

- OIDC-attempt encryption;
- CSRF HMAC;
- ephemeral rate-limit source pseudonyms.

Never reuse the Google client secret for local cryptography. The newest root
key encrypts/signs new values; prior configured keys may decrypt/verify during
a documented rotation window. A production process refuses to start with a
missing, malformed, short, or example authentication secret.

Use HKDF-SHA256 with a 32-byte output, `salt=None`, no
dynamic/user-controlled `info`, and these exact labels:

```text
illinois-lottery-tracker/auth/oidc-attempt/v1
illinois-lottery-tracker/auth/csrf/v1
illinois-lottery-tracker/auth/telemetry/v1   # ephemeral rate-limit keys only
```

Encrypt the PKCE verifier with `cryptography`'s AES-256-GCM using the derived
OIDC-attempt key, a fresh 12-byte random nonce, and AAD
`b"ilt-oidc-attempt-v1\x00" + attempt_id.bytes`. Persist a versioned envelope
`v1.<base64url(nonce || ciphertext || tag)>`. Decryption tries configured root
keys newest-first and rejects an unknown version, modified value, wrong AAD,
or all-key failure. Never reuse a nonce with a key. This fixes the storage
format while delegating the cryptographic primitive to a maintained library.
For the exact 86-byte verifier this envelope is 155 characters; reject any
other decoded component length before decryption.

## Cookie contract

### Production

| Purpose | Name | Required attributes |
|---|---|---|
| OIDC browser binding | `__Host-ilt_login` | `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600` initially |
| Application session | `__Host-ilt_session` | `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800` initially |

Neither cookie has a `Domain` attribute. No authentication cookie is readable
by JavaScript. Cookie values are meaningless random strings.

Reject a request containing more than one cookie with the configured login or
session name; do not rely on a framework cookie dictionary that silently picks
the first/last duplicate. Other duplicate/unrelated cookies do not become auth
credentials. Set and clear only the configured environment's names.

`Max-Age` is generated from the validated attempt/absolute-session
configuration; the values above are the required initial policy. It never
exceeds the corresponding server-side deadline.

`SameSite=Lax` is intentional for the transient login cookie: Google's
cross-site top-level callback must carry the browser binding. The application
session is also Lax for predictable consumer navigation and is independently
protected by CSRF validation on unsafe methods.

### Local development

Plain HTTP is allowed only when all of these are true:

- `APP_ENV=development` or `test`;
- configured public host is exactly `localhost` or a loopback address;
- cookie names are `ilt_login_dev` and `ilt_session_dev` without the
  `__Host-` prefix;
- `Secure` is disabled explicitly by the validated development configuration.

Production configuration must reject `http`, insecure cookies, wildcard
origins, or a non-`__Host-` cookie name. Do not add a configurable cookie
domain.

## Safe return paths

The browser may request an internal post-login destination, but it never
controls a redirect origin. Version 1 permits only exact allowlisted paths:

```text
/
/account
```

`/my-tickets` is added to the allowlist only in the later personal-tracking
feature packet that creates and protects the actual route.

Validation occurs before the attempt is stored. Reject values with a scheme,
authority/netloc, encoded or literal backslash, control character, fragment,
double leading slash, or non-allowlisted normalized path. Do not fall back to
echoing an invalid value. An absent value defaults to `/`; an explicitly
supplied invalid value produces `400 INVALID_RETURN_PATH` and creates no
attempt. Internal service helpers may return `/` only when called with no
requested value, never as silent recovery from attacker input.

The validated path is stored in `oidc_login_attempts`. Do not serialize it
inside `state`, trust a callback query copy, or expose an open redirect helper.

## Flow A: start ordinary Google login

Endpoint:

```text
GET /api/v1/auth/google/start?returnTo=/account
```

Steps:

1. Validate production configuration and the return path.
2. If the request already has an active local session, return a clean `303` to
   the validated local return path and create no attempt. A stale/invalid
   cookie is cleared and login may continue.
3. Apply edge/application rate limiting.
4. Generate state, nonce, PKCE verifier, browser binding, and attempt UUID.
5. Build and validate the Google authorization URL outside a database
   transaction. Discovery may use its bounded validated cache/transport.
6. If a valid browser-binding cookie identifies a pending attempt, mark it
   `superseded` in the same transaction. If it identifies an `exchanging`
   attempt still inside its 30-second post-expiry grace, do not overwrite the
   cookie/create an attempt and redirect to the clean local return path with
   the fixed `in_progress` result. After that grace, atomically fail it with
   `exchange_abandoned`; terminal rows do not block a new flow.
7. Insert a `pending` attempt containing digests, encrypted verifier,
   validated return path, intent `login`, and ten-minute expiry; commit.
8. Set the transient binding cookie.
9. Respond `303 See Other` to Google with `Cache-Control: no-store` and
   `Referrer-Policy: no-referrer`.

Do not derive the callback URI from `Host` or untrusted forwarding headers.
Use `PUBLIC_BASE_URL + /api/v1/auth/google/callback` from validated settings.

The start route is the only ordinary GET endpoint that creates transient
state. It never creates a user or authenticated session.

## Flow B: process the Google callback

Endpoint:

```text
GET /api/v1/auth/google/callback?code=...&state=...&iss=...
```

The callback never renders an HTML page containing provider parameters and
always redirects to a clean local URL. It does not blindly clear the transient
cookie: a concurrent newer start may already have overwritten that cookie, and
an older callback response must not erase the new binding. The HttpOnly random
cookie expires naturally after at most ten minutes or is overwritten on the
next start; one-time database state, not cookie deletion, prevents replay.

### B1. Claim the attempt

1. Require syntactically bounded `state` and the transient binding cookie.
   Reject duplicate `state`, `code`, `error`, or `iss` query keys rather than
   relying on framework first/last-value behavior.
2. Hash both and query the attempt by state digest with `SELECT ... FOR
   UPDATE`.
3. Require provider `google`, status `pending`, and a matching browser-binding
   digest.
4. If `now >= expires_at`, atomically mark the attempt `expired` and stop.
5. For `reauth_delete`, also require the current application cookie to resolve
   to the active `expected_session_id` owned by `expected_user_id`.
6. If Google supplied `iss`, require Google's canonical/accepted issuer.
7. For exact `error=access_denied`, atomically set `denied` with
   `user_denied`, append a generic event, commit, and redirect to a clean
   cancellation result. Consume any other bounded provider `error` as `failed`
   with an allowlisted local reason and the public `failed` result.
8. For a code callback, atomically transition `pending -> exchanging`, set
   `claimed_at`, decrypt the PKCE verifier, and commit.

An invalid supplied `iss`, a response containing both `code` and `error`,
neither one, or another invalid bounded shape never reaches token exchange; if
state and browser binding validly identify the attempt, consume it as `failed`
with `invalid_callback`. A denial sets both `claimed_at` and `completed_at`.
Verifier decryption failure similarly consumes the attempt as `failed` with
`attempt_decryption_failed` and is an operational alert.
Provider `error_description`, `error_uri`, and unknown parameters are ignored
and never logged.

Only exact provider `error=access_denied` maps to public `cancelled`; all other
provider errors map to public `failed` and an allowlisted internal reason. An
expired attempt maps to `expired`, a suspended user to
`account_unavailable`, and every other validation/identity/internal failure to
`failed`. Mapping depends on trusted local state, never provider description
text.

Only the transaction that changed the state to `exchanging` may proceed. A
replay or racing callback fails with a generic expired/invalid-login result.

### B2. Exchange outside a transaction

1. POST the one-time code, exact callback URI, client ID, client secret,
   authorization-code grant, and PKCE verifier to Google's discovered token
   endpoint over TLS.
2. Use bounded connect/read/total timeouts and no automatic redirect to an
   unvalidated host.
3. Bound the response size before JSON parsing.
4. Require bounded nonempty `access_token`, case-insensitive Bearer
   `token_type`, and ID token; treat the entire response as ephemeral. A refresh
   token is never required or retained.
5. Validate the ID token with the maintained OIDC library and cached Google
   JWK material.

No SQLAlchemy transaction or checked-out database connection remains open
during this network operation.

Discovery must report canonical Google issuer and HTTPS endpoints that match
the code allowlist:

```text
https://accounts.google.com/o/oauth2/v2/auth
https://oauth2.googleapis.com/token
https://www.googleapis.com/oauth2/v3/certs
```

An endpoint host/path change fails closed until reviewed in code; it is not
accepted from configuration. Do not follow HTTP redirects for token,
discovery, or JWK requests. Version-1 ID-token verification allows only
`RS256`, intersected with the discovery metadata; symmetric algorithms and
`none` are forbidden. TLS certificate verification is mandatory and cannot be
disabled by configuration. The provider HTTP client uses `trust_env=False` so
unreviewed process proxy variables cannot receive the client secret; an
enterprise egress proxy would require a separate explicit deployment design.

### B3. Validate identity claims

Require all of the following:

- valid signature from the discovered Google JWK set;
- issuer is `https://accounts.google.com` or Google's supported legacy issuer,
  then canonicalize it;
- `aud` is either the configured web client ID string or an array containing
  it; when the array has more than one member, `azp` is required and equals
  that client ID; whenever `azp` is present it must equal that client ID;
- integer `iat` and `exp` are present, `exp` is after `iat`, the token is
  unexpired, and it was not issued implausibly in the future, allowing at
  most a small configured clock skew (maximum 60 seconds);
- if `nbf` is present, it is an integer and has passed within the same skew;
- if `at_hash` is present, the OIDC library validates it against the ephemeral
  access token and the permitted signing algorithm;
- nonce claim is an exact 43-character unpadded base64url value whose decoded
  length is 32 bytes and whose digest matches the attempt;
- nonce is accepted only once through the attempt transition;
- subject is a 1–255 byte case-sensitive string containing only printable
  non-whitespace ASCII `0x21`–`0x7e`;
- email is present and satisfies the exact trim/control/NFC/length rules in
  the architecture document;
- `email_verified` is boolean true;
- optional `hd` and other unneeded claims are ignored and not copied into the
  verified domain value.

Do not call Google's token-info endpoint in production. Do not accept a plain
subject or decoded JWT payload from the browser. Do not use email domain to
authorize access.

After claim validation, discard the authorization code, raw ID token, access
token, refresh token if unexpectedly present, and raw token response. None may
enter logs or persistence.

### B4. Finalize local login

In a new transaction:

1. Lock/read the attempt and require status `exchanging`.
2. Look up identity by canonical `(issuer, subject)`.
3. For ordinary `login`, create one user plus identity atomically when absent.
   On unique conflict, roll the entire transaction back and retry as a
   returning login.
4. For `reauth_delete`, never create or link a user/identity. Require the found
   identity's user to equal `expected_user_id`; require the callback's current
   application cookie still to resolve to the active `expected_session_id`;
   and require that session to belong to the expected user. On any mismatch,
   fail the attempt with `identity_mismatch` and leave the old session/account
   unchanged.
5. Lock the parent user row. Update verified identity email metadata and
   timestamps only after the identity branch above succeeds.
6. If the user is suspended, set attempt `failed` with an allowlisted reason,
   append a generic event, commit, and issue no session.
7. For successful `reauth_delete`, revoke `expected_session_id` with
   `replaced`. Then lock/count remaining active sessions and revoke the
   deterministic oldest if the new session would exceed five.
8. Generate a new session token and insert only its digest with the configured
   idle/absolute deadlines.
9. Update `app_users.last_login_at`.
10. Mark the attempt `succeeded` and append the intent-appropriate success
    event.
11. Commit before setting browser cookies.

After commit, set the session cookie and return a `303` to the attempt's
validated return path. The callback URL—and therefore
the code/state—must not remain in browser history or be visible to frontend
scripts.

If token exchange, claim validation, or finalization fails, mark the claimed
attempt `failed` in a short independent transaction when possible, discard all
transient in-process provider values, and redirect with a generic stable error
code. A transient provider failure requires starting a new login; an
`exchanging` attempt is never reused.

## Flow C: authenticate an application request

For routes that deliberately allow or require a principal:

1. Read only the configured session cookie. Reject session IDs supplied in a
   header, URL, body, or alternate cookie.
2. Apply a strict maximum encoded-token length and base64url syntax before
   hashing.
3. Hash the raw token and query session, user, and current Google identity.
4. Require a matching digest, no revocation, active user, and both idle and
   absolute deadlines in the future; reject a future-dated local session.
5. For an expired session, mark it revoked with the correct expiry reason in a
   bounded transaction and clear the cookie.
6. At most once per five minutes, touch last-seen/idle expiry without extending
   the absolute deadline.
7. Construct a server-side principal containing local user UUID, verified
   display email, and session UUID.

An optional-principal route treats missing/invalid/expired cookies as
anonymous and clears a stale cookie. A required-principal route returns the
standard `401 AUTH_REQUIRED` problem. It never trusts a cached React user.

Do not apply principal resolution as global middleware to the existing public
rankings endpoint. That route remains independent of auth availability and
does not query auth tables; the frontend's separate session request controls
account chrome.

Revocation/suspension prevents any request whose principal resolution begins
after the revocation transaction commits. It cannot retroactively cancel a
request already executing application code. Future user-owned write services
must resolve/recheck the active principal in the same request transaction as
the owner-scoped write rather than trusting old React state or a principal
cached across requests.

Do not hard-bind sessions to IP address or user agent. Mobile networks,
privacy relays, and browser updates make those unstable. They may inform
rate limiting only through the keyed, in-memory pseudonymization and bounded
retention specified in the operations document; they never become session
identity or persistent auth data.

## Flow D: CSRF validation

The session endpoint returns a CSRF token derived on the server:

```text
csrf = base64url(HMAC-SHA256(
  derived_csrf_key,
  b"ilt-csrf-v1\x00" || session.id.bytes || session.token_digest
))
```

The token is returned only over an authenticated, `Cache-Control: no-store`
response and held in React memory. It is never put in a URL, persistent browser
storage, or cookie.

For every authenticated `POST`, `PUT`, `PATCH`, and `DELETE`:

1. Reject duplicate `X-CSRF-Token`, `Origin`, `Referer`, `Sec-Fetch-Site`, or
   `Content-Type` headers rather than accepting a framework-combined value.
2. Require parsed media type `application/json` when a body is present; allow
   only an optional `charset=utf-8` parameter (case-insensitive).
3. Require `X-CSRF-Token` with bounded syntax.
4. Recompute and constant-time compare the session-bound token.
5. Require `Origin` to exactly match configured public origin; if legitimately
   absent, require an exact same-origin `Referer`; reject `null` or missing both.
6. Reject `Sec-Fetch-Site: cross-site`; treat absent Fetch Metadata as needing
   the Origin/Referer fallback, not as automatic success.

Route ordering is: resolve active principal, apply the authenticated rate
limit, validate CSRF/origin/fetch metadata, validate body media type/size, parse
the strict request model, then call the state-changing service. No handler
mutation occurs earlier. The anonymous-idempotent logout behavior documented
below is the only case that can return before authenticated CSRF validation.

`SameSite=Lax` and the `__Host-` cookie prefix are defense in depth, not the
sole CSRF control. CORS never allows wildcard origins or wildcard headers with
credentials.

Origin comparison parses and canonicalizes scheme/host/default port, then
compares the complete origin tuple; it never uses string prefix/suffix matching
and does not accept a path, credentials, `null`, or a nondefault production
port.

The Google callback is the explicit exception: it is a cross-site GET and is
protected by state, browser binding, nonce, PKCE, exact redirect, and one-time
consumption rather than the application CSRF header.

## Flow E: logout

Endpoint:

```text
POST /api/v1/auth/logout
```

Require an active principal and CSRF. Revoke the current session with reason
`logout`, append an event, and commit. Then expire the session and transient
login cookies using the same name/path/security attributes used to set them.
Return `204 No Content` with `Cache-Control: no-store`.

Logout behavior is exact: an absent, malformed, unknown, revoked, or expired
session receives `204` after cookie clearing and cannot mutate an active
account, so no CSRF token can be required for that anonymous result. Once an
active session is resolved, CSRF is mandatory and failure leaves it active.
Logout must never be a state-changing GET.

## Flow F: logout all and revoke one session

`POST /api/v1/auth/logout-all` locks the parent user row and revokes all active
sessions belonging to the principal. `DELETE /api/v1/auth/sessions/{sessionId}`
first scopes the session UUID to the
principal's user ID; another user's UUID is returned as `404`. Revoking the
current session clears its cookie.

Both require CSRF. Neither calls Google because no Google authorization is
retained.

## Flow G: account deletion

Account deletion is required before public launch, even though personal play
records are a later feature.

1. Require an active session, CSRF, and an exact explicit confirmation value.
2. Require `session.created_at <= now` and
   `now - session.created_at <= configured recent-login window` (ten minutes
   initially). Every version-1 session is issued only by a completed Google
   authentication, so its creation time is its authentication time.
3. If stale, return `403 RECENT_AUTH_REQUIRED` and offer a dedicated Google
   reauthentication flow with attempt intent `reauth_delete`. Initiate that
   flow only through the authenticated, CSRF-protected POST specified in the
   API contract; its JSON response supplies the provider URL for a deliberate
   same-window navigation.
4. The attempt stores the current local user as `expected_user_id`. That
   attempt also stores the current local session as `expected_session_id`.
   The same still-active local session cookie must accompany the callback.
5. The callback must match the current user's issuer and subject exactly; it
   may not switch or link accounts. A mismatch fails closed.
6. The dedicated authorization request adds `prompt=select_account`, forcing
   an explicit account selection while retaining the same `openid email`
   scopes. On success, rotate the application session at the new callback time.
7. Delete the user and all user-owned data in one transaction, preserving only
   anonymized security-event rows.
8. Clear cookies after commit and return a clean logged-out page.

Do not rely on an old Google access token, because none is stored. Do not use
email to match the reauthenticated identity.

This is recent Google identity confirmation, not proof that Google prompted
for a password, passkey, or MFA. Do not represent it as strong authentication.
If future features need a stronger assurance level, add an authenticator and
provider-supported assurance policy in a separate design.

## Flow H: provider or database failure

- Google unavailable before authentication: show a retryable generic login
  error; do not create a user/session.
- JWK refresh unavailable with no valid cached key: fail closed.
- PostgreSQL unavailable: do not redirect to Google from the start route; the
  callback still returns a clean local no-store `303 failed`, issues no cookie,
  and never leaves code/state in its Location.
- Commit succeeds but response is lost: the session row may exist without its
  cookie and expires normally; no recovery by exposing the raw token is
  possible.
- Cookie is set but commit failed: forbidden ordering; cookies are set only
  after commit.
- Event insertion failure: fail the security-sensitive transaction rather than
  silently losing required audit evidence.
