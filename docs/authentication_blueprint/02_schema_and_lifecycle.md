# Schema and Lifecycle

## General conventions

- Use PostgreSQL `uuid` primary keys generated in Python with `uuid4()` so no
  database extension is required and test databases remain portable.
- Use UTC-aware `timestamptz` columns for every timestamp.
- Use application-defined string states plus database check constraints rather
  than PostgreSQL enum types, matching the existing project style.
- Use `BYTEA` for fixed-length digests and check `octet_length(...) = 32` in
  PostgreSQL.
- Use `server_default=now()` where appropriate, but pass an explicit clock into
  services for deterministic tests.
- Never use an email column as a primary, foreign, or unique key.
- Never store a provider password, authorization code, raw ID token, access
  token, or refresh token in any table.

The SQLAlchemy mappings should live in `auth_models.py` and share
`models.Base`. Alembic and schema-smoke tests must explicitly import both
`analytics_models` and `auth_models` so `Base.metadata` is complete.

## `app_users`

This is the provider-neutral local account. It intentionally contains no
email or profile data.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | UUID | no | primary key; Python-generated |
| `status` | varchar(16) | no | `active` or `suspended`; default `active` |
| `created_at` | timestamptz | no | default `now()` |
| `updated_at` | timestamptz | no | default `now()`; explicitly updated |
| `last_login_at` | timestamptz | yes | set only after successful login |
| `suspended_at` | timestamptz | yes | required only when suspended |
| `suspension_reason_code` | varchar(64) | yes | allowlisted; suspended only |

Constraints:

```text
status IN ('active', 'suspended')

 (status = 'active'
 AND suspended_at IS NULL
 AND suspension_reason_code IS NULL)
OR
(status = 'suspended'
 AND suspended_at IS NOT NULL
 AND suspension_reason_code IN (
   'abuse', 'suspected_compromise', 'legal_request', 'user_request',
   'test_account', 'operator_correction'
 ))
```

Also require `updated_at >= created_at`, `last_login_at IS NULL OR
last_login_at >= created_at`, and `suspended_at IS NULL OR suspended_at >=
created_at`. Every successful login and status change sets `updated_at` with
the same injected server clock used for the operation.

Suspension is an operator action, not a public API. Suspending a user and
revoking all active sessions occur in one transaction. A suspended identity
may complete Google authentication, but local session issuance is denied with
a generic account-unavailable response.

Account deletion hard-deletes `app_users`. It is not represented as another
status. Child identities and sessions cascade; future personal play rows must
also cascade or be explicitly erased in the same transaction. Authentication
events survive only with nulled foreign keys.

## `user_identities`

This table binds a local account to a verified external identity.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | UUID | no | primary key |
| `user_id` | UUID | no | FK `app_users.id ON DELETE CASCADE` |
| `provider` | varchar(32) | no | `google` in version 1 |
| `issuer` | varchar(255) | no | canonical `https://accounts.google.com` |
| `subject` | varchar(255) | no | verified, case-sensitive Google `sub` |
| `email` | varchar(320) | no | current verified display email |
| `email_verified` | boolean | no | must be true |
| `last_authenticated_at` | timestamptz | no | newest successful login |
| `created_at` | timestamptz | no | first successful authentication; explicit server time |

Constraints and indexes:

- unique `(issuer, subject)`;
- unique `(user_id, provider)` in version 1;
- check `provider = 'google'`;
- check `issuer = 'https://accounts.google.com'`;
- check `email_verified`;
- check subject against `^[!-~]+$` and `octet_length(subject) <= 255`, enforcing
  the printable non-whitespace ASCII byte contract at the database boundary;
- check nonblank email and no leading/trailing email whitespace;
- check `last_authenticated_at >= created_at`.

The unique issuer/subject constraint is the final concurrency authority. A
second simultaneous first login for the same Google subject must not create a
second local account. The service performs creation in one transaction; on a
unique conflict it rolls the transaction back in full, reads the winning
identity, and continues. No orphan `app_users` row may remain.

Email updates replace the identity's display metadata after each valid login.
An email collision with another identity is allowed and does not link, merge,
or block either identity.

Email validation follows the exact rule in the architecture document.
Application validation rejects unsafe categories and oversize values before
the insert; database length/nonblank/trim checks are a second boundary. The
optional Google `hd` claim is deliberately ignored and not persisted.

## `oidc_login_attempts`

This table provides single-use, browser-bound server state for the redirect
flow. It is deliberately short-lived.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | UUID | no | primary key and correlation anchor |
| `provider` | varchar(32) | no | `google` |
| `state_digest` | bytea | no | SHA-256 of 32-byte random state; unique |
| `browser_binding_digest` | bytea | no | SHA-256 of transient cookie token |
| `nonce_digest` | bytea | no | SHA-256 of OIDC nonce |
| `pkce_verifier_ciphertext` | varchar(256) | no | versioned authenticated encryption envelope |
| `return_path` | varchar(512) | no | validated internal path; default `/` |
| `intent` | varchar(24) | no | `login` or `reauth_delete` |
| `expected_user_id` | UUID | yes | FK `app_users.id ON DELETE CASCADE`; required for reauth only |
| `expected_session_id` | UUID | yes | FK `user_sessions.id ON DELETE CASCADE`; initiating session; reauth only |
| `status` | varchar(16) | no | lifecycle below; default `pending` |
| `created_at` | timestamptz | no | server time |
| `expires_at` | timestamptz | no | creation plus configured attempt lifetime; 10 minutes initially |
| `claimed_at` | timestamptz | yes | callback atomically claimed attempt |
| `completed_at` | timestamptz | yes | terminal outcome time |
| `failure_code` | varchar(64) | yes | allowlisted internal reason only |

Statuses:

```text
pending -> exchanging -> succeeded
                    \-> failed
pending -> denied | expired | superseded
```

The column-shape matrix is exact:

| Status | `claimed_at` | `completed_at` | `failure_code` |
|---|---:|---:|---:|
| `pending` | null | null | null |
| `exchanging` | set | null | null |
| `succeeded` | set | set | null |
| `failed` | set | set | set |
| `denied` | set | set | set |
| `expired` | null | set | set |
| `superseded` | null | set | set |

`failure_code` is one of the bounded application constants, initially
`user_denied`, `attempt_expired`, `attempt_superseded`, `invalid_callback`,
`provider_unavailable`, `token_exchange_failed`, `token_validation_failed`,
`attempt_decryption_failed`, `exchange_abandoned`, `identity_mismatch`, or
`account_unavailable`. It is never copied from a provider error or exception
message.

Constraints and indexes:

- unique `state_digest` and unique `browser_binding_digest`;
- all three digests have exactly 32 bytes;
- check `provider = 'google'`;
- check `return_path IN ('/', '/account')` in version 1;
- require `pkce_verifier_ciphertext` to match exact shape
  `^v1[.][A-Za-z0-9_-]{152}$` (155 characters total), with decoded component
  lengths and authentication still validated by the crypto service;
- `status IN ('pending', 'exchanging', 'succeeded', 'failed', 'denied',
  'expired', 'superseded')`;
- `intent IN ('login', 'reauth_delete')`;
- `intent = 'login'` exactly when both `expected_user_id` and
  `expected_session_id` are null;
- `intent = 'reauth_delete'` exactly when both are nonnull; the service also
  proves the session belongs to that user;
- `expires_at > created_at`;
- terminal rows require `completed_at`;
- enforce the status/claimed/completed/failure matrix above;
- when present, check `failure_code` against the exact initial list above;
- when present, `created_at <= claimed_at <= completed_at`; when only
  `completed_at` is present, require `created_at <= completed_at`;
- index `(status, expires_at)` for claim and cleanup;
- indexes on nonnull `expected_user_id` and `expected_session_id` for cascades.

The PKCE verifier is encrypted using authenticated encryption with a key
derived from the configured authentication secret. Do not invent a cipher;
use a maintained cryptography library. State, nonce, and browser binding are
already high-entropy one-time values and therefore may be stored as SHA-256
digests.

Only one pending attempt is supported per browser binding. Starting another
attempt marks the earlier pending row `superseded` and overwrites the transient
cookie. This intentionally makes the earlier tab fail rather than weakening
browser binding. If the identified attempt is already `exchanging` and its
30-second post-expiry grace has not elapsed, a new start is not allowed to
supersede it: ordinary navigation gets
the fixed local `in_progress` result and reauth POST gets `AUTH_IN_PROGRESS`.

No database transaction remains open during token exchange. Claim the attempt
with a row lock and commit `exchanging`; perform the Google network operation;
then commit the terminal result and local session in a new transaction.

## `user_sessions`

This is the server-side application session.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | UUID | no | primary key; safe to expose only to its owner |
| `user_id` | UUID | no | FK `app_users.id ON DELETE CASCADE` |
| `token_digest` | bytea | no | SHA-256 of random cookie token; unique |
| `created_at` | timestamptz | no | session issue time |
| `last_seen_at` | timestamptz | no | throttled server activity time |
| `idle_expires_at` | timestamptz | no | creation plus configured idle lifetime; 24 hours initially |
| `absolute_expires_at` | timestamptz | no | creation plus configured absolute lifetime; 7 days initially; never extended |
| `revoked_at` | timestamptz | yes | server revocation time |
| `revocation_reason` | varchar(32) | yes | required exactly when revoked |

Allowed revocation reasons:

```text
logout
logout_all
session_limit
account_suspended
account_deleted
security_event
replaced
expired_idle
expired_absolute
```

Constraints and indexes:

- unique `token_digest` and check length 32;
- `created_at <= last_seen_at <= idle_expires_at <= absolute_expires_at`;
- `created_at < idle_expires_at <= absolute_expires_at`;
- `revoked_at IS NULL` exactly when `revocation_reason IS NULL`;
- when present, `revoked_at >= created_at`;
- check `revocation_reason` against the exact list above;
- index `(user_id, revoked_at, absolute_expires_at)`;
- index `(idle_expires_at, absolute_expires_at)` for cleanup.

An active session requires all of the following at request time:

```text
revoked_at IS NULL
created_at <= now
now < idle_expires_at
now < absolute_expires_at
app_users.status = 'active'
```

Session activity updates are write-throttled. At most once every five minutes,
set `last_seen_at = now` and:

```text
idle_expires_at = least(now + interval '24 hours', absolute_expires_at)
```

The implementation uses the validated configured idle duration in that
formula; 24 hours is the initial policy value shown here.

Expired sessions are marked revoked lazily on use or by maintenance. The
cookie's expiry is only browser cleanup; PostgreSQL is authoritative.
When both deadlines have passed, use `expired_absolute` if
`now >= absolute_expires_at`; otherwise use `expired_idle`. Set
`revoked_at = now`, never backdate it to the deadline.

On a sixth successful session, revoke the oldest active session with
`session_limit` before committing the new one. Order oldest by
`(created_at, id)` for a deterministic tie-break. Concurrent session creation
must first lock the stable parent `app_users` row with `SELECT ... FOR UPDATE`,
then count/lock the active session rows. Locking only a possibly empty set of
session rows is insufficient to prevent concurrent inserts.

## `auth_events`

This is a bounded security audit trail, not a general analytics stream.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | bigint | no | primary key; PostgreSQL identity/autoincrement |
| `occurred_at` | timestamptz | no | default `now()` |
| `event_type` | varchar(32) | no | allowlisted event |
| `outcome` | varchar(16) | no | `success`, `failure`, or `info` |
| `user_id` | UUID | yes | FK `app_users.id ON DELETE SET NULL` |
| `session_id` | UUID | yes | FK `user_sessions.id ON DELETE SET NULL` |
| `attempt_id` | UUID | yes | FK `oidc_login_attempts.id ON DELETE SET NULL` |
| `reason_code` | varchar(64) | yes | allowlisted, non-secret reason |
| `request_id` | UUID | yes | application correlation ID |
| `details` | JSONB | no | allowlisted non-PII object; server default `'{}'::jsonb` |

Initial event types:

```text
login_started
login_succeeded
login_failed
reauth_started
reauth_succeeded
reauth_failed
logout
logout_all
session_revoked
session_rejected
account_suspended
account_reactivated
account_deleted
```

Indexes:

- `occurred_at`;
- `(event_type, outcome, occurred_at)`;
- `(user_id, occurred_at)`;
- `session_id` and `attempt_id` for `ON DELETE SET NULL` maintenance;
- nonnull `request_id` for bounded incident correlation.

Constraints require one of the event types above, an outcome in
`('success', 'failure', 'info')`, a nonblank reason when present, a JSON object
for `details`, and a serialized `details` size no greater than 2 KiB. Event and
reason constants live in one shared module used by services and tests; route
or provider strings cannot become event types/reasons dynamically.

Initial emission policy:

| Event | Outcome | Required moment |
|---|---|---|
| `login_started` / `reauth_started` | `info` | same transaction as the stored attempt |
| `login_succeeded` / `reauth_succeeded` | `success` | same transaction as session issuance |
| `login_failed` / `reauth_failed` | `failure` | same transition that moves an identified attempt to any terminal non-success state |
| `logout` / `logout_all` | `success` | same transaction as revocation |
| `session_revoked` | `info` | session-limit, operator, or security revocation transaction |
| `session_rejected` | `failure` | known session rejected for expiry/status/CSRF; rate-limited |
| `account_suspended` / `account_reactivated` | `info` | same operator transaction |
| `account_deleted` | `success` | immediately before the user delete in the same transaction |

Unsolicited callbacks with no identifiable valid attempt and random unknown
session-token probes increment bounded aggregate metrics but do not insert an
unbounded event row per request. Rate limiting occurs before event amplification.

Version-1 `details` keys are limited to `provider`, `intent`,
`sessions_revoked`, `http_status_class`, and `duration_bucket_ms`. Values are
validated as follows: provider is `google`; intent is `login` or
`reauth_delete`; sessions revoked is an integer from 0 through 10; HTTP class
is `4xx` or `5xx`; and duration is the upper-bound bucket integer from
`(100, 250, 500, 1000, 2500, 5000, 10000, 10001)` where `10001` means over ten
seconds. Exact durations and arbitrary strings are not stored. Adding a key
requires schema-contract tests and a privacy review.

Version-1 event reason codes are the union below (or null when no reason is
needed); both application validation and a database check enforce it:

```text
user_denied
attempt_expired
attempt_superseded
invalid_callback
provider_unavailable
token_exchange_failed
token_validation_failed
attempt_decryption_failed
exchange_abandoned
identity_mismatch
account_unavailable
session_limit
account_suspended
security_event
replaced
expired_idle
expired_absolute
session_invalid
csrf_invalid
rate_limited
abuse
suspected_compromise
legal_request
user_request
test_account
operator_correction
review_cleared
test_complete
```

The details object may contain provider name, HTTP class, number of sessions
revoked, or a bounded timing measurement. It must never contain an email,
subject, raw IP address, user-agent string, cookie, authorization code,
state, nonce, PKCE value, ID/access/refresh token, client secret, stack trace,
or raw provider response.

## Lifecycle and deletion

### Successful returning login

1. Update identity display claims and timestamps.
2. Reject if local user is suspended.
3. Revoke the oldest active session if the limit would be exceeded.
4. Create a new session and update `last_login_at` in the same transaction.
5. Append `login_succeeded` without secret metadata.

Steps 1–5 run while holding the local user's row lock. That same lock
serializes session-cap enforcement, suspension, reauthentication, and account
deletion for an existing user.

### Successful first login

1. Insert one `app_users` row.
2. Insert one `user_identities` row.
3. Insert session and event in the same transaction.
4. On issuer/subject conflict, roll back all three and retry as a returning
   login.

### Logout

Revoke only the current session, append an event, and clear the cookie. Logging
out locally does not log the person out of Google and does not call Google's
revocation endpoint because no Google authorization is retained.

### Logout all

Lock the parent user row, revoke every active session for the current user
including the caller, append one summary event, and clear the current cookie.
The shared parent lock serializes this operation with session issuance.

### Suspension

Set user status and reason and revoke every active session in one transaction.
Identity rows remain so a later login can fail closed instead of creating a
new account.

### Account deletion

Require CSRF, explicit confirmation, and a session authenticated within the
configured recent-login window (ten minutes initially). Delete the user row in
a transaction after writing an event;
foreign keys null the event's user/session link as the deletion cascades.
Clear cookies after commit. A later Google sign-in creates a new, unrelated
local account.

## Retention maintenance

A daily idempotent maintenance task must:

- mark overdue pending attempts `expired`;
- mark an `exchanging` attempt that remains unfinished 30 seconds after its
  expiry as `failed` with `exchange_abandoned` (bounded provider calls normally
  finish earlier; this also recovers process crashes);
- delete terminal attempts completed more than 24 hours ago;
- lazily mark expired sessions with the appropriate revocation reason, then
  delete inactive sessions 30 days after the earliest timestamp that made them
  inactive (`revoked_at`, idle deadline, or absolute deadline); a long
  maintenance outage must not restart retention at the later repair time;
- delete auth events older than 90 days;
- never delete active identities or users;
- report counts only, without PII.

Backups may temporarily contain encrypted PKCE ciphertext and session digests.
The ten-minute attempt expiry and retention job limit their utility and volume.
Restored environments must use isolated Google credentials and must not be
publicly routable with production cookies or redirect URIs.

## Migration requirements

The authentication migration must:

1. use the then-current single Alembic head as `down_revision`;
2. create tables in dependency order: users, identities, sessions, attempts,
   events;
3. create named constraints and indexes matching the ORM;
4. downgrade in exact reverse dependency order;
5. add no users or synthetic identities;
6. make no changes to source, analytics, ranking, or catalog data;
7. pass fresh zero-to-head and populated prior-head-to-head PostgreSQL tests;
8. leave `alembic heads` at exactly one head.

The downgrade exists for disposable migration verification but drops all five
auth tables. Never run it against an environment containing real accounts;
production rollback is application rollback plus a forward corrective
migration after a verified backup, not destructive schema downgrade.
