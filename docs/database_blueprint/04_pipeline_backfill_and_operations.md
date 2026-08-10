# Pipeline, Backfill, and Operations

## Nightly State Machine

The nightly job is one orchestrated workflow with separately committed stages.
Network work must not hold a database transaction open.

### Stage 0 — acquire lock

Acquire a PostgreSQL advisory lock using a project-specific constant before
checking today's state. If the lock is held, exit zero with `already_running`.
Release it on every exit path.

This closes the race between multiple systemd attempts that currently check
and fetch independently.

### Stage 1 — collect and validate outside a transaction

1. Determine Chicago source date.
2. Skip only when a complete successful source run already exists for that
   date and a manual `--force` was not supplied.
3. Fetch one unpaid-prizes file.
4. Compute SHA-256 before writing a second physical copy.
5. Validate page markers and parse into memory.
6. Run absolute and previous-complete-run checks from
   `01_current_state_and_remediation.md`.

If validation fails, create a short failed/quarantined run record with the raw
file provenance, but insert no game/tier snapshots and do not change current
membership.

### Stage 2 — import observed data atomically

In one transaction:

1. create/finalize the source run with canonical source time/date/hash;
2. insert its raw source row;
3. upsert stable game metadata;
4. insert game and tier snapshots;
5. compute snapshot rollups and structure fingerprints;
6. verify database constraints and tier/rollup reconciliation;
7. set parsed counts and `is_complete`;
8. synchronize `games.is_active` as a compatibility cache based on this
   complete run;
9. commit.

If any observed-data step fails, roll back the complete source transaction.
The previous complete snapshot remains current.

### Stage 2b — refresh the retail catalog

Collect the paginated instant-ticket hub once per Chicago day as one
`instant_ticket_catalog` workflow run. Persist every page raw hash and every
unique card/URL. Map known URLs from `games.source_url` without detail fetch;
fetch details only for unknown/ambiguous cards. Commit catalog membership in a
separate transaction so a catalog failure cannot roll back prize history.

Tier analytics may proceed if this stage fails, but recommendation ranking
views use the newest complete catalog only. If that catalog exceeds its
freshness threshold, rankings are unavailable with `CATALOG_STALE` rather than
assuming every unpaid-prizes game is still offered.

### Stage 3 — compute versioned analytics

In a separate analytics execution:

1. create/retry the `analytics_runs` row for the new source cutoff;
2. validate all current game inputs;
3. build progress and tier metrics;
4. calibrate lag from history available at the cutoff;
5. score high tiers and lag sensitivity;
6. aggregate strategy metrics;
7. persist quality issues;
8. check publication gates;
9. set run `success` and `publishable=true` atomically.

If analytics fail, preserve the source import and mark analytics failed. The
current analytics views deliberately return no row for the new source cutoff;
reports must say `analytics pending/failed`, not silently show yesterday as
today.

### Stage 4 — reports and maintenance

Run read-only status reports, update logs, and perform scheduled metadata/raw
maintenance. A reporting failure does not roll back source or analytics rows.

## Source Freshness

Store and report age from `source_observed_at`:

| Age | State |
|---|---|
| `<= 36 hours` | fresh |
| `> 36 and <= 72 hours` | stale warning |
| `> 72 hours` | stale error; current rankings not publishable |

The thresholds are model parameters. Source date is Chicago time; elapsed age
uses UTC timestamps.

Apply the same age bands independently to the unpaid-prizes source and the
catalog. Both must be fresh for recommendation rankings.

## Historical Backfill

Backfill is explicit and resumable:

```text
scripts/backfill_analytics.py
  --model-version 1.0.0
  --from-source-date YYYY-MM-DD
  --to-source-date YYYY-MM-DD
  --resume
  --dry-run
```

Rules:

- process complete source runs in ascending source time;
- commit one analytics run at a time;
- skip an already successful `(model version, source run)` pair;
- retry failed rows only with `--resume` or `--force`;
- never use observations after the as-of run for progress, lag, or scoring;
- write a final attempted/success/failed/skipped summary;
- return nonzero if any requested cutoff failed.

The first implementation may backfill only cutoffs that have enough prior
history for the requested metric. It still creates explicit unavailable
statuses rather than inventing a reference.

## Metadata Collection Redesign

Metadata is supporting input, not part of the daily prize-count transaction.

### Trigger conditions

Run targeted metadata discovery when:

- a current game is new;
- a current game lacks overall odds, launch date, category, or detail URL and
  its retry time has arrived;
- a weekly full metadata refresh is due;
- an operator requests `--force`.

### Candidate matching

Parse and persist hub cards first. Normalize names by case-folding, Unicode normalization,
punctuation removal, whitespace collapse, and standard handling of currency
symbols. Match a missing game by normalized name plus ticket price. Fetch only
unique/plausible detail candidates; ambiguous candidates remain an explicit
issue.

### Retry state

Persist per-game metadata attempt fields or a dedicated attempt table:

- last attempted time;
- outcome code;
- candidate URL;
- attempt count;
- next retry time;
- last error.

Use backoff of 1, 3, 7, and then 30 days. A known missing page is not crawled
57 times every morning.

## Raw-File Storage and Retention

Raw preservation remains mandatory, but physical duplication is not.

### Storage rules

- content hash is calculated before final placement;
- identical content uses one content-addressed blob or a hard link plus
  per-capture metadata;
- file extension records compression (`.html.gz` or `.html.zst`);
- database provenance always resolves to an existing blob;
- compression or deduplication never changes the recorded original SHA-256;
- any maintenance command supports `--dry-run` and writes a manifest.

### Retention classes

| Source | Retention |
|---|---|
| Unpaid-prizes snapshots used for game/tier history | indefinite |
| Hub pages | keep changes plus latest 90 days; deduplicate unchanged content |
| Detail pages | keep first, every changed version, and latest; unchanged duplicates may be deduplicated after 90 days |
| Invalid/Cloudflare captures | keep 30 days unless attached to an incident |

No deletion command is implemented before raw storage has its own backup and a
restore test.

## Database Backups

The database is small enough for simple logical backups.

### Required command behavior

Create a script that:

1. resolves an explicit backup directory, never `$HOME`, `~`, or `/`;
2. runs `pg_dump --format=custom --no-owner`;
3. calculates a SHA-256 manifest;
4. records database name, migration revision, timestamp, size, and row counts;
5. writes atomically through a temporary file;
6. refuses to overwrite an existing backup;
7. applies retention only after a successful new backup.

Recommended retention:

- 7 daily;
- 4 weekly;
- 12 monthly.

### Restore verification

At least monthly:

1. create an explicitly named disposable database;
2. restore the newest custom dump;
3. run Alembic/current-schema verification;
4. run `audit_queries.sql` and database integration smoke tests;
5. compare source and analytics row counts;
6. drop only the validated disposable database name.

A backup without a tested restore is not considered operational protection.

For a pre-Alembic backup, restore verification requires the explicit
`--upgrade-legacy-baseline` flag. The verifier creates a second disposable
revision-0001 database, compares the restored legacy schema to it exactly, and
only then stamps/upgrades the disposable restore. It never stamps the source
database.

## Database Security

- Change `.env` permissions to `600`.
- Use a runtime database role with only required DML privileges.
- Use a separate migration/owner role for DDL.
- Do not print `DATABASE_URL` or credentials in logs.
- Parameterize every query.
- Read-only reports should use a read-only transaction or reporting role.
- Backup files inherit restrictive permissions and never enter the repository.

## Performance and Index Maintenance

At current size, correctness matters more than premature materialization. Use
the indexes in the schema design and verify with `EXPLAIN (ANALYZE, BUFFERS)`
for:

- newest complete source selection;
- current game/tier joins;
- one game's ordered progress history;
- lag calibration input scan;
- current strategy ranking by ticket price.

Acceptance targets on the development database, with a warm cache:

- current game/tier dataset under 250 ms;
- one-game 90-day history under 100 ms;
- current ranking view under 250 ms;
- complete nightly analytics under 60 seconds at current scale;
- full 90-cutoff analytics backfill under 15 minutes.

These are regression guards, not reasons to denormalize raw source tables.
Rely on PostgreSQL autovacuum/analyze initially; add manual maintenance only
when measured evidence requires it.

## Database-Facing Commands

The target command surface is:

```text
scripts/check_db.py                         # connectivity
scripts/audit_source_data.py                # invariant/quality audit
scripts/run_nightly_unpaid_prizes_pipeline.py
scripts/compute_analytics.py                # one cutoff
scripts/backfill_analytics.py               # historical/resumable
scripts/calibrate_claim_lag.py              # read-only or persisted run section
scripts/report_analytics.py                 # game/tier/strategy/status
scripts/backtest_analytics.py               # walk-forward validation
scripts/backup_database.py                  # logical backup + manifest
scripts/verify_database_restore.py           # restored-DB checks
```

All mutating commands support `--dry-run` when meaningful. Every command has
help tests, stable nonzero error exits, concise summaries, and no network
access unless its purpose explicitly includes collection.

## Monitoring and Alerts

The nightly summary must contain:

- source time/date/hash and source age;
- catalog time/manifest hash, age, mapped/unmapped count, and reconciliation
  counts;
- parsed/current game and tier counts;
- additions/removals versus previous complete source;
- quality issue counts by severity/code;
- metadata misses;
- analytics model version and cutoff;
- lag status, qualified game count, median, and bootstrap interval;
- scored/partial/unavailable game and tier counts;
- total duration by stage;
- backup age and last verified restore age.

Alert/error conditions include:

- no fresh complete source by 08:00 America/Chicago;
- source count below completeness gates;
- any rollup mismatch or count reversal;
- analytics cutoff not matching latest complete source;
- lag calibration unexpectedly unavailable after previously being available;
- backup older than 36 hours;
- restore verification older than 35 days;
- raw archive growth beyond a configurable monthly threshold.
