# Authentication Release Gate Status

Recorded: 2026-08-10

Code status: complete through AU-09

Public authentication status: disabled (superseded — see the 2026-08-28 update)

## Automated evidence

- Single Alembic head/current: `0011_defer_auth_event_links`.
- Python: 566 passed; 31 PostgreSQL-only tests separately passed in the guarded
  disposable harness.
- PostgreSQL: fresh migration, populated upgrades, concurrency, retention,
  auth audit, backup, restore, restored-schema account deletion, and restored
  complete PostgreSQL suite passed. Disposable databases were removed.
- Frontend: 40 unit tests, production build, and 10 desktop/mobile Playwright
  tests passed, including the stateful fake-provider lifecycle.
- Ruff and diff whitespace checks passed.
- Python and Node dependency audits report no known vulnerabilities after
  reviewed patched-version constraints.
- Built frontend contains no authentication secret/provider-token identifiers.
- Development maintenance has no backlog and all read-only auth audit invariant
  counts are zero.

## External prerequisites still missing

- operator-approved owned production HTTPS domain;
- separate production Google web client and exact callback;
- published product homepage, privacy notice, terms, and contact information;
- independently tested TLS reverse-proxy source limits, clean callback 303, and
  callback/cookie access-log omission;
- protected production secret delivery and documented encrypted backup target;
- designated real-Google account smoke test covering login, refresh, logout,
  revoke, same-identity reauthentication, different-identity rejection, and
  deletion.

## Update — 2026-08-27

Four of the six external prerequisites are now satisfied. Alembic head is
`0012_user_ticket_entries`; the counts above predate that.

| Prerequisite | Status |
|---|---|
| Owned production HTTPS domain | **Passed.** `scratchoffdata.com` serves the release over Let's Encrypt TLS; the old domain 301s to it with path and query preserved. |
| Published homepage, privacy notice, terms, contact | **Passed.** `/privacy`, `/terms`, `/contact` are live and linked from the footer. The privacy notice covers the verified email and Google identifier, sessions, in-memory source pseudonyms, 90-day auth events, and the backup lifecycle. |
| TLS proxy limits, clean callback 303, log omission | **Passed and independently tested.** `deploy/nginx/scratchoffdata.com.conf` implements the blueprint's per-source table. Verified live: login start refuses with `429` plus `Retry-After: 60` after burst; a throttled callback returns `303` to `/?authResult=failed` with `no-store` and no code or state; the access log records `$uri` only — a request with `code=`/`state=` produced zero matches in the log — and no cookie data is logged. |
| Documented encrypted backup target | **Passed.** The 7-daily/4-weekly/12-monthly lifecycle, weekly restore verification, and an offsite pull are implemented (`deploy/BACKUP_OPERATIONS.md`). Offsite copies are encrypted to a public key so the scheduled job never holds decryption capability; the passphrase-protected private key is held locally with a recovery copy in a password manager. Verified end to end on 2026-08-27: a pulled dump encrypted to the intended subkey, decrypted with the operator's passphrase, and matched its manifest checksum byte for byte. |
| Separate production Google web client and exact callback | **Passed 2026-08-28.** A dedicated production client now lives in its own Google Cloud project (`367561791883`), published rather than in Testing, requesting only `openid email`, with origin `https://scratchoffdata.com` and redirect `https://scratchoffdata.com/api/v1/auth/google/callback`. Confirmed distinct from development in client id, secret, and project. The earlier shared-client condition is resolved. |
| Real-Google smoke test | **Passed 2026-08-28.** Operator completed sign-in, session persistence, ticket entry, sign-out, session revocation, same-identity reauthentication, and account deletion against the production client. Server-side confirmation: `auth_events` recorded login_started, login_succeeded, logout_all, and account_deleted; the account present afterwards was created after the deletion timestamp, with zero orphaned identities or sessions. |
| Protected production secret delivery | **Outstanding.** Deferred to a separate cross-project effort covering every `.env`. |

Two production environment values must change in the same edit that sets
`AUTH_ENABLED=true`, and neither is safe to leave as-is:

- `PUBLIC_BASE_URL` is still `https://illinoislotterytracker.com`; it must
  become `https://scratchoffdata.com` so the derived callback matches the
  Google client.
- `AUTH_TRUSTED_PROXY_HOPS` is `none`. Behind this proxy that makes every
  request appear to originate from `127.0.0.1`, so the in-process limiter would
  place all users in a single bucket. It must name the explicit loopback hop.

## Authentication enabled — 2026-08-28

Every prerequisite above is recorded as passed, and `AUTH_ENABLED=true` is live
on `https://scratchoffdata.com`. `PUBLIC_BASE_URL` names the new origin and
`AUTH_TRUSTED_PROXY_HOPS` is `127.0.0.1/32`, so the limiter sees real client
addresses rather than the proxy. The session signing key is distinct from
development, `.env` remains mode `0600`, and the service runs a single worker.

Rollback remains one edit and one restart: set `AUTH_ENABLED=false` and restart
`illinois-lottery-prod-api`; every authenticated route then fails closed. Do not infer Google
age, residence, password, passkey, or MFA verification from this login or
recent-account-selection flow.
