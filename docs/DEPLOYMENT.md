# Production deployment

Illinois Lottery Tracker runs from the official Git checkout on the VPS:

```text
/home/stosh99/projects/IllinoisLotteryTracker
```

That checkout is production. It is not a development workspace.

## Runtime

- System service: `illinois-lottery-prod-api.service`
- Service user: `stosh99`
- Origin: `127.0.0.1:8766`
- Public edge: Nginx at `https://illinoislotterytracker.com`
- Configuration: project-root `.env`, mode `0600`
- Production database: `illinois_lottery_tracker_prod`
- Shared development database: `illinois_lottery_tracker_dev`

The source fanout runs as a separate system service and timer. It collects one
database-free bundle and independently imports it into both databases from the same
code checkout.

## Deployment preflight

Before changing production:

1. Confirm the intended commit is pushed and reviewed.
2. Confirm the VPS checkout has no uncommitted or untracked files other than the
   ignored production `.env`.
3. Confirm the production database identity and current Alembic revision.
4. Back up production and restore-verify the backup before a schema migration.
5. Confirm no fanout import is running.
6. Keep topology, feature/schema, and authentication changes separate.

## Normal deploy

```bash
cd /home/stosh99/projects/IllinoisLotteryTracker
git status --short --branch
git fetch origin
git pull --ff-only
.venv/bin/pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/alembic current
```

Run the next command only when the reviewed deployment explicitly includes a
migration:

```bash
.venv/bin/alembic upgrade head
```

Restart and verify:

```bash
sudo systemctl restart illinois-lottery-prod-api.service
sudo systemctl status illinois-lottery-prod-api.service --no-pager
curl -f http://127.0.0.1:8766/api/v1/rankings
curl -f http://127.0.0.1:8766/api/v1/auth/session
curl -f https://illinoislotterytracker.com/
curl -f https://illinoislotterytracker.com/api/v1/rankings
```

When authentication is intentionally disabled, the session response must report
`authenticationAvailable: false` and `authenticated: false`.

## Configuration requirements

The production `.env` includes:

```dotenv
APP_ENV=production
EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod
DATABASE_URL=<production URL>
DEV_EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev
DEV_DATABASE_URL=<development URL>
RAW_DATA_DIR=/home/stosh99/illinois-lottery-data/source-captures
AUTH_ENABLED=false
```

OAuth and root-key values are also present when configured, even while auth remains
disabled. Never print or log the file. The file must remain gitignored and mode
`0600`.

## Fanout operation

```bash
sudo systemctl status illinois-lottery-source-fanout.timer --no-pager
sudo systemctl start illinois-lottery-source-fanout.service
sudo journalctl -u illinois-lottery-source-fanout.service -n 100 --no-pager
```

A successful run reports both targets independently. Verify that the same bundle
and source identity reached development and production and that logs contain no
credentials.

## Rollback

Application rollback is a Git operation after database compatibility is confirmed:

1. Stop the production service.
2. Check out or revert to the approved prior commit.
3. Rebuild the frontend and restore dependencies for that commit.
4. Start the service and verify loopback and public HTTPS.

Never downgrade a production database merely because application code was rolled
back. Additive migrations may safely remain when the older application ignores
them; destructive migration rollback requires a separate reviewed recovery plan.

During the architecture cutover's seven-day soak, use the preserved release-based
service and external `production.env` as the documented emergency rollback instead.
Do not remove those artifacts before the soak completes and the owner approves.
