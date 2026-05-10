# IllinoisLotteryTracker

Goal: Track Illinois Lottery instant ticket prize availability over time.

## Primary purpose

- Collect official Illinois Lottery instant ticket prize data nightly
- Preserve raw source snapshots
- Parse prize data into structured records
- Store game and prize tier snapshots in PostgreSQL
- Calculate estimated EV and related metrics
- Build UI later after enough trend data exists

## Initial priorities

1. Database schema ✅
2. Raw snapshot collection ✅
3. Source discovery ✅
4. Parser ✅
5. Import pipeline ✅
6. Data quality / reconciliation ✅
7. Math/metrics (next)
8. Nightly scheduler
9. Minimal admin/status views
10. Public UI later

Two import workflows are complete:
- Unpaid-prizes snapshot import (games, game_snapshots, prize_tier_snapshots)
- Instant-ticket hub discovery and detail metadata import (games only)

Reconciliation compares coverage between the two sources by game_number and is read-only.

## Important principles

- Preserve raw source files
- Do not overwrite history
- Make parser testable with fixtures
- Treat expected value as estimated
- Avoid polished UI until data pipeline is stable
