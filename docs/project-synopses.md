# IllinoisLotteryTracker — Project Synopsis

## Purpose and Scope

IllinoisLotteryTracker is a database-first system for collecting Illinois
instant-ticket prize data, preserving immutable source evidence, and comparing
games with versioned analytics. Public API/UI, login, and personal ticket
tracking remain deliberately out of scope.

Public unclaimed-prize counts are not ticket-level sales data. Every estimate
is labeled and reproducible from a source cutoff, model version, and stored
parameters.

## Implemented Data Flow

1. Collect and content-address official unpaid-prizes source files.
2. Validate completeness and persist normalized game/tier snapshots atomically.
3. Refresh the paginated retail catalog independently and reconcile membership.
4. Compute <=$500 baseline progress and non-circular regular-tier metrics.
5. Calibrate strict >$600 reporting lag with adaptive, top-excluded bands.
6. Score high tiers only when a same-game lagged reference is available.
7. Persist player-style strategy primitives and cutoff-strict ranking views.
8. Walk-forward test 7/14/30-day aligned, no-lag, and legacy variants.
9. Report source/catalog/analytics/backup freshness and explicit alerts.

The $500-$600 interval is a separate retail-gap group. Exactly $500 belongs to
the baseline, exactly $600 belongs to the retail-gap group, and high tiers are
strictly greater than $600.

## Current Validation Finding

The latest descriptive calibration has nine positive primary games and a
roughly 24-day median lag. That does not establish predictive value. The paired
walk-forward backtest found the lag-aligned high-tier model worse than no-lag
on currently eligible horizons and had no eligible aligned 30-day sample, so
the promotion gate correctly fails. The outputs remain fully auditable in
storage, model version 1.0.0 is explicitly rejected, and no current ranking
view publishes them.

## Operations

- Schema: `alembic upgrade head`
- Nightly: `scripts/run_nightly_unpaid_prizes_pipeline.py`
- Backfill: `scripts/backfill_analytics.py --resume`
- Current status: `scripts/report_analytics.py --nightly-status`
- Model validation: `scripts/backtest_analytics.py --report-json`
- Backup/restore: `scripts/backup_database.py` and
  `scripts/verify_database_restore.py`

Nightly collection uses a PostgreSQL advisory lock. Source and analytics stages
commit independently, and canonical current views return no analytics when the
latest source cutoff has not been successfully computed by the active model.
Systemd source dates and schedules use `America/Chicago`; stored timestamps are
timezone-aware.

## Legacy Transition

The mutable `games.est_total_tickets` and `game_snapshots.estimated_*` fields
remain only for one release-cycle audit. Nightly no longer writes them, current
reports/rankings do not read them, and database comments identify their
versioned replacements. The archived comparison is
`database_blueprint/legacy_comparison_1.0.0_2026-08-08.md`.
