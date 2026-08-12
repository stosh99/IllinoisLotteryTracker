# Systemd and public-production operations

The active deployment collects official source evidence once and independently
imports the same immutable bundle into development and production. The production
application remains loopback-only; Nginx is the sole public edge. Authentication is
disabled. The authoritative implementation record is
[docs/environment_separation/IMPLEMENTATION_STATUS.md](../docs/environment_separation/IMPLEMENTATION_STATUS.md).

## Active units

- `illinois-lottery-dev-api.service` — development API/site on `127.0.0.1:8765`
- `illinois-lottery-prod-api.service` — public production origin on `127.0.0.1:8766`
- `illinois-lottery-source-fanout.service` — database-free collection followed by
  independent development and production imports
- `illinois-lottery-source-fanout.timer` — four Illinois-morning attempts

`illinois-lottery-shadow-api.service` and `illinois-lottery-nightly.timer` are
disabled, not deleted. Their files and release/data dependencies remain available
for rollback.

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

The canonical archive is
`/home/stosh99/illinois-lottery-data/source-captures`. The original archive at
`data/raw` remains preserved. The dedicated collector Chrome profile is
`/home/stosh99/illinois-lottery-data/browser-profile/collector`.

## Status and logs

```bash
systemctl --user status illinois-lottery-dev-api.service
systemctl --user status illinois-lottery-prod-api.service
systemctl --user status illinois-lottery-source-fanout.timer
systemctl --user status illinois-lottery-source-fanout.service
journalctl --user -u illinois-lottery-prod-api.service -n 100
journalctl --user -u illinois-lottery-source-fanout.service -n 100
```

Confirm only the intended services and timer are enabled:

```bash
systemctl --user is-enabled illinois-lottery-prod-api.service
systemctl --user is-enabled illinois-lottery-shadow-api.service
systemctl --user is-enabled illinois-lottery-source-fanout.timer
systemctl --user is-enabled illinois-lottery-nightly.timer
```

## Application checks

Run the installed collector/fan-out service idempotently with:

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

Check the loopback and public surfaces:

```bash
curl -f http://127.0.0.1:8765/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/auth/session
curl -f https://illinoislotterytracker.com/
curl -f https://illinoislotterytracker.com/api/v1/rankings
curl -f https://illinoislotterytracker.com/api/v1/auth/session
```

The auth-session response must report `authenticationAvailable: false` and
`authenticated: false`. `ss -ltnp` must show Uvicorn listening on `127.0.0.1`, never
`0.0.0.0` or `[::]`.

## Nginx and TLS

The repository contains:

```text
deploy/nginx/illinoislotterytracker.com.bootstrap.conf
deploy/nginx/illinoislotterytracker.com.conf
deploy/certbot/reload-nginx
```

The bootstrap vhost exists only to obtain the first webroot certificate. Normal
operation uses the final vhost at
`/etc/nginx/sites-available/illinoislotterytracker.com`, enabled through an exact
symlink in `sites-enabled`. It redirects all HTTP and `www` traffic to
`https://illinoislotterytracker.com` and proxies only the HTTPS apex to
`127.0.0.1:8766`.

Validate the edge and renewal path with:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certificates --cert-name illinoislotterytracker.com
sudo certbot renew --cert-name illinoislotterytracker.com \
  --dry-run --no-random-sleep-on-renew
systemctl status certbot.timer
```

Certbot authenticates through `/var/www/illinoislotterytracker`. Its installed
deploy hook validates Nginx before reloading it so renewed certificates become active
without a manual restart.

## Timer details

The source timer fires at 03:00, 04:00, 05:00, and 06:00 `America/Chicago`, with up
to five minutes of jitter and `Persistent=true`. Once a valid bundle exists for
today's Illinois source date, later attempts validate and re-import the newest such
bundle idempotently rather than collecting again.

Collection uses headed installed Chrome on a private Xvfb display only when direct
HTTP collection is blocked or returns challenge content. A failed challenge capture
cannot publish a bundle and cannot reach either database.

## Application rollback

The pre-public release is selected by:

```text
/home/stosh99/apps/illinois-lottery-tracker/rollback-before-public-20260812
```

To return port 8766 to that preserved release without changing either database or
the public Nginx edge:

```bash
systemctl --user disable --now illinois-lottery-prod-api.service
ln -s \
  /home/stosh99/apps/illinois-lottery-tracker/rollback-before-public-20260812 \
  /home/stosh99/apps/illinois-lottery-tracker/current.rollback
mv -Tf \
  /home/stosh99/apps/illinois-lottery-tracker/current.rollback \
  /home/stosh99/apps/illinois-lottery-tracker/current
systemctl --user enable --now illinois-lottery-shadow-api.service
curl -f http://127.0.0.1:8766/api/v1/rankings
```

To restore only the old single-database collection schedule:

```bash
systemctl --user disable --now illinois-lottery-source-fanout.timer
systemctl --user enable --now illinois-lottery-nightly.timer
```

Exact legacy unit copies remain under
`/home/stosh99/.config/illinois-lottery-tracker/rollback/`. Do not drop the production
database, remove either archive, delete a release, remove the certificate, or
overwrite environment files as part of routine rollback.
