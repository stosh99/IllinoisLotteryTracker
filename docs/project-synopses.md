# IllinoisLotteryTracker — Project Synopsis

## Project Name

IllinoisLotteryTracker

## Purpose

IllinoisLotteryTracker is a data-first project to track Illinois Lottery instant ticket prize availability over time.

The goal is to collect official Illinois Lottery instant-ticket prize data nightly, preserve raw source snapshots, parse prize data into structured records, store historical snapshots in PostgreSQL, and later calculate estimated expected value and trend metrics.

The project should prioritize trustworthy data collection and historical snapshots before building any public UI.

## Core Product Idea

A successful app will eventually show:

- All Illinois instant lottery ticket games
- Odds of winning anything
- Estimated expected monetary value of each ticket
- Initial prize counts versus currently unclaimed/remaining prize counts
- Which games may have relatively better odds at specific prize levels
- How prize availability changes over time
- Trends by game, prize tier, and ticket price

Important framing:

Expected value should be labeled as estimated. Unclaimed prizes are not exactly the same thing as unsold winning tickets, because some sold winning tickets may not yet have been claimed.

## Build Order

1. Database schema ✅
2. Raw source collection ✅
3. Source discovery ✅
4. Parser ✅
5. Import pipeline ✅
6. Data quality / reconciliation ✅
7. Math / metrics ✅
8. Nightly scheduler (runner built; scheduling pending)
9. Minimal admin / status views
10. Public UI (later)

Do not build the public UI yet.

Trend data is valuable only after nightly snapshot collection is running reliably, so the first major milestone is reliable nightly data collection.

## Completed Milestones (as of 2026-05-10)

### Database schema
- Tables: `scrape_runs`, `raw_source_snapshots`, `games`, `game_snapshots`, `prize_tier_snapshots`
- `games` stores stable per-game metadata: `game_number` (integration key), `name`, `source_url`,
  `ticket_price`, `launch_date`, `end_date`, `overall_odds_one_in`, `est_total_tickets`,
  `top_prize_amount`, `category`, `play_style`, `is_active`
- `game_snapshots` stores per-scrape prize counts and derived metrics (EV fields left null until math step)

### Raw source collection (`raw_collector.py`)
- `collect_raw_snapshot`: fetches a single URL, tries `requests` first, falls back to headless
  Playwright on HTTP 403
- `collect_pages_batch`: reuses a single Playwright browser instance to fetch many pages efficiently
- All fetched HTML is saved to `data/raw/YYYY-MM-DD/` with timestamped filenames

### Source discovery
- Unpaid-prizes page: `https://www.illinoislottery.com/about-the-games/unpaid-instant-games-prizes`
- Instant-ticket hub: `https://www.illinoislottery.com/games-hub/instant-tickets`
  - Hub has 3 paginated pages; discovery follows `<a class="grey-icon">` with text `">"` for next page
  - 58 card entries discovered; 57 unique game numbers (duplicate jurassic-park card on pages 2 and 3)
- `instant_ticket_discovery.py`: `parse_instant_ticket_hub_html` returns `InstantTicketHubDiscoveryResult`

### Parsers
- `parser.py`: parses unpaid-prizes HTML table → `ParseResult` (list of `ParsedGame` / `ParsedPrizeTier`)
- `instant_ticket_detail_parser.py`: parses individual game detail pages → `ParsedInstantTicketDetail`
  - Handles two odds formats: `"1 in X"` and `"X to 1"` (both stored as the 1-in-X denominator)
  - Falls back to `<title>` tag for game name if `<h1 class="cmp-title__text">` is absent
  - Last live run: 57 unique games, 0 warnings

### Import pipeline (`importer.py`)
Two independent import workflows:

1. **Unpaid-prizes snapshot import** (`import_unpaid_prizes_parse_result`)
   - Source: unpaid-prizes page
   - Writes: `games`, `game_snapshots`, `prize_tier_snapshots`
   - Idempotent on `(game_id, scrape_run_id)`; historical snapshots are never overwritten
   - EV fields left null (computed later)

2. **Instant-ticket detail metadata import** (`import_instant_ticket_detail_metadata`)
   - Source: instant-ticket detail pages
   - Writes: `games` only (upsert stable metadata by `game_number`)
   - Never touches `game_snapshots` or `prize_tier_snapshots`
   - Reports name mismatches, price mismatches, duplicate inputs, unsupported fields

CLI scripts:
- `scripts/import_unpaid_prizes_snapshot.py` — import one saved unpaid-prizes HTML file
- `scripts/import_instant_ticket_metadata.py` — import saved detail HTML files
- `scripts/collect_instant_ticket_details.py` — 4-phase pipeline: hub discovery → batch fetch → parse → report

### Data quality / reconciliation (`reconciliation.py`)
- `reconcile(session, detail_inputs=None)` — read-only; never writes to the DB
- Compares unpaid-prizes snapshot coverage vs. detail-metadata coverage using `game_number`
- Proxies: `has_unpaid_snapshot` = game has ≥1 `GameSnapshot`; `has_detail_metadata` = `source_url IS NOT NULL`
- Report includes: matched, unpaid-only, detail-only, missing odds, missing launch date
- With `detail_inputs`: also detects price and name mismatches between fresh-parsed data and DB state
- Without `detail_inputs`: notes the schema limitation in `schema_notes`
- CLI: `scripts/reconcile_instant_ticket_data.py [--details-dir DIR] [--json]`

### Math / metrics (`metrics.py`)
- Pure calculation functions: `estimate_total_tickets`, `estimate_remaining_tickets`,
  `estimate_ev`, `estimate_ev_excluding_top_prize`
- `compute_snapshot_metrics(session)` — idempotent updater; never touches raw observed counts
- Populates `games.est_total_tickets`, `game_snapshots.estimated_tickets_remaining`,
  `game_snapshots.estimated_ev`, `game_snapshots.estimated_ev_excluding_top_prize`
- CLI: `scripts/compute_metrics.py [--dry-run]`

### Nightly pipeline runner (`pipeline.py`)
- `validate_unpaid_prizes_html(content)` — raises `ValidationError` for Cloudflare challenges or
  wrong-page captures before anything touches the DB
- `find_successful_snapshot_run_for_source_date(session, ...)` — DB-backed completion guard for
  retry scheduling; checks successful scrape run, source capture date, game snapshots, and prize tiers
- `run_from_file(session, raw_path, *, min_games, fetch_method)` — validate → parse → import → metrics
  in one call; caller handles commit/rollback (enables dry-run)
- `PipelineResult` — structured summary of every pipeline step and final DB counts
- CLI: `scripts/run_nightly_unpaid_prizes_pipeline.py [--dry-run] [--raw-file PATH] [--min-games N] [--skip-if-today-imported]`
- Fetch path: `--raw-file` skips network fetch (for re-processing or testing); default path calls
  `collect_raw_snapshot()` which tries `requests` first, falls back to Playwright on 403

## Current Technical Direction

Python-first data pipeline. No UI yet.

Current environment:

- Python `.venv` exists
- PostgreSQL is running on the VPS
- Database connection via `DATABASE_URL` in `.env` (not committed)
- Raw source files preserved under `data/raw/YYYY-MM-DD/`
- Historical snapshots are never overwritten

Project name: `IllinoisLotteryTracker`

## Current Scheduling

The unpaid-prizes pipeline is scheduled with a user-level systemd timer. It fires up to four
times each morning. Each run first checks the database for a successful imported snapshot for
the current source date; if one exists, it exits without fetching.

```bash
# systemd timer attempts
03:00
04:00
05:00
06:00

# deployed command includes:
.venv/bin/python scripts/run_nightly_unpaid_prizes_pipeline.py --skip-if-today-imported
```

After reliable nightly data exists for a few weeks, the next milestone is minimal admin/status views.
