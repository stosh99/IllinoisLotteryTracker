# Systemd Scheduling Setup

Runs the nightly unpaid-prizes pipeline as a systemd user service (no root required).

## Prerequisites

### 1. Enable linger (one-time, requires sudo)

Linger lets user services start at boot without an active login session:

```bash
sudo loginctl enable-linger stosh99
```

Verify:

```bash
loginctl show-user stosh99 | grep Linger
# Linger=yes
```

### 2. Confirm .env is present and readable

```bash
head -2 /home/stosh99/projects/IllinoisLotteryTracker/.env
# DATABASE_URL=postgresql+psycopg://...
# RAW_DATA_DIR=data/raw
```

---

## Install

Copy unit files to the user systemd directory and reload:

```bash
cp deploy/systemd/illinois-lottery-nightly.service ~/.config/systemd/user/
cp deploy/systemd/illinois-lottery-nightly.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
```

---

## Enable and Start

```bash
systemctl --user enable --now illinois-lottery-nightly.timer
```

Verify the timer is active:

```bash
systemctl --user list-timers illinois-lottery-nightly.timer
```

---

## Status and Logs

```bash
# Timer status
systemctl --user status illinois-lottery-nightly.timer

# Most recent service run status
systemctl --user status illinois-lottery-nightly.service

# Full journal output for all runs
journalctl --user -u illinois-lottery-nightly.service

# Last run only
journalctl --user -u illinois-lottery-nightly.service -n 100
```

---

## Manual Run (one-off)

Run the service immediately without waiting for the timer:

```bash
systemctl --user start illinois-lottery-nightly.service
```

Or run the script directly from a shell (useful for debugging):

```bash
cd /home/stosh99/projects/IllinoisLotteryTracker
env $(grep -v '^#' .env | xargs) \
    .venv/bin/python scripts/run_nightly_unpaid_prizes_pipeline.py
```

Dry-run (parse and import but roll back — no DB writes):

```bash
cd /home/stosh99/projects/IllinoisLotteryTracker
env $(grep -v '^#' .env | xargs) \
    .venv/bin/python scripts/run_nightly_unpaid_prizes_pipeline.py --dry-run
```

Re-import a specific saved file (skips network fetch):

```bash
cd /home/stosh99/projects/IllinoisLotteryTracker
env $(grep -v '^#' .env | xargs) \
    .venv/bin/python scripts/run_nightly_unpaid_prizes_pipeline.py \
    --raw-file data/raw/2026-05-10/unpaid-instant-games-prizes-20260510T000519Z.html
```

---

## Disable and Remove

```bash
systemctl --user disable --now illinois-lottery-nightly.timer
rm ~/.config/systemd/user/illinois-lottery-nightly.service
rm ~/.config/systemd/user/illinois-lottery-nightly.timer
systemctl --user daemon-reload
```

---

## Timer Details

| Setting | Value | Effect |
|---|---|---|
| `OnCalendar` | `*-*-* 03:00:00` | Fires daily at 03:00 local time (America/New_York) |
| `AccuracySec` | `1s` | Near-exact firing time (default is 1 minute) |
| `RandomizedDelaySec` | `300` | Random 0–5 min jitter to avoid thundering-herd |
| `Persistent` | `true` | Runs immediately on next boot if a scheduled run was missed |
