# A1 remote-development verification

Date: 2026-08-16

Machine: stoshai 5090 development workstation

Topology branch: `topology-cutover` at `b44a4cc`

## Scope

This checkpoint verified the external-development model described in
`04_MIGRATION_RUNBOOK.md`. It made no production application, production database,
VPS checkout, systemd, Nginx, or fanout changes.

## Configuration and tunnel

| Check | Result |
|---|---|
| Local `.env` permissions | `0600`, owned by `stoshai` |
| `APP_ENV` | `development` |
| Expected database | `illinois_lottery_tracker_dev` |
| URL database | `illinois_lottery_tracker_dev` |
| URL endpoint | `127.0.0.1:55432` |
| Authentication | disabled |
| Local tunnel listener | owned by `ssh`, bound to `127.0.0.1:55432` |
| Connected database role | `lottery_dev` |

No production database URL or production role is present on the development
machine. Credential values were not printed or recorded.

## Database safety

- `scripts/check_db.py` connected successfully and reported
  `illinois_lottery_tracker_dev` as role `lottery_dev`.
- A temporary table was created, written, read, and automatically dropped in
  `illinois_lottery_tracker_dev`, proving the development role can write without
  leaving application data behind.
- Overriding the process to `APP_ENV=production` and
  `EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod` while retaining the
  development URL failed before connection with an identity mismatch.
- A live attempt against production was intentionally not made: production
  credentials do not belong on a development machine. Unit tests cover the
  symmetric URL/expected-name mismatch behavior.

## Local application

- Uvicorn started on `127.0.0.1:8765` from `topology-cutover`.
- `GET /api/v1/rankings` returned HTTP 200 with current, available development
  analytics.
- `GET /api/v1/auth/session` returned HTTP 200 with authentication unavailable and
  no authenticated user, as required for Track A.
- Vite started locally and served the Illinois Lottery Tracker root document. Ports
  4173 and 4174 were already occupied by existing local Node listeners, so this
  isolated verification used 4175 and did not stop or modify those processes.

## Migration rehearsal

The clean workspace was temporarily switched to `main`, because migration `0012`
is deliberately excluded from `topology-cutover`.

- Repository head: `0012_user_ticket_entries`
- Development database revision: `0012_user_ticket_entries (head)`
- `alembic upgrade head`: successful, idempotent no-op
- Workspace returned to `topology-cutover` immediately afterward

## Test evidence

Track A0 validation on the same topology code completed before this checkpoint:

- Ruff: passed
- Backend: 578 passed, 31 skipped because `TEST_DATABASE_URL` was not configured
- Frontend unit tests: 76 passed
- Frontend production build: passed
- Playwright desktop/mobile: 20 passed
- Focused topology and credential-boundary tests: 13 passed

## Checkpoint result

**A1 passed.** The 5090 can run the project externally through an SSH tunnel using
development-only configuration; database identity fails closed; local API and
frontend startup work; and the development schema is at its intended head.

The next phase, A2, is production-side backup and rollback-state capture. It requires
separate owner authorization before any VPS or production action begins.
