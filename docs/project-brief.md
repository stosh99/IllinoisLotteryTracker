# IllinoisLotteryTracker

Goal: Track Illinois Lottery instant-ticket prize availability over time using
auditable source history and versioned analytics.

## Primary purpose

- Collect official Illinois Lottery instant ticket prize data nightly
- Preserve raw source snapshots
- Parse prize data into structured records
- Store game and prize tier snapshots in PostgreSQL
- Calculate non-circular tier probabilities, EV, and player-style rankings
- Validate the claim-lag hypothesis with cutoff-strict walk-forward tests
- Build UI later after enough trend data exists

## Initial priorities

1. Database schema ✅
2. Raw snapshot collection ✅
3. Source discovery ✅
4. Parser ✅
5. Import pipeline ✅
6. Data quality / reconciliation ✅
7. Versioned math/metrics ✅
8. Nightly scheduler/orchestration ✅
9. Database status/reporting ✅
10. Public UI later

The database-centric implementation is complete through the blueprint release
gate. It includes:

- Alembic migrations, logical backup/verified restore tooling, and CI;
- immutable source/catalog provenance and current-membership views;
- a <=$500 baseline, $500-$600 retail gap, and strict >$600 high-tier model;
- adaptive lag calibration, strategy datasets, backtesting, and promotion
  gates;
- advisory-locked nightly stages, resumable backfill, and status alerts.

Two source workflows are complete:
- Unpaid-prizes snapshot import (games, game_snapshots, prize_tier_snapshots)
- Instant-ticket hub discovery and detail metadata import (games only)

Reconciliation compares coverage between the two sources by game_number and is read-only.

The observed roughly 24-day descriptive lag is not currently promoted for
predictive ranking: paired walk-forward validation performed worse than the
no-lag comparator. Results remain stored as auditable evidence, model version
1.0.0 is rejected, and its rankings are not publishable.

## Important principles

- Preserve raw source files
- Do not overwrite history
- Make parser testable with fixtures
- Treat expected value as estimated
- Never equate unclaimed prizes with unsold tickets
- Never expose analytics from an older cutoff as current
- Avoid polished UI until data pipeline is stable
