# IllinoisLotteryTracker

A data-first pipeline that tracks Illinois Lottery instant ticket prize
availability over time. The pipeline collects official source pages nightly,
preserves raw snapshots on disk, parses game/prize data, and stores historical
snapshots in PostgreSQL. It computes versioned non-circular tier analytics,
claim-lag calibration, strategy datasets, and auditable backtests.

The canonical implementation design for the database-centric analytics phase
is [docs/database_blueprint/README.md](docs/database_blueprint/README.md).
No public UI, API, authentication, or personal play tracking is in the current
scope.

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
chmod 600 .env
```

Then edit `.env` and set `DATABASE_URL` to point at your local PostgreSQL
database. `.env` is git-ignored — never commit real credentials.

## Common commands

### Verify the database connection

```bash
python scripts/check_db.py
```

### Create or upgrade the schema

```bash
alembic upgrade head
```

For a new empty database, this creates the complete schema. An existing
pre-Alembic database must first be backed up and verified, then stamped at the
baseline only after its schema has been compared with revision `0001`:

```bash
python scripts/backup_database.py \
  --target-dir /explicit/backup/directory --name pre_alembic
python scripts/verify_database_restore.py \
  --dump /explicit/backup/directory/pre_alembic.dump \
  --target-database illinois_lottery_restore_verify_pre_alembic \
  --upgrade-legacy-baseline
alembic stamp 0001_existing_schema_baseline
alembic upgrade head
```

Never stamp a nonempty database merely to make Alembic accept it. Restore the
backup into a disposable database and run the schema and audit checks first.

### Run the nightly pipeline manually

```bash
python scripts/run_nightly_unpaid_prizes_pipeline.py \
  --skip-if-today-imported --refresh-catalog \
  --backup-dir /explicit/backup/directory \
  --raw-growth-limit-bytes 1073741824
```

This acquires a PostgreSQL advisory lock, fetches and validates the Illinois
Lottery unpaid-prizes page without an open transaction, preserves the raw
capture, commits normalized source snapshots, and computes the matching
versioned analytics in a separate transaction. The optional catalog refresh is
also collected without an open transaction and committed independently. A
failed analytics stage never rolls back source history or silently exposes an
older analytics cutoff.

### Compute, backfill, validate, and report analytics

```bash
python scripts/compute_analytics.py
python scripts/backfill_analytics.py --resume
python scripts/backtest_analytics.py --report-json
python scripts/report_analytics.py --nightly-status
```

Analytics are never made current merely because a version number is newest.
Only an explicitly approved model with a persisted passing promotion backtest
can publish. Inspect or change model state with:

```bash
python scripts/manage_model_approval.py
python scripts/manage_model_approval.py --approve \
  --backtest-run-id ID --reason "reviewed passing promotion report"
```

Approval without a passing backtest is rejected by both the application and
PostgreSQL. A failed promotion backtest automatically rejects the model.

If the live catalog is temporarily blocked but a complete raw crawl was
already preserved, replay the ordered files without network access:

```bash
python scripts/import_catalog_files.py page-001.html page-002.html page-003.html
```

The historical `compute_metrics.py --legacy` and `report_metrics.py` surface
uses the superseded all-reported-winner denominator. Nightly does not write
those retained transition columns, and the legacy report command is disabled.

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
tests/                          # unit plus disposable-PostgreSQL integration tests
docs/                           # design notes
data/raw/YYYY-MM-DD/            # preserved raw snapshots (git-ignored)
logs/                           # runtime logs (git-ignored)
```

## What is intentionally NOT built

- Public API or UI
- Authentication and user accounts
- Personal play/outcome tracking

The current implementation remains database-first. Rankings come only from an
exact current source/model cutoff in `current_strategy_rankings_v`. Retained
legacy `game_snapshots.estimated_*` columns are audit-only and must not be used
as publication inputs.
