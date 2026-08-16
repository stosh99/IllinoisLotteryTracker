# Systemd and production operations

Illinois Lottery Tracker uses system-level systemd units running as `stosh99`.
Exactly one web application runs on the VPS, and it is production.

Canonical deployment checkout:

```text
/home/stosh99/projects/IllinoisLotteryTracker
```

## Units

- `illinois-lottery-prod-api.service` — production API/site on `127.0.0.1:8766`
- `illinois-lottery-source-fanout.service` — database-free collection followed by
  independent development and production imports
- `illinois-lottery-source-fanout.timer` — four Illinois-morning attempts

Install tracked unit files with root ownership:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/illinois-lottery-prod-api.service \
  /etc/systemd/system/illinois-lottery-prod-api.service
sudo install -o root -g root -m 0644 \
  deploy/systemd/illinois-lottery-source-fanout.service \
  /etc/systemd/system/illinois-lottery-source-fanout.service
sudo install -o root -g root -m 0644 \
  deploy/systemd/illinois-lottery-source-fanout.timer \
  /etc/systemd/system/illinois-lottery-source-fanout.timer
sudo systemctl daemon-reload
```

Do not install or enable `illinois-lottery-dev-api.service`. Development runs only
on external machines.

## Configuration

The production application and fanout importer read:

```text
/home/stosh99/projects/IllinoisLotteryTracker/.env
```

The file is gitignored, owned by `stosh99`, and mode `0600`. It contains production
and development database URLs because the fanout imports the same source bundle into
both databases. The production web application reads only `DATABASE_URL`.

Required identity variables:

```dotenv
APP_ENV=production
EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod
DATABASE_URL=<production URL>
DEV_EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev
DEV_DATABASE_URL=<development URL>
RAW_DATA_DIR=/home/stosh99/illinois-lottery-data/source-captures
AUTH_ENABLED=false
```

Never print, log, or pass the file through command arguments. The collector service
does not load it. The fanout script reads it only after collection and sends
least-privilege environments to the two importer subprocesses.

## Status and logs

```bash
sudo systemctl status illinois-lottery-prod-api.service --no-pager
sudo systemctl status illinois-lottery-source-fanout.timer --no-pager
sudo systemctl status illinois-lottery-source-fanout.service --no-pager
sudo journalctl -u illinois-lottery-prod-api.service -n 100 --no-pager
sudo journalctl -u illinois-lottery-source-fanout.service -n 100 --no-pager
```

Confirm there is no development API:

```bash
sudo systemctl is-active illinois-lottery-prod-api.service
sudo systemctl is-enabled illinois-lottery-prod-api.service
systemctl --user is-active illinois-lottery-dev-api.service
systemctl --user is-enabled illinois-lottery-dev-api.service
```

The final two commands must report inactive/disabled or not found.

## Application checks

```bash
curl -f http://127.0.0.1:8766/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/auth/session
curl -f https://illinoislotterytracker.com/
curl -f https://illinoislotterytracker.com/api/v1/rankings
curl -f https://illinoislotterytracker.com/api/v1/auth/session
```

While authentication is disabled, the auth-session response reports
`authenticationAvailable: false` and `authenticated: false`. `ss -ltnp` must show
Uvicorn on `127.0.0.1:8766`, never `0.0.0.0` or `[::]`.

## Fanout checks

Run a manual collection/import and inspect its result:

```bash
sudo systemctl start illinois-lottery-source-fanout.service
sudo systemctl status illinois-lottery-source-fanout.service --no-pager
sudo journalctl -u illinois-lottery-source-fanout.service -n 150 --no-pager
```

The journal must report independent development and production outcomes. Confirm the
same bundle reached both databases and that no database URL, password, OAuth secret,
or root key appears in logs.

The timer fires at 03:00, 04:00, 05:00, and 06:00 `America/Chicago`, with up to five
minutes of jitter and `Persistent=true`.

## Nginx and TLS

The tracked edge configuration remains under `deploy/nginx/`. Nginx proxies only the
HTTPS apex to `127.0.0.1:8766`; the application trusts proxy headers only from
`127.0.0.1`.

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certificates --cert-name illinoislotterytracker.com
```

## Architecture-cutover rollback

For seven days after cutover, preserve:

- the release tree selected by `/home/stosh99/apps/illinois-lottery-tracker/current`;
- the old user-level production and fanout unit files;
- `~/.config/illinois-lottery-tracker/{development,production,collector}.env`;
- database dumps and restore-verification evidence; and
- the prior fanout configuration.

If the new production service fails during cutover:

1. Stop and disable the system-level production service.
2. Restore the saved user-level release service and external `production.env`.
3. Confirm `current` still targets the preserved release.
4. Start the old service on `127.0.0.1:8766`.
5. Verify loopback and public HTTPS.
6. Restore the previous fanout unit only if the replacement had been activated.

The development API is not required for public rollback. Do not delete rollback
artifacts until the seven-day soak passes and the owner explicitly approves cleanup.

See `docs/DEPLOYMENT.md` for normal deployment and `docs/REMOTE_DEV.md` for external
development setup.
