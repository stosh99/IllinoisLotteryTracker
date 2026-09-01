# IllinoisLotteryTracker

A data-first pipeline that tracks Illinois Lottery instant ticket prize
availability over time. The pipeline collects official source pages nightly,
preserves raw snapshots on disk, parses game/prize data, and stores historical
snapshots in PostgreSQL. It computes versioned tier and strategy analytics,
including a narrow fixed 24-day correction for statistically stable high-prize
tiers. A read-only API and React frontend expose rankings from aligned, fresh
source, catalog, and analytics cutoffs.

The canonical implementation design for the database-centric analytics phase
is [docs/database_blueprint/README.md](docs/database_blueprint/README.md).
Google OIDC authentication and local account/session management are implemented
but deliberately disabled pending a separate public-authentication readiness decision.
Personal play tracking is not built yet.

The canonical public site is [scratchoffdata.com](https://scratchoffdata.com).
Development and production are separated. One database-free collector feeds immutable
evidence bundles to independent databases and importers; Nginx exposes only the
loopback-bound production application over HTTPS.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the current target and
[docs/environment_separation/IMPLEMENTATION_STATUS.md](docs/environment_separation/IMPLEMENTATION_STATUS.md)
for the superseded release-tree state retained as rollback history.
The controlled public-domain cutover and rollback procedure is
[deploy/DOMAIN_MIGRATION.md](deploy/DOMAIN_MIGRATION.md).

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

The raw collector tries `requests` first and falls back to Chromium via
Playwright when the origin blocks the request. The fallback is triggered by
both HTTP 403 and Cloudflare challenge HTML returned with HTTP 200. Download
the bundled browser binary once per machine:

```bash
playwright install chromium
```

For Cloudflare diagnostics, the collector can instead launch the machine's
installed Chrome with a dedicated persistent profile. The profile is separate
from every personal browser profile and is ignored by Git. This command opens
a visible Chrome window, validates both primary source pages, saves the raw
HTML, and performs no database writes:

```bash
python scripts/check_live_chrome_collection.py
```

If Cloudflare presents an interactive prompt, complete it in that dedicated
window. The resulting clearance state remains in
`data/browser-profile/collector` for later collector runs. Never point the
collector at a personal Chrome profile or open the dedicated collector profile
in another Chrome process at the same time.

Do not assume that the persistent profile makes headless Chrome equivalent to
visible Chrome. Cloudflare can still distinguish the modes; require a live
headless diagnostic pass before using `--headless-chrome` in an unattended job.
These diagnostic and manual commands do not install or modify a systemd unit.

For unattended collection, run headed Chrome on an isolated virtual X11
display instead of using Chrome's headless mode:

```bash
xvfb-run --auto-servernum \
  --server-args="-screen 0 1920x1080x24 -nolisten tcp" \
  env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11 \
  .venv/bin/python scripts/check_live_chrome_collection.py \
  --profile-dir data/browser-profile/collector \
  --force-x11
```

After the diagnostic passes, a manual nightly run can opt into the same browser
fallback without changing the installed systemd service:

```bash
python scripts/run_nightly_unpaid_prizes_pipeline.py \
  --chrome-profile-dir data/browser-profile/collector
```

### 4. Create your `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Then edit `.env` and set `DATABASE_URL` to the guarded development database,
normally reached through an SSH tunnel to the VPS. Set `APP_ENV=development`
and `EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev`. Each development
machine keeps its own git-ignored `.env` and authentication root key; never copy
the production `.env` to a development machine or commit real credentials.

See [docs/REMOTE_DEV.md](docs/REMOTE_DEV.md) for the complete workstation setup.
The checkout at `/home/stosh99/projects/IllinoisLotteryTracker` on the VPS is the
production application and must not be used for development work.

## Common commands

### Verify the database connection

```bash
python scripts/check_db.py
```

### Run the read-only API and frontend

Start the API from the project root:

```bash
.venv/bin/uvicorn illinois_lottery_tracker.api:app --reload
```

In another terminal, start the Vite frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend uses `/api/v1/rankings` by default. The endpoint reads the current
status and ranking views in one read-only transaction and returns no rows when
the source, catalog, freshness, or current-analytics checks fail.

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

### Run the split source pipeline

The installed scheduler collects once and fans the same verified bundle out to both
environments. Run it idempotently with:

```bash
sudo systemctl start illinois-lottery-source-fanout.service
```

The VPS keeps its git-ignored canonical production configuration at the project
root `.env`. The collector is deliberately launched without database or
authentication credentials; the fanout passes a least-privilege environment to
each importer. See [deploy/SYSTEMD_SETUP.md](deploy/SYSTEMD_SETUP.md) for status,
comparison, and rollback commands. The command below is the preserved legacy
single-database runner, not the active scheduler:

```bash
python scripts/run_nightly_unpaid_prizes_pipeline.py \
  --skip-if-today-imported --refresh-catalog \
  --backup-dir /explicit/backup/directory \
  --raw-growth-limit-bytes 1073741824
```

The legacy runner acquires a PostgreSQL advisory lock, fetches and validates the Illinois
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
python scripts/report_analytics.py --nightly-status
```

Model 2.0.0 computes every tier in one pass. High tiers above $600 with at least
300 original prizes use the fixed 24-day correction when history is available;
otherwise they use official counts and remain visible. Successful model/cutoff
runs are immutable.

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

cd frontend
npm test
npm run build
npm run test:e2e
```

### Authentication operations

Authentication remains off unless `AUTH_ENABLED=true` passes the strict startup
configuration and schema-readiness checks. Before enabling it publicly, follow
[deploy/AUTHENTICATION_OPERATIONS.md](deploy/AUTHENTICATION_OPERATIONS.md).
Database-only maintenance and operator commands remain usable while login is
disabled:

```bash
python scripts/maintain_authentication.py --dry-run
python scripts/manage_user_account.py --show-user-id <local-user-uuid>
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
frontend/                       # React comparison frontend
docs/                           # design notes
data/raw/YYYY-MM-DD/            # preserved raw snapshots (git-ignored)
logs/                           # runtime logs (git-ignored)
```

## What is intentionally not built yet

- Personal play/outcome tracking
- Personal ticket write APIs

The current implementation remains database-first. Rankings come only from an
exact current source/model cutoff in `current_strategy_rankings_v`. Retained
legacy `game_snapshots.estimated_*` columns are audit-only and must not be used
as publication inputs.
