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

1. Database schema
2. Raw snapshot collection
3. Parser
4. Import pipeline
5. Math/metrics
6. Nightly scheduler
7. Minimal admin/status views
8. Public UI later

## Important principles

- Preserve raw source files
- Do not overwrite history
- Make parser testable with fixtures
- Treat expected value as estimated
- Avoid polished UI until data pipeline is stable
