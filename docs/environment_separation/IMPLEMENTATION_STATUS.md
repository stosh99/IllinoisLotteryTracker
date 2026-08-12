# Development / production implementation status

Status: **implemented, publicly promoted, and verified on 2026-08-12**.

## Outcome

Development and production have independent PostgreSQL databases, credentials,
application processes, and importer subprocesses. One database-free collector
publishes an immutable source bundle and fans that exact evidence out to both
environments.

Production runs from a Git-pinned release on `127.0.0.1:8766`. Nginx exposes that
loopback service at [https://illinoislotterytracker.com](https://illinoislotterytracker.com),
redirects HTTP and `www` requests to the canonical HTTPS origin, and does not expose
the Uvicorn port directly. Authentication remains explicitly disabled and the five
authentication/user tables contain zero rows.

The split source timer is active. The legacy timer, shadow service, shadow release,
original database, original raw archive, verified backups, and a named pre-promotion
release pointer remain preserved for rollback.

## Verified state

| Check | Result at public promotion |
| --- | --- |
| Development identity | `illinois_lottery_tracker_dev` as `lottery_dev` |
| Production identity | `illinois_lottery_tracker_prod` as `lottery_prod` |
| Migration revision | `0011_defer_auth_event_links` in both |
| Database comparison | all 20 table counts identical after live import |
| Authentication data | 0 rows in every auth/user table; public session reports unavailable |
| Source audit | zero failures |
| API binding | development 8765 and production 8766, both loopback only |
| Production release | Git commit `ac6e3b83dbc0e21406818497f46b1a0d6f3d3512` |
| Public API content | comparison available; 442 strategy-ranking rows; source run 101 |
| Public application | homepage, detail, history, and SPA routes returned successfully |
| Browser interaction | installed Chrome passed desktop and 390 px mobile flows with 52 live games |
| Browser layout/runtime | no horizontal overflow or runtime/request failures |
| TLS | valid ECDSA certificate for apex and `www`; expires 2026-11-10 |
| Renewal | Certbot simulated renewal succeeded; deploy hook reloads valid Nginx config |
| Redirects | HTTP apex, HTTP `www`, and HTTPS `www` redirect to HTTPS apex |
| Security surface | HSTS, CSP, content-type, referrer, and permissions headers present |
| Neighboring sites | four existing HTTPS virtual hosts still returned 200 with valid TLS |

## Release and public edge

The active release is:

```text
/home/stosh99/apps/illinois-lottery-tracker/releases/prod-ac6e3b83dbc0
```

It has its own Python virtual environment and lockfile-built frontend. The atomic
`/home/stosh99/apps/illinois-lottery-tracker/current` symlink selects it. The
pre-promotion target is retained at:

```text
/home/stosh99/apps/illinois-lottery-tracker/rollback-before-public-20260812
```

The permanent process is `illinois-lottery-prod-api.service`. The preserved
`illinois-lottery-shadow-api.service` is disabled. Both use the same loopback port,
so only one may run at a time.

The tracked Nginx bootstrap and final configurations are under `deploy/nginx`. The
active site file is `/etc/nginx/sites-available/illinoislotterytracker.com`, enabled
through `sites-enabled`. Certbot uses the webroot
`/var/www/illinoislotterytracker`, and the tracked deploy hook under
`deploy/certbot` validates and reloads Nginx after a successful renewal.

## Preservation and recovery artifacts

The original archive remains at
`/home/stosh99/projects/IllinoisLotteryTracker/data/raw`. Its verified canonical copy
is `/home/stosh99/illinois-lottery-data/source-captures`. Exact legacy unit copies
remain under `/home/stosh99/.config/illinois-lottery-tracker/rollback/`.

Restore-verified backups:

- `data/backups/pre_environment_split_20260811.dump`
- `data/backups/post_environment_split_dev_20260811.dump`
- `data/backups/post_environment_split_prod_20260811.dump`

Each has a SHA-256 manifest and a disposable-restore verification marker.

## Authentication boundary

Public promotion did not authorize authentication. Production retains
`AUTH_ENABLED=false`, no identity-provider credentials are needed at startup, and
the public session endpoint reports both authentication unavailable and the visitor
unauthenticated. Enabling login remains a separate deployment with the checks in
[deploy/AUTHENTICATION_OPERATIONS.md](../../deploy/AUTHENTICATION_OPERATIONS.md).

## Operational invariant

Never restore development wholesale into production after production may contain
user data. Future source evidence flows through bundles only. A failure in one
importer must remain visible but must not prevent the other importer from being
attempted. Do not delete the previous release, backups, legacy units, or source
archives as part of routine rollback.

See [SHADOW_PRODUCTION_SPEC.md](SHADOW_PRODUCTION_SPEC.md) for the separation design
and [deploy/SYSTEMD_SETUP.md](../../deploy/SYSTEMD_SETUP.md) for live operations and
rollback commands.
