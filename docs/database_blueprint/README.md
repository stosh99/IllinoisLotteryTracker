# IllinoisLotteryTracker Database Blueprint

Status: implemented, post-review remediated, and validated through revision `0008`

Design cutoff: 2026-08-08
Scope owner: the database, ingestion pipeline, analytical engine, validation,
and database-facing reports

## Authority and Scope

This directory is the canonical implementation specification for the next
database-centric phase of IllinoisLotteryTracker. When a formula or database
instruction here conflicts with an older project note or with the provisional
metric code, this blueprint wins.

The blueprint includes:

- source-data integrity and current-game semantics;
- Alembic migrations and PostgreSQL constraints;
- the count-weighted `<= $500` game-progress proxy;
- non-circular per-tier availability and odds;
- calibration of the relative reporting lag for prizes strictly above `$600`;
- date-aligned high-tier availability and odds;
- confidence, lumpiness, and data-quality classifications;
- versioned derived tables and current-result views;
- strategy datasets for later player-style rankings;
- walk-forward validation and model-promotion gates;
- nightly computation, backfills, reports, backups, and operational checks;
- ordered work packets for a lower-effort implementation agent.

The blueprint explicitly excludes:

- an API or public website;
- frontend tabs, styling, or navigation;
- authentication;
- user accounts or personal play records;
- using future user-entered outcomes in the official-data model.

## Core Decisions

1. Raw source counts remain immutable. Derived estimates live in versioned
   analytics tables, never in the raw tier rows.
2. Current prize reporting and current retail catalog membership are separate
   facts. Analytics retain games in the newest complete unpaid-prizes snapshot;
   recommendation datasets require presence in both that snapshot and the
   newest complete instant-ticket catalog snapshot. `games.is_active` is not
   authoritative for either fact.
3. Illinois source dates use `America/Chicago`; timestamps remain UTC
   `timestamptz` values.
4. Game progress is the count-weighted claimed fraction of tiers with prize
   amounts `<= $500`.
5. A tier in that baseline is evaluated with a leave-one-tier-out baseline.
6. Tiers from `$500.01` through `$600.00` use the current full baseline and no
   large-claim lag. Tiers strictly above `$600` use a lagged baseline.
7. A high-tier calibration band is selected per game using original winner
   counts, not a universal dollar ceiling. The top tier is never used for lag
   calibration.
8. Primary lag calibration requires at least 500 original winners in the
   adaptive band; 250 is exploratory only.
9. The lag used to score a game excludes that game from calibration whenever
   enough other calibration games exist.
10. Top tiers may be scored, but never calibrate lag and normally receive a
    lumpy/low-confidence label.
11. Player-style datasets sum independently estimated tier probabilities.
    They do not use an opaque composite score in version 1.
12. Existing `game_snapshots.estimated_*` values are legacy estimates and are
    not product-ranking inputs after the new model is available.
13. Retailer cash availability receives no separate correction. Any stable
    low-tier timing effect is already part of the empirically measured relative
    lag.

## Document Map

1. [Current state and remediation](01_current_state_and_remediation.md)
2. [Canonical analytical specification](02_analytics_specification.md)
3. [Schema and migration design](03_schema_and_migrations.md)
4. [Pipeline, backfill, and operations](04_pipeline_backfill_and_operations.md)
5. [Validation and backtesting](05_validation_and_backtesting.md)
6. [Player-style database datasets](06_strategy_datasets.md)
7. [Implementation work packets](07_implementation_work_packets.md)
8. [Read-only audit SQL](audit_queries.sql)
9. [Implementation and remediation status](IMPLEMENTATION_STATUS.md)

## Baseline Audit Snapshot

The design was checked against the live development database at the cutoff
above:

| Item | Verified value |
|---|---:|
| PostgreSQL database size | 20 MB |
| Games ever observed | 75 |
| Successful imported source runs | 90 |
| Game snapshots | 5,128 |
| Prize-tier snapshots | 65,911 |
| Games in latest complete source snapshot | 57 |
| Prize tiers in latest complete source snapshot | 738 |
| Unique games in latest stored catalog crawl | 53 |
| Stored source days | 90 |
| Source range | 2026-05-09 through 2026-08-08 |
| Missing source dates inside that range | 2026-05-14, 2026-07-23 |
| Unit tests | 365 passing |

All snapshot rollups reconcile to their tier rows. No negative counts,
remaining-above-original counts, claimed-count discrepancies, prize-structure
changes, or remaining-count reversals were found. These clean invariants are
preconditions for the analytical design, not reasons to omit database
constraints.

The latest stored catalog and unpaid-prizes lists are not identical. The
blueprint therefore preserves `prize_source_current` and `catalog_current`
separately and uses their mapped intersection for recommendation eligibility.

## Delivery Rule

Design globally; implement incrementally. Implementation agents should take
one work packet at a time from `07_implementation_work_packets.md`, satisfy its
specific success criteria, and stop. No agent should improvise a replacement
formula when a required input is missing; it should persist an explicit status
and reason instead.
