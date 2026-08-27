# Backup operations

The production database is backed up nightly on the VPS, pruned to a
daily/weekly/monthly lifecycle, copied off the VPS to the operator workstation,
and restore-verified weekly. Nothing here is provider-dependent: ServerOptima
snapshots (if any) are a complement, never the plan, because a hypervisor image
is crash-consistent rather than transactionally consistent and lives with the
same provider as the server it protects.

## What runs, and when

| Unit | Schedule | Action |
|---|---|---|
| `illinois-lottery-backup.timer` | 07:30 America/Chicago daily | `backup_database.py` writes a dump + manifest into `~/illinois-lottery-data/backups`, then `prune_backups.py` applies retention |
| `illinois-lottery-restore-verify.timer` | Sundays 08:00 America/Chicago | Restores the newest dump into a disposable database, verifies it, writes a verification marker |
| `pull-backups.sh` (workstation cron) | twice daily | Pulls new dumps to `~/backups/scratchoffdata` and checksums the newest |

07:30 is chosen so each dump captures that morning's completed collection
(the collector runs 03:00–06:10) without competing with it for I/O.

Retention is **7 daily, 4 weekly, 12 monthly** — the lifecycle the privacy
notice commits to. At roughly 10 MB per dump the whole set stays well under a
gigabyte. The newest dump is retained unconditionally, and a dump whose
manifest cannot be read is never pruned, because its age cannot be established.

## Why the offsite copy is a pull

`deploy/offsite/pull-backups.sh` runs on the workstation and pulls over SSH.
The VPS holds no credentials for the offsite location, so a compromised or
destroyed VPS cannot reach, encrypt, or delete the offsite copies. `rsync
--ignore-existing` keeps already-pulled dumps immutable locally even if the
remote copy is later pruned, and each run re-syncs whatever is missing, so a
workstation that was powered off catches up on its next run.

## Monitoring

`analytics/status.py` scans the backup directory's `*.manifest.json` files:
`created_at` from `backup_database.py` yields `backup_age_hours`, and
`verified_at` from the restore-verification marker yields
`last_verified_restore_age_days`. Stale or missing values raise
`BACKUP_STALE_OR_UNKNOWN` and `RESTORE_VERIFICATION_STALE_OR_UNKNOWN`.

Check the current picture at any time:

```bash
.venv/bin/python scripts/report_analytics.py --nightly-status \
  --backup-dir ~/illinois-lottery-data/backups
```

Note that the collection pipeline emits its own nightly status **without**
`--backup-dir`, so its log line still reports these two alerts. That is a
reporting gap in the pipeline invocation, not a backup failure — the command
above is authoritative.

## The identity guard and restore verification

`verify_database_restore.py` restores into a throwaway database, which the
production identity guard would reject. The unit therefore sets:

```text
DATABASE_URL=postgresql+psycopg:///postgres   # socket peer auth, no password
EXPECTED_DATABASE_NAME=                       # empty disables the check
APP_ENV=test                                  # keeps an empty expectation legal
```

`EXPECTED_DATABASE_NAME` must be **empty rather than pointed at the disposable
database**: the verifier also runs `tests/postgres`, whose migration tests
create their own temporary databases and would fail any fixed expectation.

Verification requires a role with `CREATEDB`. The unit relies on local socket
peer authentication as `stosh99`, so no password is stored anywhere.

## Restoring for real

1. Choose a dump and confirm it against its manifest:

   ```bash
   sha256sum ~/illinois-lottery-data/backups/<name>.dump
   python3 -c "import json;print(json.load(open('<name>.dump.manifest.json'))['dump_sha256'])"
   ```

2. Rehearse into a disposable database first — never restore straight over
   production:

   ```bash
   cd ~/projects/IllinoisLotteryTracker
   DATABASE_URL=postgresql+psycopg:///postgres EXPECTED_DATABASE_NAME= APP_ENV=test \
     .venv/bin/python scripts/verify_database_restore.py \
     --dump ~/illinois-lottery-data/backups/<name>.dump \
     --target-database illinois_lottery_restore_verify_manual --keep-database
   ```

3. Only after that passes, stop the application, restore into production with
   `pg_restore --no-owner --clean --if-exists`, run `alembic current` to confirm
   the revision, and restart.

4. If the restore is a disaster recovery rather than a rehearsal, follow the
   session and login-attempt invalidation transaction in
   `deploy/AUTHENTICATION_OPERATIONS.md` before exposing traffic.

## Installing or changing the schedule

```bash
sudo install -o root -g root -m 0644 deploy/systemd/illinois-lottery-backup.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/illinois-lottery-backup.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/illinois-lottery-restore-verify.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/illinois-lottery-restore-verify.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now illinois-lottery-backup.timer illinois-lottery-restore-verify.timer
```

## Not yet covered

- **At-rest encryption of the offsite copies — deliberately deferred
  (decided 2026-08-27).** Required by the authentication release gate, and not
  yet urgent because the database holds no user rows: every byte in these
  backups is public lottery data.

  It is deferred because there is nowhere safe to keep the key. The workstation
  holding the offsite copies runs an unencrypted ext4 filesystem and there is no
  password manager, so any key or passphrase would sit on the same disk as the
  backups it protects — buying almost no confidentiality while creating a real
  new failure mode, since losing that machine would make every encrypted backup
  permanently unreadable.

  **Prerequisite: a secrets store** (password manager or equivalent). The same
  prerequisite blocks the separate all-projects `.env` backup effort, so one
  decision unblocks both. Once it exists, encrypt with a keypair so the nightly
  pull needs only the public key, and keep the private key both passphrase-
  protected locally and copied into the secrets store.
- **Secrets — deliberately out of scope here (decided 2026-08-27).** The
  production `.env` (Google OAuth client secret, `AUTH_SECRET_KEYS`) exists in
  exactly one place, and losing it means re-issuing OAuth credentials and
  invalidating every session. Rather than solve that for this project alone, it
  is being tracked as a **separate cross-project effort**: a protected backup of
  every `.env` across all projects and machines, stored on Google Drive.
  Whatever that effort produces must encrypt client-side before upload, since
  Drive is third-party storage and would otherwise become a single point of
  compromise for every project at once. Note the dependency: the authentication
  release gate requires a protected secret backup, so Phase 4 needs either that
  project or an interim measure for this one `.env`.
- **Backup failure alerting.** The morning watchdog checks collection freshness
  only; extending it to backup age is straightforward once outbound SMTP works.
