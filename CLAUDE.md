# Illinois Lottery Tracker — Project Guide

## Production boundary — read this first

`/home/stosh99/projects/IllinoisLotteryTracker` on the VPS is the production
deployment checkout. Do not develop, edit files, run an IDE/agent session, or test
feature code there. The only normal VPS checkout operations are deploy, migration,
service operation, collection/import operation, backup, and read-only inspection.

All development happens on an authorized external machine against
`illinois_lottery_tracker_dev` through an SSH tunnel. Production uses
`illinois_lottery_tracker_prod`. Never place production database credentials on a
development machine.

## Architecture

- Public site: `https://illinoislotterytracker.com`
- Production checkout: `/home/stosh99/projects/IllinoisLotteryTracker`
- Production API: system-level `illinois-lottery-prod-api.service`, loopback port
  `8766`, proxied only by Nginx
- Source pipeline: system-level `illinois-lottery-source-fanout.timer` and service
- Production database: `illinois_lottery_tracker_prod`, role `lottery_prod`
- Shared remote-development database: `illinois_lottery_tracker_dev`, role
  `lottery_dev`
- Canonical source archive:
  `/home/stosh99/illinois-lottery-data/source-captures`
- Collector browser profile:
  `/home/stosh99/illinois-lottery-data/browser-profile/collector`

Exactly one Illinois Lottery Tracker web application runs on the VPS, and it is
production. The development database is fed by the same immutable source bundle as
production, but there is no development API or frontend process on the VPS.

## Database identity guard

Every database-using process must provide:

- `APP_ENV=development|production|test`
- `EXPECTED_DATABASE_NAME=<exact database name>`
- `DATABASE_URL=<matching URL>`

Production without `EXPECTED_DATABASE_NAME` fails closed. The URL database name
and `SELECT current_database()` must both match. Preserve this guard in application
startup, Alembic, scripts, tests, and future services.

## Configuration and secrets

- VPS production configuration: project-root `.env`, mode `0600`, gitignored
- Development configuration: each development machine's local `.env`, mode `0600`
- `.env.example` contains placeholders only
- Never print environment files, credentials, OAuth codes, cookies, or database URLs
  containing passwords
- Each development machine generates its own `AUTH_SECRET_KEYS`
- Production has an independent `AUTH_SECRET_KEYS`

The VPS production `.env` also contains `DEV_DATABASE_URL` and
`DEV_EXPECTED_DATABASE_NAME` for the fanout importer. Those variables are inert to
the web application. The collector subprocess explicitly strips both database URLs
and sets `ILT_DISABLE_DOTENV=true` before collecting.

## Source collection and fanout

The collector publishes one immutable, content-addressed source bundle. Two
independent importer subprocesses then import that same bundle into development and
production using the single production checkout as their code root.

Required invariants:

- collection has no database credentials;
- dev and prod import identities are independently guarded;
- both imports are attempted even if one fails;
- credentials never appear in argv or logs; and
- a published bundle is replayable and hash-verifiable.

## Development workflow

See `docs/REMOTE_DEV.md` for onboarding and tunnel setup.

Normal workflow:

1. Develop and test on an external machine.
2. Rehearse migrations against `illinois_lottery_tracker_dev`.
3. Commit and push to GitHub.
4. On the VPS, require a clean checkout and pull the reviewed commit.
5. Back up production before risky migrations.
6. Build the frontend, install changed dependencies, apply an explicitly intended
   migration, restart, and verify.

Never use the production checkout as a convenient development workspace.

## Production deployment

See `docs/DEPLOYMENT.md` and `deploy/SYSTEMD_SETUP.md`. A normal deploy is:

```bash
cd /home/stosh99/projects/IllinoisLotteryTracker
git status --short --branch
git pull --ff-only
.venv/bin/pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/alembic current
# Run `alembic upgrade head` only when that migration is explicitly part of the deploy.
sudo systemctl restart illinois-lottery-prod-api.service
```

Do not combine topology changes, feature/schema deployment, and authentication
enablement. They are separate risks with separate verification and rollback.

## Authentication boundary

Production authentication remains disabled until the release gate in
`deploy/AUTHENTICATION_OPERATIONS.md` is complete and the owner explicitly enables
it. Never infer authorization to set `AUTH_ENABLED=true` from a schema migration or
OAuth credential setup.

## Tests and quality checks

From the project root:

```bash
.venv/bin/ruff check .
AUTH_ENABLED=false .venv/bin/pytest
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

PostgreSQL integration tests require the dedicated guarded test database when it is
available. Do not point destructive tests at development or production.

## Repository conventions

- `CLAUDE.md` is the canonical project guide.
- `AGENTS.md` must remain a real symlink to `CLAUDE.md`.
- Infrastructure configuration is tracked under `deploy/`.
- Architecture and implementation records live under `docs/`.
- Superseded architecture documents must be marked clearly rather than silently
  deleted.
- Use `rg`/`rg --files` for repository search.
- Preserve unrelated user changes in a dirty worktree.
