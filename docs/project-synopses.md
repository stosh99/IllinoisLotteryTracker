# IllinoisLotteryTracker — Project Synopsis

IllinoisLotteryTracker collects Illinois instant-ticket prize data, preserves
immutable source evidence, reconciles the retail catalog, and compares games
with versioned analytics. Public counts are not ticket-level sales data, so
every estimate retains its source cutoff, model version, and parameters.

## Data flow

1. Collect and content-address official unpaid-prizes source files.
2. Validate completeness and persist game/tier snapshots atomically.
3. Refresh and reconcile the retail catalog independently.
4. Compute count-weighted ordinary progress from tiers at or below $600.
5. For tiers above $600 with at least 300 original prizes, subtract the
   estimated claims from the fixed preceding 24-day reporting window.
6. Use official counts for all other high tiers and whenever history is absent.
7. Aggregate explicit player-style strategies and current-cutoff rankings.
8. Expose status/rankings through the read-only API and React frontend.
9. Report source/catalog/analytics/backup freshness and invariant alerts.

## Operations

- Schema: `alembic upgrade head`
- Nightly: `scripts/run_nightly_unpaid_prizes_pipeline.py`
- Analytics: `scripts/compute_analytics.py`
- Backfill: `scripts/backfill_analytics.py --resume`
- Status: `scripts/report_analytics.py --nightly-status`
- Backup/restore: `scripts/backup_database.py` and
  `scripts/verify_database_restore.py`

Nightly source and analytics stages commit independently. Rankings require
fresh complete source/catalog data and a successful model-2.0.0 run for the
same current source cutoff. Missing optional 24-day history never hides a game.
