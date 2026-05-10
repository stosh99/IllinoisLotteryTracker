# Codex Interim Work

> **Status (2026-05-09):** This document covers only the unpaid-prizes import
> phase. The project has since added instant-ticket hub discovery, detail
> metadata parsing/import, and a read-only reconciliation workflow. See
> `docs/project-synopses.md` for the full current state.

## Scope

This note documents the unpaid-prizes database import work added in parallel
with the instant-ticket discovery/detail parsing work.

It does not cover instant-ticket hub discovery, instant-ticket detail parsing,
or Claude prompt files.

## Added Import Layer

New module:

```text
src/illinois_lottery_tracker/importer.py
```

Primary entry point:

```python
import_unpaid_prizes_parse_result(session, parse_result, *, scrape_run, captured_at=None)
```

The importer takes the existing unpaid-prizes parser output,
`parser.ParseResult`, and persists it into the current SQLAlchemy schema.

It does not:

- fetch the network
- parse instant-ticket detail pages
- calculate EV
- build UI
- create migrations

## Database Behavior

Games are matched by `Game.game_number`.

For each parsed game with a `game_number`, the importer:

- creates or updates `Game`
- sets `Game.name`
- sets `Game.ticket_price`
- marks `Game.is_active = True`
- creates one `GameSnapshot` for the supplied `ScrapeRun`
- creates `PrizeTierSnapshot` rows for parsed prize tiers

Snapshot totals are populated from parsed prize tiers:

- `total_original_prize_value`
- `total_remaining_prize_value`
- `total_original_winning_tickets`
- `total_remaining_winning_tickets`
- `top_prizes_original`
- `top_prizes_remaining`
- `weeks_in_market`

Prize tier rows populate:

- `prize_amount`
- `original_count`
- `remaining_count`
- `claimed_count`

EV fields are intentionally left null.

## Idempotency

Idempotency is scoped to the existing schema constraint:

```text
(game_id, scrape_run_id)
```

If a `GameSnapshot` already exists for a game and scrape run, the importer
leaves that snapshot and its prize tiers untouched and reports it as skipped.

This preserves historical snapshots and avoids overwriting prior import
history for the same scrape run.

## Parser Warnings And Import Issues

Parser warnings are returned on the import result without crashing the import.

Parsed games without `game_number` are skipped and returned as import issues.

Prize tiers without `prize_amount` are skipped and returned as import issues.

## CLI

New script:

```text
scripts/import_unpaid_prizes_snapshot.py
```

Usage:

```bash
python scripts/import_unpaid_prizes_snapshot.py path/to/unpaid-prizes.html
python scripts/import_unpaid_prizes_snapshot.py path/to/unpaid-prizes.html --dry-run
python scripts/import_unpaid_prizes_snapshot.py path/to/unpaid-prizes.html --scrape-run-id 123
```

The CLI parses a saved unpaid-prizes HTML file and imports it into the database.
It does not fetch live data.

If `--scrape-run-id` is omitted, the script creates a success `ScrapeRun`
pointing at the supplied raw file path.

`--dry-run` stages the import and rolls back instead of committing.

## Tests

New tests:

```text
tests/test_importer.py
```

Coverage includes:

- importing one parsed game with multiple prize tiers
- repeat import idempotency for the same scrape run
- duplicate game names with different game numbers
- parser warnings returned without crashing
- parsed games missing `game_number` being skipped and reported

Tests use in-memory SQLite and do not require PostgreSQL or network access.

## Validation

Commands run:

```bash
.venv/bin/pytest tests/test_importer.py
.venv/bin/pytest
.venv/bin/ruff check .
```

Results:

```text
tests/test_importer.py: 5 passed
full test suite: 116 passed
ruff: all checks passed
```

## Schema Notes

No migration system exists in the repository yet. This work uses the current
SQLAlchemy models directly.

`weeks_in_market` is stored on `game_snapshots` because it is observed on the
unpaid-prizes page at snapshot time and changes over time.

There is no migration framework in the repository yet. For an existing
database, apply this SQL before importing snapshots with this model version:

```sql
ALTER TABLE game_snapshots
ADD COLUMN weeks_in_market INTEGER;
```

The instant-ticket detail metadata importer stores stable parsed metadata on
`games`. For an existing database, also apply:

```sql
ALTER TABLE games
ADD COLUMN category VARCHAR(128);

ALTER TABLE games
ADD COLUMN play_style VARCHAR(128);
```

Instant-ticket detail fields currently stored on `games`:

- `source_url`
- `ticket_price`
- `launch_date`
- `overall_odds_one_in`
- `top_prize_amount`
- `category`
- `play_style`

Parsed detail fields intentionally not stored yet because the schema has no
columns for them:

- `overall_odds_text`
- `image_url`
- `play_instructions`
- `consolidated_odds_present`
- `raw_fields`

Before relying on production historical data, the project should add an
explicit migration path, such as Alembic.

## Addendum: Subsequent Work (not covered above)

### Instant-ticket detail metadata import

Added to `importer.py`:

```python
import_instant_ticket_detail_metadata(session, details, *, create_missing_games=True)
```

- Upserts stable metadata onto `games` only (no snapshots created)
- Matches by `game_number`
- Reports name mismatches, price mismatches, duplicate inputs, and unsupported fields
- CLI: `scripts/import_instant_ticket_metadata.py`

### Instant-ticket hub discovery and batch fetch

- `instant_ticket_discovery.py`: parses hub pages, follows pagination
- Hub has 3 pages; 58 card entries; 57 unique game numbers (duplicate
  jurassic-park card on pages 2 and 3 — source issue, not a parser bug)
- `collect_pages_batch` in `raw_collector.py` reuses a single Playwright
  browser session for all 57 detail page fetches
- CLI: `scripts/collect_instant_ticket_details.py`

### Reconciliation

Read-only workflow comparing the two data sources by `game_number`:

- `src/illinois_lottery_tracker/reconciliation.py` — `reconcile()` function
- Proxies: `has_unpaid_snapshot` = game has ≥1 `GameSnapshot`;
  `has_detail_metadata` = `games.source_url IS NOT NULL`
- With `detail_inputs`: also detects price/name mismatches vs. DB state
- CLI: `scripts/reconcile_instant_ticket_data.py [--details-dir DIR] [--json]`
- Never writes to the database
