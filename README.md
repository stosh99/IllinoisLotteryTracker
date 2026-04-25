# IllinoisLotteryTracker

A data-first pipeline that tracks Illinois Lottery instant ticket prize
availability over time. The pipeline collects official source pages nightly,
preserves raw snapshots on disk, and stores structured game/prize data in
PostgreSQL for later trend and expected-value analysis.

UI, HTML parsing, and EV calculations are intentionally **not built yet**.
This repository is the stable foundation for nightly data collection.

See [docs/project-brief.md](docs/project-brief.md) for the longer plan.

## Setup

### 1. Activate the virtual environment

A `.venv` already exists in the project root.

```bash
source .venv/bin/activate
```

### 2. Install the package (editable) with dev extras

```bash
pip install -e ".[dev]"
```

This installs the project from `src/` in editable mode, so
`illinois_lottery_tracker` is importable from anywhere and the scripts in
`scripts/` work without setting `PYTHONPATH`. Use this for normal development.

`requirements.txt` is kept as a flat dependency list (e.g. for CI mirrors or
`pip install -r requirements.txt` outside an editable install), but day-to-day
work should use the editable install above.

### 3. Install the Playwright browser

The raw collector tries `requests` first and falls back to headless Chromium
via Playwright when the origin blocks the request (for example with HTTP 403).
Download the browser binary once per machine:

```bash
playwright install chromium
```

### 4. Create your `.env`

```bash
cp .env.example .env
```

Then edit `.env` and set `DATABASE_URL` to point at your local PostgreSQL
database. `.env` is git-ignored — never commit real credentials.

## Common commands

### Verify the database connection

```bash
python scripts/check_db.py
```

### Create tables (early development only)

```bash
python -c "from illinois_lottery_tracker.db import create_all_tables; create_all_tables()"
```

We will switch to a proper migration tool (e.g. Alembic) before any data we
care about lives in the database.

### Collect a raw snapshot

```bash
python scripts/collect_raw_snapshot.py
```

This fetches the Illinois Lottery unpaid-prizes page, writes the raw HTML to
`data/raw/YYYY-MM-DD/`, and records a `ScrapeRun` + `RawSourceSnapshot` row.
Raw files are never overwritten.

### Run tests

```bash
pytest
```

### Lint

```bash
ruff check .
```

## Project layout

```
src/illinois_lottery_tracker/   # importable package
scripts/                        # CLI entry points
tests/                          # pytest suite (no network, no live DB)
docs/                           # design notes
data/raw/YYYY-MM-DD/            # preserved raw snapshots (git-ignored)
logs/                           # runtime logs (git-ignored)
```

## What is intentionally NOT built yet

- HTML parsing of game/prize tables
- Expected-value math
- Any UI (admin or public)
- Multi-page scraping
- Production scheduling

The current scope is: collect the page, preserve it, and record metadata.
