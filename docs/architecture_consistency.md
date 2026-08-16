# Architecture Consistency Migration Plan

Status: **Planning only — no production changes are authorized by this document.**

## Purpose

Restore Illinois Lottery Tracker to the same development and production model used
by MyMediaDashboard.

The intended architecture is:

- the VPS hosts the official production checkout and production application;
- the VPS hosts both the production and shared development databases;
- no development web application runs on the VPS;
- development may occur on any authorized machine configured for the project;
- development machines reach the shared development database through an SSH tunnel;
- production deployment runs from the official project checkout; and
- application secrets remain untracked and environment-specific.

This topology correction must be completed separately from the unfinished UI,
ticket-tracking, schema, and authentication work.

## Target architecture

### VPS

- Official production checkout:
  `/home/stosh99/projects/IllinoisLotteryTracker`
- One production web application
- Production configuration in the project `.env`
- Production database: `illinois_lottery_tracker_prod`
- Shared development database: `illinois_lottery_tracker_dev`
- Required collection and import jobs
- No development web application

### Authorized development machines

- Any authorized Linux, Windows, or other supported machine may be configured for
  development.
- Each machine has its own checkout, virtual environment, and local `.env`.
- Each machine connects to `illinois_lottery_tracker_dev` through the SSH tunnel.
- No development machine receives production database credentials.
- Each machine generates its own `AUTH_SECRET_KEYS` value.
- The Google OAuth client may be shared when all required local callbacks are
  registered.

## Migration constraints

- Do not apply a schema migration during the topology cutover.
- Do not deploy unfinished UI, ticket-tracking, or authentication work as part of
  the topology cutover.
- Do not replace either database.
- Keep Nginx proxying to `127.0.0.1:8766`.
- Keep `AUTH_ENABLED=false` throughout the migration.
- Establish a tested rollback point before every production mutation.
- Never print, commit, log, or place secrets in command arguments.

## Current-state findings

At the time this plan was written:

- live production code runs from release `ac6e3b8`;
- the clean VPS project checkout is at `e52d9c1`;
- the local development checkout is based on `e52d9c1` and contains substantial
  uncommitted UI and authentication work;
- the VPS runs both a production API and a development API;
- the production API runs from `/home/stosh99/apps/illinois-lottery-tracker/current`;
- the VPS project checkout is treated as the development code root;
- the public production service loads an external `production.env`; and
- the project `.env` currently identifies itself as production while pointing to
  the development database and omitting `EXPECTED_DATABASE_NAME`.

The existing project `.env` must not be used to start production until its database
identity is corrected.

## Phase 1 — Establish a clean code baseline

1. Preserve the current local UI and authentication work in a dedicated branch or
   commit series.
2. Do not include that feature work in the topology migration.
3. Create the topology migration from clean revision `e52d9c1`.
4. Make, review, test, and push all deployment changes from an authorized
   development machine before touching production.

### Checkpoint 1 — Code isolation

Proceed only when:

- the current UI and authentication work is safely preserved;
- the topology migration has a clean, identifiable commit;
- the topology migration working tree is clean; and
- migration `0012` and ticket-tracking code are absent from the topology deployment.

## Phase 2 — Capture and back up the current VPS

Create a rollback package containing:

- production and development PostgreSQL dumps;
- restore-verification results for both dumps;
- current production and development environment files;
- the current project `.env`;
- installed systemd unit files;
- current Git revisions;
- the current release-symlink target;
- current enabled and active service and timer states;
- current Nginx configuration; and
- baseline public API and browser results.

Record the following without exposing credentials:

- production database identity;
- development database identity;
- Alembic revision in each database;
- row counts for critical tables;
- latest successful source import; and
- current public data timestamp.

Do not rotate credentials or change database schemas during this phase.

### Checkpoint 2 — Verified rollback

Proceed only when:

- both database dumps restore successfully into disposable databases;
- the existing production service can be restored with its saved unit and external
  `production.env`;
- the current public site passes baseline smoke tests; and
- the rollback procedure is recorded before cutover.

## Phase 3 — Refactor deployment configuration locally

### Production application

Change the production service to run from the official checkout:

```text
WorkingDirectory=/home/stosh99/projects/IllinoisLotteryTracker
ExecStart=/home/stosh99/projects/IllinoisLotteryTracker/.venv/bin/uvicorn ...
```

The production application should load:

```text
/home/stosh99/projects/IllinoisLotteryTracker/.env
```

It should no longer load:

```text
/home/stosh99/.config/illinois-lottery-tracker/production.env
```

To match MyMediaDashboard operationally, the production service may be installed as
a system service running as `stosh99`. Retaining a user service instead must be an
explicitly reviewed decision, not an accidental architectural difference.

### Canonical production `.env`

The canonical VPS project `.env` should contain the following categories of values:

```dotenv
APP_ENV=production
EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod
DATABASE_URL=<production database URL>
DEV_DATABASE_URL=<development database URL>
RAW_DATA_DIR=/home/stosh99/illinois-lottery-data/source-captures

PUBLIC_BASE_URL=https://illinoislotterytracker.com
GOOGLE_OIDC_CLIENT_ID=<verified client ID>
GOOGLE_OIDC_CLIENT_SECRET=<correct value copied directly from Google>
AUTH_SECRET_KEYS=<new, unexposed production key>
AUTH_ENABLED=false
```

`DEV_DATABASE_URL` follows the MyMediaDashboard model. It is inert to the web
application and is available only to controlled import tooling.

The authentication root key previously exposed in conversation must not be reused.

### Data collection and fan-out

Illinois Lottery Tracker must continue updating both databases from the same source
evidence. Refactor the pipeline so:

- there is one application code root: the official project checkout;
- production import uses `DATABASE_URL`;
- development import maps `DEV_DATABASE_URL` internally to `DATABASE_URL`;
- production and development database identity guards remain mandatory;
- the collector subprocess removes both database URLs from its environment;
- the collector remains incapable of reaching either database;
- credentials never appear in command arguments or logs; and
- development and production imports remain independent, so one failure does not
  hide or prevent the other attempt.

The separate `collector.env` can be eliminated by placing its non-secret settings
directly in the collector service definition. The intended result is one canonical,
secret-bearing VPS `.env`.

### Documentation

Replace the current environment-separation instructions with:

- the production deployment procedure;
- remote-development setup;
- new-machine onboarding;
- the database migration rehearsal workflow;
- collection and import operations; and
- rollback instructions.

### Checkpoint 3 — Local validation

Proceed only when tests prove:

- production configuration resolves only the production database;
- development configuration resolves only the development database;
- `APP_ENV=production` with the development database fails closed;
- the collector receives no database credentials;
- fan-out imports the same bundle independently into both databases;
- secrets are absent from logs and command arguments; and
- existing application, API, and frontend tests pass.

## Phase 4 — Validate remote development

Each authorized development machine should use a local configuration equivalent to:

```dotenv
APP_ENV=development
EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev
DATABASE_URL=postgresql+psycopg://<dev-role>:<dev-password>@127.0.0.1:5433/illinois_lottery_tracker_dev

PUBLIC_BASE_URL=http://127.0.0.1:4173
GOOGLE_OIDC_CLIENT_ID=<shared Google client ID>
GOOGLE_OIDC_CLIENT_SECRET=<shared Google client secret>
AUTH_SECRET_KEYS=<unique key for this machine>
AUTH_TRUSTED_PROXY_HOPS=none
```

Validate that:

- the SSH tunnel reaches the development database;
- the application refuses to connect to production;
- migrations can be rehearsed against development;
- Google's local callback works when local authentication is enabled; and
- tests run without production access.

Onboarding documentation must support any authorized development machine. It must
not describe the current 5090 as a permanent architectural dependency.

### Checkpoint 4 — Remote-development independence

Proceed only when a developer checkout can:

- start locally;
- read and write only the development database;
- run its test suite; and
- operate without a development application running on the VPS.

## Phase 5 — Prepare the canonical VPS checkout

1. Confirm `/home/stosh99/projects/IllinoisLotteryTracker` is clean.
2. Pull the approved topology-migration commit.
3. Install locked backend dependencies.
4. Build the frontend.
5. Confirm the production `.env` is mode `0600`.
6. Replace its hybrid database configuration with the production database identity.
7. Correct the manually mistyped Google client secret directly from Google.
8. Generate a new production authentication root key.
9. Keep `AUTH_ENABLED=false`.
10. Confirm the database revision without upgrading it.

A short-lived production candidate may be started on an unused loopback port for
deployment verification. It is not a development service and must be stopped
immediately after testing.

Validate that the candidate:

- connects to `illinois_lottery_tracker_prod`;
- serves rankings and game details;
- reports authentication unavailable;
- does not write unexpected data; and
- serves the intended frontend build.

### Checkpoint 5 — Production candidate

Proceed only when:

- the production checkout is clean at the approved commit;
- the production `.env` points only to the production database;
- the database identity guard passes;
- the candidate smoke test succeeds;
- authentication remains disabled; and
- the existing public service remains available.

## Phase 6 — Controlled cutover

Use a short maintenance window outside the collection timer.

1. Pause the source fan-out timer.
2. Confirm no collection or import process is running.
3. Stop the current release-based production service.
4. Stop and disable the VPS development API permanently.
5. Install or activate the production service pointing to the official project
   checkout.
6. Keep production on `127.0.0.1:8766` so Nginx requires no change.
7. Start the new production service.
8. Verify database identity before public traffic checks.
9. Run loopback smoke tests.
10. Run public HTTPS smoke tests.
11. Activate the revised collector and fan-out service.
12. Re-enable its timer.

Do not:

- apply migration `0012`;
- enable authentication;
- deploy unfinished UI work;
- delete the old release tree; or
- delete the external environment files.

### Checkpoint 6 — Production cutover

Cutover succeeds only when:

- exactly one Illinois web application is running on the VPS;
- no VPS development API is active or enabled;
- production runs from `/home/stosh99/projects/IllinoisLotteryTracker`;
- production connects to `illinois_lottery_tracker_prod`;
- Nginx returns the site and API successfully;
- authentication remains unavailable; and
- neighboring VPS sites are unaffected.

If any check fails, execute rollback immediately.

## Rollback procedure

Because this topology migration must not include schema changes, rollback is:

1. Stop the new production service.
2. Restore the saved release-based service definition.
3. Restore its reference to the external `production.env`.
4. Confirm the `current` symlink still targets the preserved release.
5. Start the previous production service on port `8766`.
6. Verify loopback and public HTTPS.
7. Restore the previous fan-out service only if the replacement had been activated.

The VPS development API is not required to restore public production.

## Phase 7 — Data-pipeline verification

After cutover:

1. Run a controlled collection and fan-out cycle.
2. Confirm the collector has no database URL.
3. Confirm both import attempts are reported independently.
4. Confirm the same source bundle reached both databases.
5. Compare relevant table counts and source-run identities.
6. Confirm the production data timestamp advances normally.
7. Confirm failure in one target remains visible and does not prevent attempting the
   other target.

### Checkpoint 7 — Collection and import

Proceed to cleanup only after:

- one manual fan-out succeeds;
- at least one scheduled fan-out succeeds;
- production and development use the same source evidence; and
- no credentials appear in service logs.

## Phase 8 — Soak period and cleanup

Retain rollback artifacts for at least seven days:

- the old release tree;
- old service definitions;
- old external environment files;
- database backups; and
- previous fan-out configuration.

During the soak period, monitor:

- production uptime;
- collection timer results;
- import results;
- database identity checks;
- the public data timestamp;
- Nginx errors; and
- neighboring VPS sites.

After the soak period and explicit approval:

- remove the obsolete VPS development API unit;
- archive or securely remove obsolete `development.env` and `production.env` files;
- retain only the canonical production `.env` and genuinely necessary non-secret
  collector configuration;
- mark the release-tree deployment documentation obsolete; and
- update the project handoff documentation with the approved architecture.

### Checkpoint 8 — Architecture consistency complete

The migration is complete when:

- the official project checkout is production;
- only the production web application runs on the VPS;
- both databases remain on the VPS;
- development occurs exclusively on authorized external machines through the SSH
  tunnel;
- production deployment follows the MyMediaDashboard workflow; and
- the old release topology is no longer required for rollback.

## Phase 9 — Resume feature and authentication work

Only after the topology has passed its soak period:

1. Finish and commit the current UI and ticket-tracking work.
2. Rehearse migration `0012` against the development database.
3. Test local Google login.
4. Complete privacy, terms, support contact, and authentication release requirements.
5. Back up production.
6. Deploy the approved feature commit.
7. Apply the production migration.
8. Enable production authentication as a separate, reversible configuration change.

This deliberately separates three risks:

1. deployment topology correction;
2. UI and ticket-tracking deployment; and
3. production authentication enablement.
