# A2 production backup and rollback verification

Date: 2026-08-16

Execution location: 5090 development workstation, using bounded SSH commands

VPS: `stosh`

## Scope

This checkpoint captured the live pre-cutover state and created restore-verified
backups of both Illinois Lottery databases. It did not change the production or
development application, either real database, systemd configuration, Nginx,
repository checkout, release pointer, schema, fanout timer, or authentication
setting.

## Pre-cutover application state

| Item | Captured value |
|---|---|
| Official checkout | `/home/stosh99/projects/IllinoisLotteryTracker` |
| Official checkout revision | `4b7a6c6` (`main`, clean, matches `origin/main`) |
| Live release pointer | `/home/stosh99/apps/illinois-lottery-tracker/releases/prod-ac6e3b83dbc0` |
| Live release revision | `ac6e3b8`, detached and clean |
| Production service | user unit, active and enabled, loopback port 8766 |
| Development service | user unit, active and enabled, loopback port 8765 |
| Fanout timer | user unit, active and enabled |
| Fanout service | inactive between scheduled runs |
| Replacement system units | not installed |

The live service is already running from the exact release tree retained for
rollback. Its unit, environment, release symlink, and Nginx configuration were
captured before any cutover work.

## Baseline health

- Nginx configuration test: passed.
- Production loopback root and rankings: HTTP 200.
- Public Lottery root and rankings: HTTP 200.
- Loopback and public authentication session: authentication unavailable and no
  authenticated user.
- Neighboring HTTPS sites returned HTTP 200:

  - `baseball-unlimited.com`
  - `budraft2026.com`
  - `invoicetimetracker.com`
  - `mymediadashboard.com`

Both production and development APIs reported the same available data state:

| Field | Value |
|---|---|
| Source observed | `2026-08-16T07:04:42-04:00` |
| Catalog observed | `2026-08-16T07:04:53.482647-04:00` |
| Source run | 107 |
| Catalog run | 108 |
| Analytics run | 187 |
| Model | `2.0.0` |

## Backup artifacts

Protected VPS directory:

```text
/home/stosh99/projects/IllinoisLotteryTracker/data/backups/a2_topology_20260816
```

The directory is gitignored. Dumps, manifests, verification markers, configuration
copies, and the rollback archive are owned by `stosh99`; sensitive files are mode
`0600`, and protected directories are mode `0700`.

| Database | Recorded revision | Bytes | SHA-256 | Restore verified |
|---|---|---:|---|---|
| `illinois_lottery_tracker_prod` | `0011_defer_auth_event_links` | 9,563,568 | `e3dc39f98b8dc8ecaf973c87de20504144395ba69f89c9504d2d6e57de447fa2` | Yes |
| `illinois_lottery_tracker_dev` | `0012_user_ticket_entries` | 9,568,020 | `734b3506d3c4b7c2e673231e53c42430ce757875f23c4b5282c695a8ed0df660` | Yes |

Production was backed up at `2026-08-16T14:50:36Z` and verified at
`2026-08-16T14:54:48Z`. Development was backed up at `2026-08-16T14:50:40Z` and
verified at `2026-08-16T14:55:20Z`.

## Critical row counts

The two manifests agree on all shared tables:

| Table or area | Count |
|---|---:|
| Games | 77 |
| Scrape runs | 104 |
| Raw source snapshots | 120 |
| Game snapshots | 5,478 |
| Prize-tier snapshots | 70,403 |
| Catalog snapshots | 424 |
| Analytics runs | 96 |
| Analytics game metrics | 5,478 |
| Analytics strategy metrics | 5,478 |
| Analytics tier metrics | 70,403 |
| Users, identities, sessions, login attempts, auth events | 0 each |

Development alone contains the additive `user_ticket_entries` table from migration
`0012`; it has zero rows. Production remains at `0011` and was not migrated.

## Restore verification

Each custom-format dump was checksum-validated, restored into a strictly named
disposable database, compared with its manifest revision and row counts, audited,
and exercised by the PostgreSQL test suite. Both final verification runs passed and
automatically dropped their disposable databases.

Production verification preserved least privilege:

1. The `lottery_prod` role refused `CREATE DATABASE`, as intended; its privileges
   were not changed.
2. The existing development verification role created the isolated production
   restore.
3. The production dump was first verified at its recorded `0011` revision and its
   recorded row counts.
4. Only the disposable restore was then upgraded to `0012` so the current checkout
   could run its audits and PostgreSQL tests. The real production database remained
   at `0011`.
5. `EXPECTED_DATABASE_NAME` was empty only inside the disposable verifier's test
   process because two tests create additional uniquely named databases. The
   verifier itself fixed and validated the exact target URL, database name,
   checksum, recorded revision, and row counts.

One nested disposable test database remained after an intermediate failed test run.
Its exact name and `lottery_dev` ownership were verified, then it was explicitly
dropped. It contained only temporary test data. A final catalog check confirmed no
A2 or nested migration-test databases remain.

## Rollback configuration archive

`rollback-state/` contains protected copies of:

- the project-root `.env` and three existing external environment files;
- the installed production, development, fanout service, and fanout timer user
  units;
- previously retained legacy rollback units;
- the current release symlink;
- `nginx.conf`, the Lottery site configuration, and the enabled-site symlink.

The copies byte-match their sources. The consolidated archive is:

```text
rollback-state.tar.gz
SHA-256 6f58f0a4a0fe4c6c5141bf2ee3390580108829eb17f77231b8daf090656abc8d
```

Environment contents were never printed, logged, or copied to the development
machine.

## Rollback path

If a later topology cutover fails:

1. Stop and disable the replacement system-level production and fanout units.
2. Restore the captured user-level unit files and external environment files.
3. Confirm `current` targets `prod-ac6e3b83dbc0` at revision `ac6e3b8`.
4. Start the captured user-level production service on `127.0.0.1:8766`.
5. Restore the captured fanout service/timer if it had been replaced.
6. Verify database identity, loopback endpoints, public HTTPS, authentication
   unavailable, and all four neighboring sites.

The database dumps and rollback artifacts must be retained for at least seven days
after a successful cutover and removed only with explicit owner approval.

## Checkpoint result

**A2 passed.** Both database dumps restore successfully, the current release-based
service is healthy and fully captured, the rollback procedure is concrete, all
baseline checks pass, and no disposable resources remain.

The next phase is A3: stage `topology-cutover` in the official checkout, construct
the canonical production `.env`, build the candidate, and smoke-test it on an unused
loopback port without migrating production or enabling authentication. A3 requires
separate owner authorization.
