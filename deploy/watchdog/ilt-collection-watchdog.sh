#!/usr/bin/env bash
# Independent overnight-collection watchdog for Illinois Lottery Tracker.
# Reads both databases directly (no shared code with the collector) and emails
# when the expected complete collection for today is missing, and separately
# when today's production catalog run recorded unresolved quality issues.
#
# Installed copy: /home/stosh99/bin/ilt-collection-watchdog.sh (see README.md).
set -u

RECIPIENT="hartman.steve99@gmail.com"
SENDER="hartman.steve99@gmail.com"
ENV_DIR="/home/stosh99/.config/illinois-lottery-tracker"
# Override for testing: ILT_WATCHDOG_EXPECT_DATE=2099-01-01 forces a failure.
CHECK_DATE="${ILT_WATCHDOG_EXPECT_DATE:-$(TZ=America/Chicago date +%F)}"
# Override for testing: report the catalog warnings recorded on another date.
WARNINGS_DATE="${ILT_WATCHDOG_WARNINGS_DATE:-$CHECK_DATE}"
# Set ILT_WATCHDOG_DRY_RUN=1 to print emails instead of sending them.
DRY_RUN="${ILT_WATCHDOG_DRY_RUN:-0}"

send_mail() {
  if [ "$DRY_RUN" = "1" ]; then
    cat
    return 0
  fi
  msmtp "$RECIPIENT"
}

database_url() {
  grep -E '^DATABASE_URL=' "${ENV_DIR}/$1.env" 2>/dev/null | head -1 | cut -d= -f2- \
    | sed 's#^postgresql+psycopg://#postgresql://#'
}

failures=()
for env_name in production development; do
  url=$(database_url "$env_name")
  if [ -z "$url" ]; then
    failures+=("${env_name}: could not read DATABASE_URL from ${ENV_DIR}/${env_name}.env")
    continue
  fi
  latest=$(psql "$url" -Atqc "SELECT max(source_date) FROM current_complete_scrape_run_v" 2>&1)
  if [ $? -ne 0 ]; then
    failures+=("${env_name}: database check failed: ${latest}")
  elif [ "$latest" != "$CHECK_DATE" ]; then
    failures+=("${env_name}: latest complete collection is '${latest:-none}', expected ${CHECK_DATE}")
  fi
done

status=0
if [ ${#failures[@]} -eq 0 ]; then
  echo "OK: both databases have a complete collection for ${CHECK_DATE}"
else
  {
    printf 'Subject: [IllinoisLotteryTracker] Overnight collection FAILED (%s)\n' "$CHECK_DATE"
    printf 'From: %s\nTo: %s\n\n' "$SENDER" "$RECIPIENT"
    printf 'The overnight collection watchdog ran at %s and found problems:\n\n' "$(date --iso-8601=seconds)"
    printf ' - %s\n' "${failures[@]}"
    printf '\nCollector log: ssh stosh99@66.220.29.98 then\n'
    printf '  journalctl -u illinois-lottery-source-fanout.service --since today\n'
  } | send_mail
  echo "FAILURE: ${failures[*]} (email exit=$?)"
  status=1
fi

# Catalog quality warnings. Production only: development imports the same bundle.
if ! [[ "$WARNINGS_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "ERROR: invalid warnings date '${WARNINGS_DATE}'"
  exit 1
fi
prod_url=$(database_url production)
if [ -n "$prod_url" ]; then
  warnings=$(psql "$prod_url" -Atq -v ON_ERROR_STOP=1 -v check_date="$WARNINGS_DATE" 2>&1 <<'SQL'
SELECT issue.severity || ' ' || issue.code
       || ' | game ' || coalesce(issue.details->>'game_number', '-')
       || ' ' || coalesce(issue.details->>'name', issue.detail_url, '')
       || coalesce(' | ' || (issue.details->>'summary'), '')
FROM catalog_quality_issues issue
JOIN scrape_runs run ON run.id = issue.scrape_run_id
WHERE run.workflow = 'instant_ticket_catalog'
  AND run.source_date = :'check_date'
  AND issue.resolved_at IS NULL
ORDER BY issue.severity DESC, issue.code, issue.id;
SQL
  )
  if [ $? -ne 0 ]; then
    echo "ERROR: catalog warning query failed: ${warnings}"
    status=1
  elif [ -n "$warnings" ]; then
    count=$(printf '%s\n' "$warnings" | wc -l)
    {
      printf 'Subject: [IllinoisLotteryTracker] Collection warnings (%s): %s issue(s)\n' \
        "$WARNINGS_DATE" "$count"
      printf 'From: %s\nTo: %s\n\n' "$SENDER" "$RECIPIENT"
      printf 'The %s production catalog import published with these unresolved\n' "$WARNINGS_DATE"
      printf 'quality issues. The collection itself succeeded.\n\n'
      printf '%s\n' "$warnings" | sed 's/^/ - /'
      printf '\nDetails: catalog_quality_issues for the %s instant_ticket_catalog run.\n' \
        "$WARNINGS_DATE"
    } | send_mail
    echo "WARNINGS: ${count} catalog issue(s) for ${WARNINGS_DATE} (email exit=$?)"
  else
    echo "OK: no catalog warnings for ${WARNINGS_DATE}"
  fi
fi

exit "$status"
