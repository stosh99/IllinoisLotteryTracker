# A4 production topology cutover verification

Date: 2026-08-16

Execution location: 5090 development workstation, using bounded SSH commands

Cutover branch and revision: `topology-cutover` at `959a79d`

## Scope

This checkpoint performed the production topology cutover approved in phase A4.
It replaced the release-based user service with the tracked system-level production
service, permanently disabled the VPS development API, and replaced the user-level
fanout timer with the tracked system-level fanout units.

It did not change Nginx, migrate either database, enable authentication, run a
manual fanout, deploy ticket-tracking feature work, or remove any rollback artifact.

## Cutover sequence

1. Revalidated the A2 database dumps and rollback archive, the official checkout,
   tracked units, production database identity, Nginx, and the public sites.
2. Disabled and stopped the user-level fanout timer, then confirmed that no
   collection or import process was running.
3. Disabled and stopped the user-level production and development APIs. Ports 8765
   and 8766 were confirmed closed before installing the replacement.
4. Installed and enabled the tracked system-level production service.
5. Verified database identity and revision before completing the public checks.
6. Installed the tracked system-level fanout service and timer, enabled the timer,
   and confirmed that the old user timer remained disabled.
7. Performed a final process, port, unit, database, public-site, and rollback audit.

The SSH alias briefly failed local name resolution before step 3. Those failed
connections never reached the VPS and made no changes; the remaining bounded SSH
commands used the documented VPS address directly.

## Final service topology

| Item | Verified result |
|---|---|
| Production API | system unit, active and enabled |
| Unit user | `stosh99` |
| Working directory | `/home/stosh99/projects/IllinoisLotteryTracker` |
| Listener | one Uvicorn process on `127.0.0.1:8766` |
| VPS development API | user unit inactive and disabled; no system unit |
| Development listener | no listener on 8765 |
| Candidate listener | no listener on 8767 |
| System fanout timer | active and enabled |
| System fanout service | inactive between scheduled runs, as expected |
| Old user fanout timer | inactive and disabled |

The exact installed production service, fanout service, and fanout timer files
byte-match the tracked files in `deploy/systemd/`. The final process audit found
exactly one command containing the Lottery ASGI application, owned by `stosh99` and
running from the official checkout with proxy headers trusted only from
`127.0.0.1`.

The system timer is configured for 03:00, 04:00, 05:00, and 06:00
`America/Chicago`, with up to five minutes of jitter. At the checkpoint its next
displayed trigger was `2026-08-17 04:00:05 EDT`, equivalent to 03:00:05 CDT on the
VPS's `America/New_York` display timezone. Enabling it did not start a fanout;
the service and all collection/import processes remained inactive.

## Database and data integrity

The production service passed the fail-closed identity guard:

```text
database=illinois_lottery_tracker_prod
role=lottery_prod
revision=0011_defer_auth_event_links (head)
```

All 20 recorded production table counts exactly match the A2 production manifest.
The comparison included the 77 games, 5,478 game snapshots, 70,403 prize-tier
snapshots, all analytics tables, and all zero-row authentication tables. Production
was not upgraded to migration `0012`.

The canonical project `.env` remains owned by `stosh99:stosh99` with mode `0600`.
Its contents were not printed during A4.

## Application and edge verification

Loopback checks passed:

- root: HTTP 200;
- rankings: HTTP 200 with 442 rows;
- game 36 detail: HTTP 200;
- game 36 history: HTTP 200; and
- authentication session: HTTP 200, unavailable and unauthenticated.

Public checks passed:

- site root, rankings, and authentication session: HTTP 200;
- built JavaScript asset: HTTP 200, 316,907 bytes;
- HSTS, CSP, `nosniff`, and the expected security headers: present;
- Nginx configuration test: passed; and
- no recent production-service or Lottery Nginx errors.

A real browser render returned the title `Illinois Lottery Tracker`, rendered the
expected topology-branch heading, and produced zero console errors. The older
heading is intentional: player-focused UI and ticket-tracking feature work remain
outside this topology cutover.

Authentication remains disabled:

```json
{"authenticationAvailable":false,"authenticated":false,"user":null,"session":null,"csrfToken":null}
```

The Lottery site and all four neighboring sites returned HTTP 200:

- `illinoislotterytracker.com`
- `baseball-unlimited.com`
- `budraft2026.com`
- `invoicetimetracker.com`
- `mymediadashboard.com`

## Rollback preservation

The old release pointer still resolves to
`/home/stosh99/apps/illinois-lottery-tracker/releases/prod-ac6e3b83dbc0`; that
checkout remains clean at `ac6e3b83dbc0`. The old user unit files and external
`production.env`, `development.env`, and `collector.env` files remain in place.

All protected A2 artifacts still match their recorded SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| Production dump | `e3dc39f98b8dc8ecaf973c87de20504144395ba69f89c9504d2d6e57de447fa2` |
| Development dump | `734b3506d3c4b7c2e673231e53c42430ce757875f23c4b5282c695a8ed0df660` |
| Rollback archive | `6f58f0a4a0fe4c6c5141bf2ee3390580108829eb17f77231b8daf090656abc8d` |

These artifacts, the old release, and the retired configuration must remain for at
least the seven-day soak and may be removed only with explicit owner approval.

## Checkpoint result

**A4 passed.** Exactly one Lottery web application runs on the VPS; it is the
system-level production service from the official checkout and it uses only the
production database. No VPS development API is active, enabled, installed at the
system level, or listening. The system fanout timer is installed and waiting, the
old user timer is retired, Nginx and the public application are healthy,
authentication remains unavailable, and all neighboring sites are unaffected.

The next phase is A5. It requires a separately authorized manual fanout, followed
by verification that one source bundle reaches both databases independently and
that a scheduled fanout also succeeds without credentials appearing in logs.
