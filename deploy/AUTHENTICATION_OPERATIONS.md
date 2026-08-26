# Authentication Operations

Authentication is intentionally disabled by default. `AUTH_ENABLED=true` is a
separate production configuration decision, not a migration side effect.

## Public-enable prerequisites

Keep authentication disabled until all of these are recorded:

- an owned HTTPS origin and exact Google web-client callback are configured;
- separate development and production Google clients request only
  `openid email` and the production consent/branding review is complete;
- homepage, privacy notice, terms, and support/privacy contact are public;
- the privacy notice covers verified email/Google identifier, sessions,
  in-memory source pseudonyms, 90-day auth events, and the encrypted
  7-daily/4-weekly/12-monthly backup lifecycle;
- secrets are loaded from a mode-`0600` environment/credential file and no
  `VITE_*` input contains a secret;
- one API worker is used;
- the selected TLS proxy has independently tested source limits equivalent to
  the blueprint, trusts only explicit proxy hops, logs `$uri` rather than the
  callback request target, and never logs Cookie/Set-Cookie headers;
- the callback proxy-limit path returns a no-store `303` to
  `/?authResult=failed` without retaining code/state in the address bar;
- the complete release gate in
  `docs/authentication_blueprint/05_security_privacy_and_operations.md` passes.

The application provides a bounded process-local HMAC-pseudonymous token
bucket as defense in depth. It is not a replacement for the TLS-proxy layer;
multiple workers multiply its limits. `AUTH_TRUSTED_PROXY_HOPS` must be `none`
or an explicit comma-separated CIDR list. Forwarding headers from every other
peer are ignored.

Production responses enforce HSTS, CSP without `unsafe-inline`, no-sniff,
referrer, and permissions headers. Auth/account responses are `no-store` and
normal same-origin traffic has no CORS policy. Verify HTTPS on every covered
subdomain before public exposure because HSTS includes subdomains.

## Google and local secret rotation

Use durable organizational ownership for the production Google Cloud project.
Before public authentication is enabled, set the protected production origin and
register exactly these Google values in a separate authorized change:

```text
PUBLIC_BASE_URL=https://scratchoffdata.com
Google authorized JavaScript origin: https://scratchoffdata.com
Google authorized redirect URI: https://scratchoffdata.com/api/v1/auth/google/callback
```

The callback path is the route implemented by the application. Keep authentication
disabled during the domain cutover, and keep the existing host-only `__Host-`
cookies without adding a cookie `Domain` attribute.

For an ordinary local root-key rotation, prepend a new independent 32-byte
base64url key to `AUTH_SECRET_KEYS`, deploy, wait at least the configured
absolute session lifetime plus margin, and then remove the prior key. Root-key
compromise additionally requires expiring every OIDC attempt and revoking every
local session. Google-client-secret compromise requires disabling login,
rotating that secret, and expiring pending attempts; local sessions need
revocation only if broader compromise is suspected.

Never place either secret in command arguments, systemd units, frontend inputs,
logs, backup manifests, or incident tickets.

## Daily retention

Install the dedicated timer separately from the working nightly data pipeline:

```bash
cp deploy/systemd/illinois-lottery-auth-maintenance.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now illinois-lottery-auth-maintenance.timer
```

Preview or run it explicitly:

```bash
.venv/bin/python scripts/maintain_authentication.py --dry-run
.venv/bin/python scripts/maintain_authentication.py --apply
```

The command needs only `DATABASE_URL`, defaults to dry-run, emits counts only,
uses transactions of at most 1,000 rows, terminalizes overdue/stuck attempts,
marks expired sessions using their original inactivity deadline, and enforces
24-hour attempt, 30-day inactive-session, and 90-day event retention.

## Operator account controls

The guarded CLI targets only a canonical local UUID, defaults mutations to
dry-run, prints no email/provider identity, and accepts only action-specific
reason codes:

```bash
.venv/bin/python scripts/manage_user_account.py --show-user-id <uuid>
.venv/bin/python scripts/manage_user_account.py --suspend-user-id <uuid> --reason-code abuse
.venv/bin/python scripts/manage_user_account.py --reactivate-user-id <uuid> --reason-code review_cleared --apply
.venv/bin/python scripts/manage_user_account.py --revoke-sessions-user-id <uuid> --reason-code suspected_compromise --apply
.venv/bin/python scripts/manage_user_account.py --delete-user-id <uuid> --confirm-delete-user-id <uuid> --reason-code user_request --apply
```

Suspension and session revocation are atomic. Reactivation creates no session.
Deletion uses the same user-data deletion seam and cascade as self-service
deletion. Keep identity verification and case notes in the protected external
case system.

## Backups, restores, and incidents

Post-authentication dumps contain personal data and security material. Store
them only on an encrypted access-controlled destination; dump/manifest modes
must remain `0600` and their directory `0700`. Manifests contain counts, never
row values. Disposable verification uses an isolated database, development
Google credentials, nonproduction cookies, no public route, and destroys the
database afterward.

A production disaster restore must remain unreachable with
`AUTH_ENABLED=false`. After schema/database/auth audits, run this transaction
against the explicitly selected restored database before traffic:

```sql
BEGIN;
UPDATE oidc_login_attempts
SET status = CASE WHEN status = 'pending' THEN 'expired' ELSE 'failed' END,
    completed_at = now(),
    failure_code = CASE WHEN status = 'pending'
                        THEN 'attempt_expired' ELSE 'exchange_abandoned' END
WHERE status IN ('pending', 'exchanging');
UPDATE user_sessions
SET revoked_at = now(), revocation_reason = 'security_event'
WHERE revoked_at IS NULL;
COMMIT;
```

Then reconcile post-backup deletions/writes from protected change records,
rotate possibly exposed credentials, record the recovery point, rerun
`docs/authentication_blueprint/auth_audit_queries.sql`, and only then consider
reenabling. The restored historical database is never exposed directly.

For suspected database/server compromise: isolate the service, preserve
evidence, rotate affected database/Google/local secrets, revoke every session,
and assess notification duties. During a Google outage, existing valid local
sessions continue normally; new login fails closed and public rankings remain
available.
