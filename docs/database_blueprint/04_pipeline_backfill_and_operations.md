# Pipeline, Backfill, and Operations

## Nightly sequence

1. Acquire the project advisory lock.
2. Collect and validate the official unpaid-prizes page without holding a
   database transaction.
3. Preserve the raw capture and commit a complete normalized source snapshot.
4. Refresh the catalog independently when requested.
5. Compute model-2.0.0 analytics in one separate transaction.
6. Emit source, catalog, analytics, quality, archive, and protection status.

An analytics failure never rolls back official source history. It creates a
failed analytics run for that cutoff; current ranking views do not substitute
an older cutoff.

## One-pass analytics

For each current game, the analytics stage loads cutoff-strict history,
computes ordinary progress, obtains the optional 24-day reference, scores every
tier, aggregates strategies, and marks the run successful. No nightly fitting
or statistical promotion process occurs.

## Backfill

```text
scripts/backfill_analytics.py
  --model-version 2.0.0
  --from-source-date YYYY-MM-DD
  --to-source-date YYYY-MM-DD
  --resume
  --dry-run
```

Backfill processes source cutoffs in observed-time order and commits each
cutoff independently. Successful model/cutoff pairs are immutable and skipped;
failed pairs may be resumed.

## Command surface

```text
scripts/check_db.py
scripts/audit_source_data.py
scripts/run_nightly_unpaid_prizes_pipeline.py
scripts/compute_analytics.py
scripts/backfill_analytics.py
scripts/report_analytics.py
scripts/backup_database.py
scripts/verify_database_restore.py
```

## Freshness

Source and catalog age are calculated independently from observed timestamps.
At 36 hours status becomes a warning; after 72 hours ranking status is stale and
unavailable. These integrity/freshness rules are separate from optional
high-prize correction history.

## Monitoring

Nightly status includes source/catalog identity and age, game/tier counts,
reconciliation counts, invariant failures, model/cutoff, complete/partial/
unavailable analytics counts, adjusted high-tier count, high tiers using the
official fallback, quality issues, stage durations, raw-archive growth, backup
age, and last verified restore age.

## Deployment of revision 0010

1. Verify a pre-migration backup restore.
2. Apply Alembic revision 0010.
3. Run a full model-2.0.0 historical backfill.
4. Run database audits and focused/PostgreSQL tests.
5. Confirm current ranking status and API cutoff provenance.
6. Verify a post-migration backup restore.
