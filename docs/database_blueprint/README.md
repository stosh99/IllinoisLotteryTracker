# IllinoisLotteryTracker Database Blueprint

Status: analytics implemented through revision `0010_simplified_high_prize_adjustment`;
overall schema head is authentication hardening revision `0011_defer_auth_event_links`

This directory is the canonical database, ingestion, analytics, validation, and
operations specification.

## Core decisions

1. Official source rows are immutable; estimates live only in versioned derived
   analytics tables.
2. Current unpaid-prizes membership and current retail catalog membership are
   separate facts. Recommendation data uses their mapped intersection.
3. Illinois source dates use `America/Chicago`; stored timestamps are timezone
   aware.
4. Ordinary game progress uses the count-weighted tiers at or below $600.
5. Tiers above $600 with at least 300 original prizes receive one fixed 24-day
   claim-reporting correction.
6. Every other high tier, and every eligible tier lacking history, uses its
   official remaining count and stays visible.
7. Tier probabilities aggregate into explicit strategy datasets with complete
   cutoff/model provenance.
8. Rankings fail closed for incomplete/stale source or catalog data and for a
   missing/failed current analytics run. Optional high-prize adjustment history
   is not a publication gate.

## Document map

1. [Current state and remediation](01_current_state_and_remediation.md)
2. [Analytics specification](02_analytics_specification.md)
3. [Schema and migrations](03_schema_and_migrations.md)
4. [Pipeline, backfill, and operations](04_pipeline_backfill_and_operations.md)
5. [Analytics validation](05_validation_and_backtesting.md)
6. [Strategy datasets](06_strategy_datasets.md)
7. [Implementation work packets](07_implementation_work_packets.md)
8. [Read-only audit SQL](audit_queries.sql)
9. [Implementation status](IMPLEMENTATION_STATUS.md)

## Delivery rule

Missing optional estimation inputs must produce an explicit stored fallback,
not a guessed value and not suppression of otherwise valid source data.
