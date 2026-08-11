# Authentication Release Gate Status

Recorded: 2026-08-10

Code status: complete through AU-09

Public authentication status: disabled

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

These are release blockers, not code-completion blockers. Keep
`AUTH_ENABLED=false` until every item is recorded as passed. Do not infer Google
age, residence, password, passkey, or MFA verification from this login or
recent-account-selection flow.
