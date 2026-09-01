# Remote development

Development runs on authorized external machines. The VPS hosts the shared
development database but no development application.

## Safety boundary

- Development database: `illinois_lottery_tracker_dev`
- Production database: `illinois_lottery_tracker_prod`
- PostgreSQL is reached through an SSH tunnel to VPS loopback.
- Development machines receive only the `lottery_dev` credential.
- `APP_ENV`, `EXPECTED_DATABASE_NAME`, and the URL database must agree.
- Never copy the production database URL or production root key to a dev machine.

## One-time setup

### 1. Clone and install

```bash
git clone git@github.com:stosh99/IllinoisLotteryTracker.git
cd IllinoisLotteryTracker
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
npm --prefix frontend ci
```

Install Playwright's Chrome requirements as appropriate for the machine before
running browser tests.

### 2. Configure the SSH tunnel

One tunnel reaches the complete PostgreSQL instance, so it may be shared with other
projects on the VPS. Choose an unused local port. `5433` is the conventional
example; the current Linux development machine uses `55432`.

Example `~/.ssh/config` entry:

```sshconfig
Host media-db
    HostName 66.220.29.98
    User stosh99
    LocalForward 5433 127.0.0.1:5432
    ServerAliveInterval 30
    ServerAliveCountMax 2
    ExitOnForwardFailure yes
```

Start it with:

```bash
ssh -N media-db
```

Use `-f` only when another supervisor will monitor and restart the tunnel.

On Windows, use the supervised tunnel pattern from MediaDashboard's
`tools/tunnel-supervisor.ps1`. Windows OpenSSH requires restrictive ACLs on the
SSH config and private key; remove inherited access granted to other users.

### 3. Create the development `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Set values equivalent to:

```dotenv
APP_ENV=development
EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev
DATABASE_URL=postgresql+psycopg://lottery_dev:<dev-password>@127.0.0.1:5433/illinois_lottery_tracker_dev
RAW_DATA_DIR=data/raw

AUTH_ENABLED=false
PUBLIC_BASE_URL=http://127.0.0.1:4173
GOOGLE_OIDC_CLIENT_ID=<shared development-capable client ID>
GOOGLE_OIDC_CLIENT_SECRET=<shared client secret>
AUTH_SECRET_KEYS=<unique key generated on this machine>
AUTH_TRUSTED_PROXY_HOPS=none
```

If a different local tunnel port is used, change only the URL port. Generate a
machine-local root key with:

```bash
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Do not send the output through chat, email, or source control.

### 4. Verify database identity

```bash
.venv/bin/python scripts/check_db.py
.venv/bin/alembic current
```

Confirm the reported database is exactly `illinois_lottery_tracker_dev`. Also test
the guard before relying on the setup: a production `EXPECTED_DATABASE_NAME` paired
with the development URL must fail closed.

## Run locally

Start the API:

```bash
.venv/bin/uvicorn illinois_lottery_tracker.api:app --host 127.0.0.1 --port 8765 --reload
```

Create `frontend/.env.local` with:

```dotenv
VITE_API_PROXY_TARGET=http://127.0.0.1:8765
```

Then start Vite:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173`.

## Test and migration workflow

```bash
.venv/bin/ruff check .
AUTH_ENABLED=false .venv/bin/pytest
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Rehearse new migrations against development first:

```bash
.venv/bin/alembic current
.venv/bin/alembic upgrade head
```

Before migrating, confirm `APP_ENV=development`,
`EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev`, and the URL database name.
Production migration happens later as an explicit deploy step with a verified
backup.

## Adding another development machine

Repeat the clone, dependency, tunnel, and local `.env` setup. Reuse only the
development database credential and approved OAuth client. Generate a new local
`AUTH_SECRET_KEYS` value for every machine. No VPS application service is needed.
