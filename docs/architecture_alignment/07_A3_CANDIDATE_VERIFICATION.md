# A3 production candidate verification

Date: 2026-08-16

Execution location: 5090 development workstation, using bounded SSH commands

Candidate branch and revision: `topology-cutover` at `95692c0`

## Scope

This checkpoint staged and smoke-tested the topology candidate from the official
VPS checkout. It did not restart or replace the live release service, migrate either
real database, enable authentication, install system units, change Nginx, run the
fanout, or expose the candidate publicly.

## Preflight

- Official checkout was clean on `main` at `4b7a6c6` before staging.
- Live release was clean and detached at `ac6e3b8`.
- User-level production API, development API, and fanout timer were active.
- Ports 8765 and 8766 were occupied by the expected development and production
  Uvicorn processes.
- Candidate loopback port 8767 was unused.
- Public Lottery returned HTTP 200.

## Canonical production environment

The pre-A3 project-root `.env` still named the development database, omitted
`EXPECTED_DATABASE_NAME`, omitted fanout development variables, and did not
explicitly disable authentication. Its protected A2 copy remains available for
rollback.

The canonical project-root `.env` was assembled atomically, remains mode `0600`,
and now contains these categories:

- production application identity and guarded `lottery_prod` database URL;
- separately named guarded development fanout URL for `lottery_dev`;
- canonical source-capture directory;
- public origin and Google OAuth client values;
- a newly generated independent production root key;
- `AUTH_ENABLED=false`; and
- `AUTH_TRUSTED_PROXY_HOPS=none`.

No password, OAuth secret, or root key appeared in command arguments or output. The
5090 values were streamed over SSH stdin. Hash-only comparison confirmed both VPS
OAuth values now match the 5090. Offline authentication validation passed with one
valid root key and no trusted forwarding networks, while the stored enable flag
remained false.

Database validation reported:

```text
production:  APP_ENV=production
             expected/url/actual=illinois_lottery_tracker_prod
             role=lottery_prod
development fanout: APP_ENV=development
                    expected/url=illinois_lottery_tracker_dev
                    role=lottery_dev
```

Both fanout importer environments set `ILT_DISABLE_DOTENV=true`; neither can
silently reload the canonical file after receiving its least-privilege target.

## Candidate staging and build

The inert official checkout fetched and switched to the tracking branch
`origin/topology-cutover` at `95692c0`. Backend editable installation completed,
frontend `npm ci` completed with zero reported vulnerabilities, and the production
frontend build succeeded.

The checkout remained clean after the build. Production Alembic state was
`0011_defer_auth_event_links (head)` for this topology-only branch. No upgrade
command was run.

## Isolated candidate

The candidate ran temporarily from the official checkout on
`127.0.0.1:8767`, with proxy headers trusted only from `127.0.0.1`. It was not a
systemd service and Nginx did not route traffic to it.

API and asset checks passed:

- rankings: live/available, 442 ranking rows;
- candidate rankings exactly matched the live 8766 response after removing only
  the response-generation timestamp;
- game 36 detail: HTTP 200 with three prize tiers;
- game 36 history: HTTP 200 with 96 sales points and three tier series;
- authentication session: unavailable, unauthenticated, no user/session;
- built JavaScript asset: HTTP 200, 316,907 bytes; and
- HSTS, CSP, no-sniff, and referrer-policy production headers were present.

A real headless Chrome render returned:

| Check | Result |
|---|---|
| HTTP status | 200 |
| Title | `Illinois Lottery Tracker` |
| Primary heading | `Compare the prize pool. Keep the caveats.` |
| Browser console errors | 0 |

The heading is expected for this topology-only revision. Player-focused UI and
ticket-tracking commit `68680c4` remain deliberately excluded until Track C.

## Candidate cleanup

Closing the initiating SSH session did not stop the temporary Uvicorn candidate.
The final port audit detected the remaining listener. Before taking action, its
owner, PID, full command, official-checkout working directory, and port 8767 were
confirmed. `SIGTERM` was sent only to that exact candidate process. A subsequent
socket check confirmed port 8767 is closed.

No candidate service or unit exists.

## Post-candidate verification

- Production and development user services: active.
- Fanout timer: active.
- Only the expected 8765 and 8766 listeners remain.
- Production database: `illinois_lottery_tracker_prod` as `lottery_prod`.
- Production revision: `0011_defer_auth_event_links (head)`.
- All production table row counts exactly match the A2 production manifest.
- Authentication: unavailable and unauthenticated.
- Official checkout: clean on `topology-cutover`, matching its remote branch.
- Live release: clean and unchanged at `ac6e3b8`.
- Lottery and all four neighboring public sites: HTTP 200.

## Checkpoint result

**A3 passed.** The candidate uses only the production database, serves the intended
topology-only application and frontend, preserves authentication-disabled behavior,
writes no application data, and leaves the existing public service unaffected.

The next phase is A4, the actual production topology cutover. A4 pauses fanout,
stops the release-based production and VPS development services, installs and starts
the new system-level production/fanout units, and performs loopback/public/neighbor
verification. A4 requires separate explicit owner authorization and must roll back
immediately on any failed cutover check.
