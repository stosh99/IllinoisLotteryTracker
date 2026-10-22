# Collection watchdog

`ilt-collection-watchdog.sh` runs daily at 06:30 America/Chicago from
`ilt-collection-watchdog.timer` / `.service` (system units on the VPS). It shares
no code with the pipeline: it reads both databases with `psql` using the
credentials in `/home/stosh99/.config/illinois-lottery-tracker/{production,development}.env`
and sends mail with `msmtp` (`~/.msmtprc`).

It sends two independent emails:

- **Overnight collection FAILED** — either database lacks a complete collection
  for today. Exit status 1.
- **Collection warnings** — today's production `instant_ticket_catalog` run has
  unresolved `catalog_quality_issues` (count mismatches, duplicate or missing
  games, name or price mismatches, unmapped cards). The collection succeeded;
  exit status 0.

## Install or update

The tracked copy here is the source of truth. After pulling on the VPS:

```bash
install -m 0755 deploy/watchdog/ilt-collection-watchdog.sh /home/stosh99/bin/ilt-collection-watchdog.sh
```

## Test

```bash
# Print both emails instead of sending, for a date that has recorded issues.
ILT_WATCHDOG_DRY_RUN=1 ILT_WATCHDOG_WARNINGS_DATE=2026-09-09 /home/stosh99/bin/ilt-collection-watchdog.sh
# Send a real warning email.
ILT_WATCHDOG_WARNINGS_DATE=2026-09-09 /home/stosh99/bin/ilt-collection-watchdog.sh
# Force the failure email.
ILT_WATCHDOG_EXPECT_DATE=2099-01-01 /home/stosh99/bin/ilt-collection-watchdog.sh
```
