# Systemd operations: split collection and shadow production

The active deployment collects official source evidence once and independently
imports the same immutable bundle into development and shadow production. The
shadow site is loopback-only and authentication is disabled. The authoritative
implementation and rollback record is
[docs/environment_separation/IMPLEMENTATION_STATUS.md](../docs/environment_separation/IMPLEMENTATION_STATUS.md).

## Active units

- `illinois-lottery-dev-api.service` — development API/site on `127.0.0.1:8765`
- `illinois-lottery-shadow-api.service` — shadow API/site on `127.0.0.1:8766`
- `illinois-lottery-source-fanout.service` — database-free collection followed by
  independent development and production imports
- `illinois-lottery-source-fanout.timer` — four Illinois-morning attempts

The previous `illinois-lottery-nightly.timer` is disabled, not deleted. Its service
and timer files are preserved both in the user systemd directory and in the private
rollback directory documented below.

## Configuration and data

Private mode-600 environment files live in:

```text
/home/stosh99/.config/illinois-lottery-tracker/development.env
/home/stosh99/.config/illinois-lottery-tracker/production.env
/home/stosh99/.config/illinois-lottery-tracker/collector.env
```

Do not print or pass those files through `env`, `xargs`, command-line arguments, or
logs. Development and production files each set `APP_ENV`, an exact
`EXPECTED_DATABASE_NAME`, their independent `DATABASE_URL`, the shared
`RAW_DATA_DIR`, and `AUTH_ENABLED=false`. The collector file has no database URL.

The shared archive is
`/home/stosh99/illinois-lottery-data/source-captures`. The original project archive
at `data/raw` remains preserved. The dedicated Chrome profile is
`/home/stosh99/illinois-lottery-data/browser-profile/collector`.

## Status and logs

```bash
systemctl --user status illinois-lottery-dev-api.service
systemctl --user status illinois-lottery-shadow-api.service
systemctl --user status illinois-lottery-source-fanout.timer
systemctl --user status illinois-lottery-source-fanout.service
journalctl --user -u illinois-lottery-source-fanout.service -n 100
```

Confirm only the intended timer is active:

```bash
systemctl --user list-timers --all
systemctl --user is-enabled illinois-lottery-source-fanout.timer
systemctl --user is-enabled illinois-lottery-nightly.timer
```

## Manual checks

Run the installed collector/fan-out service idempotently:

```bash
systemctl --user start illinois-lottery-source-fanout.service
```

Compare database revisions, all table row counts, and zero auth rows without printing
credentials:

```bash
.venv/bin/python scripts/compare_shadow_environments.py \
  --development-env /home/stosh99/.config/illinois-lottery-tracker/development.env \
  --production-env /home/stosh99/.config/illinois-lottery-tracker/production.env
```

Check the loopback surfaces:

```bash
curl -f http://127.0.0.1:8765/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/auth/session
curl -f http://127.0.0.1:8766/
```

The auth-session response must report `authenticationAvailable: false` and
`authenticated: false`.

## Timer details

The timer fires at 03:00, 04:00, 05:00, and 06:00 `America/Chicago`, with up to five
minutes of jitter and `Persistent=true`. Once a valid bundle exists for today's
Illinois source date, later attempts validate and re-import the newest such bundle
idempotently rather than collecting again.

Collection uses headed installed Chrome on a private Xvfb display only when direct
HTTP collection is blocked or returns challenge content. A failed challenge capture
cannot publish a bundle and cannot reach either database.

## Rollback

Exact legacy unit copies are at:

```text
/home/stosh99/.config/illinois-lottery-tracker/rollback/illinois-lottery-nightly.service
/home/stosh99/.config/illinois-lottery-tracker/rollback/illinois-lottery-nightly.timer
```

To restore scheduling without deleting any new evidence or database:

```bash
systemctl --user disable --now illinois-lottery-source-fanout.timer
systemctl --user enable --now illinois-lottery-nightly.timer
```

To stop only the shadow surface:

```bash
systemctl --user disable --now illinois-lottery-shadow-api.service
```

The pre-split and post-split restore-verified backups are listed in the implementation
status. Do not drop the production database, remove either archive, delete a release,
or overwrite environment files as part of routine rollback.
