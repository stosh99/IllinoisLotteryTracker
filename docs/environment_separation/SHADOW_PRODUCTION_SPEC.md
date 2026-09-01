# Development / shadow-production separation

> **Superseded topology.** This is the historical shadow-production design. The
> current target has one production application in the official VPS checkout and
> no VPS development application. See [DEPLOYMENT.md](../DEPLOYMENT.md) and
> [SYSTEMD_SETUP.md](../../deploy/SYSTEMD_SETUP.md) for current operations.

Status: historical specification for the shadow phase completed on 2026-08-11.
The current public-production state and rollback boundary are recorded in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Scope and safety boundary

This phase creates independently configured development and production databases,
application processes, and import runs. Production remains a loopback-only shadow:
there is no DNS, reverse-proxy, firewall, TLS, or public-port change, and
`AUTH_ENABLED=false` in both environments.

The existing `illinois_lottery_tracker_dev` database, `data/raw` archive,
`illinois-lottery-nightly.timer`, and its installed unit files remain the rollback
path until all shadow checks pass. No source file is moved or deleted. The old timer
is disabled only after a saved-bundle import and a live collection/import have both
been verified in development and production. If live collection is blocked, the old
timer stays enabled.

Because this work is intentionally uncommitted, the shadow release is an immutable
staged copy identified by its base Git commit and a SHA-256 of the uncommitted diff.
It is not eligible for public promotion. A later reviewed commit is required before
a durable production release can be called Git-pinned.

## Fixed names and locations

| Purpose | Value |
| --- | --- |
| Development database | `illinois_lottery_tracker_dev` |
| Development database login | `lottery_dev` |
| Production database | `illinois_lottery_tracker_prod` |
| Production database login | `lottery_prod` |
| Canonical source archive | `/home/stosh99/illinois-lottery-data/source-captures` |
| Collector browser profile | `/home/stosh99/illinois-lottery-data/browser-profile/collector` |
| Operator configuration | `/home/stosh99/.config/illinois-lottery-tracker` |
| Shadow releases | `/home/stosh99/apps/illinois-lottery-tracker/releases` |
| Development API | `127.0.0.1:8765` |
| Shadow-production API/site | `127.0.0.1:8766` |

The canonical archive is copied from the existing archive and byte/hash verified.
The original archive remains in place. Historical database rows may continue to
refer to it during shadow operation; all new imports refer to files in the canonical
archive.

## Environment identity guard

Every API, database CLI, importer, backup, and online migration uses:

- `APP_ENV=development|production|test`
- `EXPECTED_DATABASE_NAME=<exact PostgreSQL database name>`
- `DATABASE_URL=<environment-specific credential and database>`

An actual `SELECT current_database()` must equal `EXPECTED_DATABASE_NAME` before
application work proceeds. `APP_ENV=production` without an expected database name
fails closed. Alembic applies the same check online and compares the URL target in
offline mode. This prevents a production process from silently operating on the
development database (or the reverse).

## One collection, two independent imports

The collector has no database URL. It writes immutable, content-addressed HTML and
then atomically publishes a versioned JSON source-bundle manifest. A manifest is
complete only when the unpaid-prizes page and the full, validated catalog crawl are
present and each file's size and SHA-256 match.

The dispatcher starts the development and production importers as independent
subprocesses using separate configuration files and separate code roots. Both are
attempted even when one fails. The final result reports each outcome and is nonzero
if either failed. Database-level advisory locks serialize imports within each
database; a filesystem lock serializes access to the one collector/browser profile.

Bundle imports are idempotent. Duplicate unpaid-prizes evidence reuses the existing
successful run, catalog persistence already deduplicates its manifest, and analytics
is computed or reused for the identified source run.

## Database creation and data policy

Immediately before separation, create and restore-verify a fresh backup of the
current database. Create the production database with a new randomly generated
credential, restore that verified dump once, and run migrations/audits/tests against
the restored production database. Never clone development into production again
after production may contain user data.

Authentication tables may exist from migrations, but authentication remains disabled
and all user/authentication tables must contain zero rows during shadow verification.

## Services and scheduler cutover

Permanent user services replace the transient development API and add the shadow API.
Both bind only to loopback. The shadow service runs the built frontend from its staged
release. The collector timer retains the existing Illinois schedule (03:00 through
06:00 America/Chicago with jitter and persistence).

Cutover order:

1. Preserve and record the currently installed legacy units and timer status.
2. Verify backup restoration and create the isolated production database.
3. Import one saved source bundle into both databases and compare invariant results.
4. Start both loopback APIs and verify rankings/game detail/history plus disabled auth.
5. Run one live collection and import its same bundle into both databases.
6. Only after steps 1-5 pass, enable the split timer and disable (do not delete) the
   legacy timer.

## Rollback

Before cutover, rollback is simply stopping the new services; the old database,
archive, API command, and timer are unchanged. After scheduler cutover, disable the
split timer and re-enable `illinois-lottery-nightly.timer`. The production database,
release, configuration, copied archive, and verified backup are retained for
diagnosis; rollback never deletes them.
