# Security, Privacy, and Operations

## Threat model

| Threat | Required control | Required proof |
|---|---|---|
| Application asks for Gmail password | Only Google-hosted OIDC authentication; no password fields or endpoints | UI/route review; browser test |
| Login CSRF or session swapping | Random state, browser-binding cookie, nonce, PKCE, exact callback, one-time attempt | cross-browser/state mismatch tests |
| Authorization-code interception/injection | Authorization code flow, PKCE S256, TLS, exact redirect, atomically claimed attempt | negative callback and replay tests |
| Open redirect through `returnTo` | exact internal path allowlist stored server-side | encoded/bypass test matrix |
| Forged or wrong-client ID token | maintained OIDC validator checks signature, issuer, audience, `azp`, expiry, nonce | fake-JWK/claim tests |
| Account takeover through email collision | identity only by issuer+subject; email nonunique; no automatic linking | PostgreSQL collision test |
| Concurrent first-login duplication | unique issuer/subject plus full rollback/retry | concurrent PostgreSQL test |
| Session fixation | no pre-auth app session; issue fresh random token after committed login | cookie replacement test |
| Session token stolen by XSS | HttpOnly host-only cookie, CSP, no browser token storage | cookie/storage browser audit |
| Session database disclosure | only SHA-256 of 256-bit tokens stored | schema and repository test |
| Session replay after logout/suspension | server lookup on every protected request; revocation in database | route and concurrency tests |
| CSRF on personal-data writes | session-bound HMAC token, exact Origin/Referer, Fetch Metadata, JSON/custom header, SameSite | forged-origin tests |
| Cookie injection from subdomain | production `__Host-` names, Secure, no Domain, Path `/` | Set-Cookie assertions |
| Provider endpoint substitution/SSRF | hard-code Google discovery URI; no request/config provider URL in production | config tests |
| Host-header poisoning | build callback from validated `PUBLIC_BASE_URL`; explicit proxy trust | hostile Host test |
| Tokens/secrets leaked to logs | centralized redaction, allowlisted event fields, no raw provider errors | caplog/static scans |
| Excessive scopes or persistent Google access | only `openid email`; no offline access; discard all provider tokens | authorization URL/token persistence tests |
| User enumeration | generic public failures; no lookup by public email endpoint | response equivalence tests |
| Cross-user object access | owner-scoped queries and indistinguishable 404 | future resource authorization tests |
| Provider/database outage | fail closed; public rankings remain usable | injected outage tests |
| Abuse/attempt-table growth | edge/app rate limit and daily bounded cleanup | rate/cleanup tests |
| Restored production database used in unsafe environment | isolated credentials, callback domains, and cookie names per environment | restore runbook check |

This authentication system does **not** prove age, residence, or legal
eligibility to gamble. Google authentication must never be described as age
verification. Any future age gate requires a separate product/legal design.
Likewise, the account-deletion confirmation flow proves a recent Google account
selection, not that Google required fresh password, passkey, or MFA entry.

## Application configuration

Required values before production authentication can be enabled:

```text
APP_ENV=production
AUTH_ENABLED=false
PUBLIC_BASE_URL=https://<owned-domain>
GOOGLE_OIDC_CLIENT_ID=<web client ID>
GOOGLE_OIDC_CLIENT_SECRET=<secret reference/value>
AUTH_SECRET_KEYS=<newest-first comma-separated 43-character base64url keys>
AUTH_SESSION_IDLE_SECONDS=86400
AUTH_SESSION_ABSOLUTE_SECONDS=604800
AUTH_SESSION_TOUCH_SECONDS=300
AUTH_LOGIN_ATTEMPT_SECONDS=600
AUTH_MAX_ACTIVE_SESSIONS=5
AUTH_RECENT_LOGIN_SECONDS=600
```

The implementation may integrate these into the API's existing settings
object, but it must validate them as a unit.

`AUTH_ENABLED` accepts only exact lowercase `true` or `false` and defaults to
`false` when absent. While false, every other auth-only setting—including
public origin, Google credentials, and root keys—may be absent, and no provider
or schema readiness check runs. No auth cookie is accepted or issued, the
session endpoint returns its disabled/no-user shape without an auth-table
lookup, the callback strips its query through a clean local no-store 303, and
all other auth/account routes return bounded `AUTH_UNAVAILABLE`; rankings
remain independent. Any auth secret that is nevertheless present remains
redacted. Setting the flag true requires every invariant below plus an
auth-schema readiness check. There is no HTTP/frontend toggle. Production
deployment keeps it false until the release gate and explicit operator change.

The readiness check verifies the single Alembic head and required auth tables;
it never calls `Base.metadata.create_all()` or auto-runs a migration. An
enabled deployment with missing schema is a deployment failure. Deploy schema
first, then code/config, using the project's normal migration procedure.

Production startup invariants:

- `APP_ENV` is exactly `development`, `test`, or `production` and is explicit
  whenever auth is enabled;
- `PUBLIC_BASE_URL` passes the exact HTTPS origin-only syntax rules below;
- callback is derived, not separately user-controlled;
- Google client values and auth keys are nonempty and not example markers;
- duration values are within reviewed bounds;
- session absolute lifetime exceeds idle lifetime;
- cookies are Secure with production `__Host-` names;
- allowed frontend origin is exactly `PUBLIC_BASE_URL`;
- debug mode and interactive API docs do not expose configuration;
- trusted proxy hops/networks are explicit.

For enabled production auth, `PUBLIC_BASE_URL` is an origin only (no path
other than `/` and no explicit nondefault port), and its host is neither an IP
literal nor localhost. The Google web client ID is trimmed, bounded to 255
characters, contains no controls, and ends in `.apps.googleusercontent.com`.
The client secret is 8–512 characters with no controls or surrounding
whitespace; do not require a vendor-prefix regex that Google may change.
Domain ownership cannot be established from string validation; it is a
separate recorded production release-gate check. Deployment review verifies
that the configured origin is exactly the operator-approved owned origin and
the registered Google callback uses it.

Reviewed numeric bounds are:

| Setting | Minimum | Maximum |
|---|---:|---:|
| Login attempt | 300 seconds | 900 seconds |
| Session idle | 900 seconds | 86,400 seconds |
| Session absolute | 3,600 seconds | 2,592,000 seconds (30 days) |
| Session touch | 60 seconds | lesser of 900 seconds or one quarter of idle |
| Active sessions per user | 1 | 10 |
| Recent-login window | 300 seconds | 900 seconds |

Idle must also be strictly less than absolute. Changing defaults within these
bounds still requires tests; changing the bounds requires a documented risk
review.

The Google discovery URI is a code constant:

```text
https://accounts.google.com/.well-known/openid-configuration
```

Tests may inject a fake provider URL through dependency injection. A production
environment variable must not redirect discovery or JWK retrieval.

Provider transport limits are code-reviewed constants in version 1:

| Item | Limit |
|---|---:|
| Connect timeout | 3 seconds |
| Read/write timeout | 5 seconds |
| Pool-acquisition timeout | 2 seconds |
| Token response body | 64 KiB |
| Discovery or JWK body | 256 KiB |
| ID token string | 16 KiB |
| Access token string | 8 KiB |
| Callback query count | 12 parameters |
| Authorization code | 4,096 characters |

The reverse proxy also applies a conventional bounded request-target/header
limit. Provider transports do not follow redirects. Any increase requires a
test and review; a provider response that exceeds a limit fails closed without
including its content in logs.

## Secrets

- Keep Google client secret and authentication root keys out of Git, frontend
  environment variables, built JavaScript, command arguments, logs, database,
  and backup manifests.
- Prefer an operating-system credential facility or secret manager. A local
  `.env` is acceptable only for development with mode `0600`.
- `VITE_*` variables are public build inputs and may never contain a secret.
- Do not print settings dataclass/repr values unless secret fields are
  explicitly redacted.
- Do not put a secret in a systemd unit checked into the repository; reference
  a protected environment/credentials file.

### Authentication-key rotation

1. Generate a new independent 32-byte key.
2. Deploy it first in `AUTH_SECRET_KEYS`, retaining the prior key afterward.
3. New OIDC ciphertext and CSRF tokens use the new key; validation accepts the
   retained key.
4. Wait at least the currently configured absolute application-session
   lifetime (seven days initially) plus deployment safety margin.
5. Remove the prior key and verify login, session, CSRF, and cleanup health.

Changing local auth keys does not rotate Google credentials or session-token
digests. A suspected auth-root compromise requires invalidating pending OIDC
attempts and all application sessions in addition to key rotation.

## Google Cloud setup

Use separate Google Cloud projects/clients for development/testing and
production. The production project should be owned by an organizational or
durable operator account rather than a disposable personal account.

### Development

- application type: Web application;
- external audience in testing mode;
- explicit test users;
- exact local callback, normally
  `http://localhost:5173/api/v1/auth/google/callback`;
- only OpenID/email scopes.

### Production

- verify ownership of the public domain;
- configure an exact HTTPS callback;
- set current developer/support contacts;
- match application name and branding to the public site;
- publish an accessible homepage, privacy policy, and terms link on the owned
  domain;
- describe that Google account identity/email are used only to create and
  secure a local account;
- request only `openid` and `email`;
- complete Google's then-current branding/verification steps before public
  launch;
- follow Google's current Sign in with Google button guidelines.

Google's production policy applies even when OIDC is used only for
authentication. Do not call the product "Gmail login" or imply that the
application reads email.

## Privacy requirements

Before a public login is enabled, publish a product-specific privacy notice
reviewed by the operator (and legal counsel if appropriate). It should state in
plain language:

- data collected: Google stable account identifier, verified email,
  authentication timestamps, local sessions, an in-memory keyed source
  pseudonym for rate limiting (up to one idle hour), and future user-entered
  ticket records;
- data not collected: Gmail password/content, contacts, Drive/Calendar data,
  Google access/refresh tokens, raw IP/user-agent data in the auth database;
- purposes: account creation, session security, and user-owned play tracking;
- retention periods and authentication-event retention;
- that deleted live data may remain in access-restricted backups until those
  backups age out under the documented 7-daily/4-weekly/12-monthly policy;
- whether infrastructure providers process logs/backups;
- how to sign out, revoke sessions, and delete the local account/data;
- support/privacy contact;
- that disconnecting/deleting the local account does not delete the Google
  Account;
- that removing the app from Google does not necessarily revoke an already
  issued local session immediately, and that the user can revoke it from the
  app's session controls;
- that the app is independent of Google and the Illinois Lottery.

Do not treat a privacy-policy template or this blueprint as legal advice.

### Data minimization rules

- No profile scope/picture/name in version 1.
- No raw Google claims JSON.
- No raw IP or complete user-agent in auth tables/events.
- No email in structured auth events or routine logs.
- No persistent identifier in product analytics without a separate consent and
  privacy design.
- No personal play data feeds the official lottery ranking model.

## CSRF, CORS, and content security

Production serves one origin and should omit CORS headers for normal
same-origin traffic. A separate credentialed browser API origin is unsupported.
Unsafe authenticated requests require all CSRF layers in the flow document.

Recommended production response headers:

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; worker-src 'self'
```

At the design cutoff, two ranking bars use React inline width styles. Replace
them with semantic `<progress>` elements or another stylesheet-only rendering
before enforcing this header; do not add `'unsafe-inline'` merely to preserve
those bars. Do not add broad third-party script origins for login: the backend
redirect flow requires no Google JavaScript SDK.

Auth start/callback/session responses use `Referrer-Policy: no-referrer` and
`Cache-Control: no-store`. Sensitive account pages use `no-store` and must not
be cached by a service worker.

Enable HSTS only after HTTPS works on every covered production subdomain.

## Rate limiting

Google protects its credential entry, but the application's endpoints still
need abuse and storage controls. Initial edge limits per resolved client source
are:

| Endpoint | Initial limit | Behavior |
|---|---:|---|
| Google login start | 10 per 10 minutes, burst 3 | `429` + `Retry-After` |
| Google callback | 30 per 10 minutes, burst 10 | clean local 303 `failed`; no lookup |
| Session/account reads | 120 per 10 minutes, burst 30 | `429`; no auth-table lookup |
| Session/account writes | 60 per 10 minutes | `429`; no state change |
| Reauthentication/account deletion POSTs | 5 per hour | `429`; event emitted |

These are starting operational values, not security constants. Tune from
aggregate metrics without logging email or Google subject. Only trust client
addresses supplied by an explicitly configured reverse proxy; otherwise use
the direct socket peer and ignore forwarding headers.

Version 1 has two layers:

1. Configure equivalent source limits at the selected TLS reverse proxy before
   public enablement. If that proxy is not selected/configured yet, keep
   `AUTH_ENABLED=false`; this does not block completing application code.
2. Add a bounded in-process token-bucket backstop. Key source buckets by
   `HMAC(derived_telemetry_key, canonical_source_address)` and protected
   account buckets by local user UUID. The source pseudonym exists only as the
   bounded in-memory cache key; never persist or log it or the raw address. Use
   a monotonic clock, a concurrency-safe cache, one-hour idle eviction, at most
   20,000 keys, and fail new keys with 429 after expired-key eviction if the cap
   is exhausted. A process restart intentionally clears this defense-in-depth
   state.

The initial deployment uses one API worker. More workers multiply in-process
limits, so a multi-worker deployment requires the proxy layer or a reviewed
shared ephemeral limiter before auth remains enabled. Return integer
`Retry-After` seconds. Aggregate every rejection, but insert at most one
`rate_limited` auth event per known-user bucket window; unknown-source floods
never amplify into database rows.

The callback limit is special because its request target contains code/state.
Both proxy and application rejection paths must return a no-store `303` to the
clean local `/?authResult=failed` without logging or echoing the query. A
generic proxy 429 page that leaves the callback URL visible does not pass the
release gate.

## Logging and metrics

Every API request receives a server-generated UUIDv4 correlation ID and returns
it as `X-Request-ID`; problem bodies and `auth_events` may reference the same
value. Do not trust a public client-supplied request ID as the event key. A
trusted reverse-proxy ID may be recorded only after an explicit proxy-boundary
design; version 1 simply generates its own.

Allowed aggregate metrics:

- login starts/success/failure by stable reason code;
- provider exchange latency and failure class;
- active/revoked/expired session counts;
- CSRF failures by route (not by user/email);
- rate-limit counts;
- expired attempt and retention-cleanup backlog;
- account deletions as a count.

Metric labels are low-cardinality enums/routes only. Never use user/session/
attempt/request IDs, source pseudonyms, email, or provider subject as a metric
label.

Routine redacted API/access logs retain at most 30 days and aggregate auth
metrics at most 90 days. Configure journald/proxy/metrics storage accordingly.
A documented security-incident legal hold may retain a narrowly scoped export
longer with access controls; it is an exception, not silent default retention.

Forbidden log content includes:

- query strings on the callback route;
- `Cookie`, `Set-Cookie`, or `Authorization` headers;
- request/response bodies from Google token exchange;
- provider ID/access/refresh tokens;
- code, state, nonce, PKCE verifier/challenge, browser-binding token;
- Google client secret or local root keys;
- email, subject, hosted domain, raw IP, full user agent;
- unredacted database URLs.

Configure the reverse proxy/access logger to omit callback query strings and
all auth cookies. Exception reporting must run a redaction filter before
transport.

Keep `httpx`, `httpcore`, Authlib/JWT, SQL parameter, and ASGI multipart/body
wire logging at non-body production levels. Catch provider exceptions at the
adapter boundary and log only the local reason code/request ID; never interpolate
`str(exc)`, because library errors may contain a response or request URL.

## Provider metadata and time

- Use the hard-coded discovery URI over TLS.
- Honor JWK/discovery cache headers and key rotation.
- A cached key may be used only within its valid cache policy; do not accept
  stale keys indefinitely when refresh fails.
- Bound external requests and response sizes.
- Synchronize host time. ID-token and session validation depend on UTC time.
- Maximum accepted OIDC clock skew is 60 seconds. A larger observed skew is an
  operations failure, not a reason to weaken validation.

## Database access boundary

The production database is not publicly reachable. Use a local protected
socket or verified TLS for any remote connection. Where the deployment permits
role separation, the web runtime role has only the existing application DML
privileges it needs and no schema-create/drop privilege; migrations run under a
separate controlled role. Authentication repositories use bound SQLAlchemy
parameters and never interpolate a token, identity, UUID, or reason into SQL.
Database URLs remain redacted from logs and status artifacts.

## Backup and restore safety

Once authentication launches, PostgreSQL dumps contain personal data and
security material even though they contain no raw session/provider token.
Retain the existing 7 daily, 4 weekly, and 12 monthly generations only on an
encrypted, access-controlled destination; dump and manifest modes remain
`0600`, the containing directory `0700`, and manifests contain counts rather
than row values. The privacy notice discloses this backup retention. Expired
generations are deleted through the existing guarded retention process.

Disposable restore verification must use an isolated database, development
Google credentials, nonproduction cookie names, and no public route. Destroy
the restored database after verification.

A production disaster restore is never exposed directly. Before traffic:

1. keep authentication in explicit unavailable mode;
2. upgrade/verify the restored schema and run both database/auth audits;
3. mark every pending/exchanging OIDC attempt terminal;
4. revoke **every** restored application session with `security_event`;
5. reconcile account deletions and other writes newer than the backup from the
   operator's incident/change records to the extent available;
6. rotate credentials if the disaster involved possible disclosure;
7. document the recovery point and only then re-enable login.

A backup is a historical exception to immediate live deletion, not an active
user database. Restoring necessarily returns the system to an older recovery
point; the operator must never claim a zero-data-loss recovery objective unless
continuous recovery and deletion replay have actually been implemented.

## Maintenance command

Add an idempotent command such as:

```text
python scripts/maintain_authentication.py --dry-run
python scripts/maintain_authentication.py --apply
```

Requirements:

- defaults to dry-run;
- runs from database-only settings even when `AUTH_ENABLED=false` and never
  needs the Google client secret or local root key;
- uses the same advisory-lock convention as other maintenance where useful;
- processes deterministic batches (1,000 rows maximum per transaction) with
  row locking/`SKIP LOCKED` where concurrent callback/session work could race;
- reports only counts by category;
- marks expired attempts before deletion;
- converts expired/stuck `exchanging` attempts to terminal failure before
  deletion;
- deletes only rows beyond documented retention;
- never deletes active users/identities;
- has unit and PostgreSQL tests;
- may run daily from the web service's scheduler or a separate least-privilege
  systemd unit, not from an HTTP request.

## Operator account controls

There is no admin web UI. If suspension is needed, implement a guarded CLI:

```text
python scripts/manage_user_account.py --show-user-id <uuid>
python scripts/manage_user_account.py --suspend-user-id <uuid> --reason-code <code>
python scripts/manage_user_account.py --reactivate-user-id <uuid> --reason-code <code>
python scripts/manage_user_account.py --revoke-sessions-user-id <uuid> --reason-code <code>
python scripts/manage_user_account.py --delete-user-id <uuid> \
  --confirm-delete-user-id <same-uuid> --reason-code <code>
```

Mutations require explicit flags and an allowlisted reason code, print a
resolved non-PII target summary, use one transaction, and append events. The
suspension codes are defined in the schema. Reactivation accepts
`review_cleared`, `operator_correction`, or `test_complete`; manual session
revocation accepts `suspected_compromise`, `user_request`, or
`operator_correction` and stores session revocation reason `security_event`.
Do not choose an account by email because email is not unique. Arbitrary notes
belong in the operator's protected case system, not auth tables or command
arguments.

Operator deletion accepts only `user_request`, `legal_request`, or
`operator_correction`, requires the second exact UUID confirmation, and uses
the same event/cascade transaction as self-service deletion. Identity
verification and any legal case notes remain in the protected external case
process; the CLI never looks up or prints email/provider subject.

Mutation commands default to dry-run and require a separate `--apply`; the
examples above intentionally omit it. Refuse conflicting action flags and an
unknown/noncanonical UUID. Exit nonzero when the user is missing or the
requested state transition is invalid; do not make silent idempotent changes
that hide an operator targeting error.

The guarded operator CLI remains usable with `AUTH_ENABLED=false`; it needs
database settings but no provider/local encryption secret for these account
and session operations.

Reactivation does not create a session; the user must authenticate again.

## Incident response

### Google client secret suspected leaked

1. Disable new login or put auth into explicit unavailable mode.
2. Rotate the client secret in Google Cloud and deployment secrets.
3. Expire all pending OIDC attempts.
4. Review aggregate auth events; never paste tokens into an incident ticket.
5. Re-enable only after callback and negative-token smoke tests.

Existing local sessions do not depend on the Google client secret and need not
automatically be revoked unless broader application compromise is suspected.

### Local authentication root key suspected leaked

1. Disable new login and authenticated writes.
2. Rotate keys.
3. Expire all OIDC attempts and revoke all application sessions.
4. Review secret/log exposure and redeploy.

### Database or server compromise suspected

1. Isolate the service and preserve security evidence under the operator's
   incident process.
2. Rotate database, Google, and local auth secrets as exposure warrants.
3. Revoke every local session.
4. Assess exposure of verified email and future personal play history.
5. Notify affected users/regulators if required after appropriate legal review.

### Google outage

Existing valid local sessions continue until their normal server-side
expiration. New login/reauth fails closed with a bounded retry message. Public
rankings stay available. Do not extend session deadlines or add password login
as an outage workaround.

## Production release gate

Do not enable the sign-in button publicly until all are true:

- owned HTTPS domain and exact reverse-proxy behavior verified;
- direct navigation/refresh at `/account` serves the SPA, while unknown
  `/api/*` routes remain JSON 404s and are never rewritten to `index.html`;
- separate production Google OAuth client configured;
- homepage, privacy, terms, contact, and branding present;
- only `openid email` appears on the actual consent flow;
- secrets stored outside Git/build artifacts;
- migration backup/restore tested;
- disposable restores use isolated auth configuration, and the production
  restore drill invalidates every restored attempt/session before simulated
  exposure;
- production rollback plan uses forward correction and never drops populated
  authentication tables;
- complete test and audit suite passes;
- cookie/header/CORS checks pass in a real browser;
- callback logs omit query strings;
- account deletion and session revocation work;
- one manual real-Google test account completes login, refresh, logout, revoke,
  reauth, and deletion without provider tokens reaching the browser/database.

After the checklist is recorded, enabling auth is a separate intentional
configuration deployment. If any prerequisite later becomes unsafe, set
`AUTH_ENABLED=false`; for an incident, also perform the revocation/rotation
steps in the relevant runbook because the flag alone does not rewrite database
state.
