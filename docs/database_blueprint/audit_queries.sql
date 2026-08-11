-- IllinoisLotteryTracker canonical read-only database audit.
--
-- Run with ON_ERROR_STOP so a missing target-schema object fails loudly:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f docs/database_blueprint/audit_queries.sql
--
-- This file performs SELECT statements only. Zero-failure result columns are
-- identified in comments. The cutoff snapshot used during design had 75 games,
-- 90 complete runs, 5,128 game snapshots, 65,911 tiers, and 57 current games.

BEGIN TRANSACTION READ ONLY;

-- Basic row inventory.
SELECT
    (SELECT count(*) FROM games) AS games,
    (SELECT count(*) FROM scrape_runs) AS scrape_runs,
    (SELECT count(*) FROM raw_source_snapshots) AS raw_source_snapshots,
    (SELECT count(*) FROM game_snapshots) AS game_snapshots,
    (SELECT count(*) FROM prize_tier_snapshots) AS prize_tier_snapshots;

-- Every game snapshot must reconcile exactly to its tiers. All four failure
-- columns must be zero.
WITH tier_rollups AS (
    SELECT
        game_snapshot_id,
        sum(original_count) AS original_count,
        sum(remaining_count) AS remaining_count,
        sum(prize_amount * original_count) AS original_value,
        sum(prize_amount * remaining_count) AS remaining_value
    FROM prize_tier_snapshots
    GROUP BY game_snapshot_id
)
SELECT
    count(*) FILTER (
        WHERE gs.total_original_winning_tickets <> tr.original_count
    ) AS original_count_failures,
    count(*) FILTER (
        WHERE gs.total_remaining_winning_tickets <> tr.remaining_count
    ) AS remaining_count_failures,
    count(*) FILTER (
        WHERE gs.total_original_prize_value <> tr.original_value
    ) AS original_value_failures,
    count(*) FILTER (
        WHERE gs.total_remaining_prize_value <> tr.remaining_value
    ) AS remaining_value_failures
FROM game_snapshots gs
JOIN tier_rollups tr ON tr.game_snapshot_id = gs.id;

-- All tier failure columns must be zero.
SELECT
    count(*) FILTER (WHERE original_count IS NULL) AS null_original,
    count(*) FILTER (WHERE remaining_count IS NULL) AS null_remaining,
    count(*) FILTER (WHERE claimed_count IS NULL) AS null_claimed,
    count(*) FILTER (
        WHERE original_count < 0 OR remaining_count < 0 OR claimed_count < 0
    ) AS negative_counts,
    count(*) FILTER (
        WHERE remaining_count > original_count
    ) AS remaining_above_original,
    count(*) FILTER (
        WHERE claimed_count <> original_count - remaining_count
    ) AS claimed_identity_failures
FROM prize_tier_snapshots;

-- No original tier structure should change within one structure fingerprint.
-- Before a legitimate/source-correction structure change is supported, this
-- query must return zero rows.
SELECT
    gs.game_id,
    p.prize_amount,
    count(DISTINCT p.original_count) AS distinct_original_counts
FROM game_snapshots gs
JOIN prize_tier_snapshots p ON p.game_snapshot_id = gs.id
GROUP BY gs.game_id, p.prize_amount
HAVING count(DISTINCT p.original_count) > 1;

-- Remaining counts may not increase over source time. Must return zero rows.
WITH ordered AS (
    SELECT
        g.game_number,
        p.prize_amount,
        r.captured_at AS source_observed_at,
        p.remaining_count,
        lag(p.remaining_count) OVER (
            PARTITION BY g.id, p.prize_amount
            ORDER BY r.captured_at, gs.id
        ) AS prior_remaining_count
    FROM game_snapshots gs
    JOIN games g ON g.id = gs.game_id
    JOIN raw_source_snapshots r ON r.scrape_run_id = gs.scrape_run_id
    JOIN prize_tier_snapshots p ON p.game_snapshot_id = gs.id
)
SELECT *
FROM ordered
WHERE remaining_count > prior_remaining_count
ORDER BY game_number, prize_amount, source_observed_at;

-- A complete imported run has one raw source row and internally matching
-- parsed child counts. Failure columns must be zero after revision 0002.
WITH actual AS (
    SELECT
        sr.id,
        count(DISTINCT raw.id) AS raw_count,
        count(DISTINCT gs.id) AS game_count,
        count(DISTINCT p.id) AS tier_count
    FROM scrape_runs sr
    LEFT JOIN raw_source_snapshots raw ON raw.scrape_run_id = sr.id
    LEFT JOIN game_snapshots gs ON gs.scrape_run_id = sr.id
    LEFT JOIN prize_tier_snapshots p ON p.game_snapshot_id = gs.id
    WHERE sr.workflow = 'unpaid_prizes'
      AND sr.status = 'success'
      AND sr.is_complete
    GROUP BY sr.id
)
SELECT
    count(*) FILTER (WHERE a.raw_count <> 1) AS raw_count_failures,
    count(*) FILTER (
        WHERE a.game_count <> sr.parsed_game_count
    ) AS parsed_game_count_failures,
    count(*) FILTER (
        WHERE a.tier_count <> sr.parsed_prize_tier_count
    ) AS parsed_tier_count_failures,
    count(*) FILTER (
        WHERE sr.source_observed_at IS NULL
           OR sr.source_date IS NULL
           OR sr.source_sha256 IS NULL
    ) AS missing_provenance_failures
FROM actual a
JOIN scrape_runs sr ON sr.id = a.id;

-- No complete successful unpaid-prizes content hash may be duplicated. Catalog
-- captures are intentionally daily and may repeat when the offered set is unchanged.
SELECT source_sha256, count(*) AS duplicate_count
FROM scrape_runs
WHERE workflow = 'unpaid_prizes' AND status = 'success' AND is_complete
GROUP BY source_sha256
HAVING count(*) > 1;

-- Canonical current membership and compatibility-cache agreement.
SELECT
    (SELECT count(*) FROM current_game_snapshots_v) AS current_game_count,
    count(*) FILTER (
        WHERE g.is_active IS DISTINCT FROM (c.game_id IS NOT NULL)
    ) AS compatibility_active_mismatches
FROM games g
LEFT JOIN (
    SELECT game_id FROM current_game_snapshots_v
) c ON c.game_id = g.id;

-- Prize-source and catalog membership remain distinct and reconciled.
SELECT
    count(*) FILTER (WHERE prize_source_current) AS prize_source_current,
    count(*) FILTER (WHERE catalog_current) AS catalog_current,
    count(*) FILTER (WHERE recommendation_current) AS recommendation_current,
    count(*) FILTER (
        WHERE prize_source_current AND NOT catalog_current
    ) AS prize_source_only,
    count(*) FILTER (
        WHERE catalog_current AND NOT prize_source_current
    ) AS catalog_only
FROM current_game_source_reconciliation_v;

SELECT count(*) AS unmapped_current_catalog_entries
FROM game_catalog_snapshots
WHERE scrape_run_id = (SELECT id FROM current_complete_catalog_run_v)
  AND game_id IS NULL;

-- Current source and successful analytics cutoffs must match
-- result. This returns either one matching row or no analytics row; it must
-- never return a mismatched pair.
SELECT
    source.id AS source_run_id,
    analytics.as_of_scrape_run_id AS analytics_source_run_id,
    analytics.id AS analytics_run_id,
    source.id = analytics.as_of_scrape_run_id AS cutoffs_match
FROM current_complete_scrape_run_v source
LEFT JOIN current_analytics_run_v analytics ON true;

-- Every current game and tier should have one row in a successful analytics
-- run. Review nonzero differences.
SELECT
    (SELECT count(*) FROM current_game_snapshots_v) AS source_games,
    (SELECT count(*) FROM current_game_metrics_v) AS analytics_games,
    (
        SELECT count(*)
        FROM prize_tier_snapshots p
        JOIN current_game_snapshots_v gs ON gs.id = p.game_snapshot_id
    ) AS source_tiers,
    (SELECT count(*) FROM current_tier_metrics_v) AS analytics_tiers;

-- No unavailable/partial strategy metric may receive a rank. Must be zero.
SELECT count(*) AS invalid_ranked_rows
FROM current_strategy_rankings_v
WHERE metric_status <> 'complete'
  AND (rank_overall IS NOT NULL OR rank_within_ticket_price IS NOT NULL);

-- Source/model quality summary for operator review.
SELECT severity, code, count(*) AS issue_count
FROM analytics_quality_issues
WHERE analytics_run_id = (SELECT id FROM current_analytics_run_v)
GROUP BY severity, code
ORDER BY severity, code;

-- Fail closed for the invariant classes used by automated restore verification.
-- The preceding SELECTs remain useful operator detail; this block makes any
-- nonzero result produce a nonzero psql exit under ON_ERROR_STOP.
DO $audit$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM prize_tier_snapshots
    WHERE original_count IS NULL OR remaining_count IS NULL OR claimed_count IS NULL
       OR original_count < 0 OR remaining_count < 0 OR claimed_count < 0
       OR remaining_count > original_count
       OR claimed_count <> original_count - remaining_count
  ) THEN
    RAISE EXCEPTION 'audit failed: invalid prize-tier counts';
  END IF;

  IF EXISTS (
    WITH totals AS (
      SELECT game_snapshot_id,
             sum(original_count) original_count,
             sum(remaining_count) remaining_count,
             sum(prize_amount * original_count) original_value,
             sum(prize_amount * remaining_count) remaining_value
      FROM prize_tier_snapshots GROUP BY game_snapshot_id
    )
    SELECT 1 FROM game_snapshots snapshot
    JOIN totals ON totals.game_snapshot_id = snapshot.id
    WHERE snapshot.total_original_winning_tickets IS DISTINCT FROM totals.original_count
       OR snapshot.total_remaining_winning_tickets IS DISTINCT FROM totals.remaining_count
       OR snapshot.total_original_prize_value IS DISTINCT FROM totals.original_value
       OR snapshot.total_remaining_prize_value IS DISTINCT FROM totals.remaining_value
  ) THEN
    RAISE EXCEPTION 'audit failed: snapshot rollup mismatch';
  END IF;

  IF EXISTS (
    SELECT 1 FROM (
      SELECT tier.remaining_count,
             lag(tier.remaining_count) OVER (
               PARTITION BY snapshot.game_id, tier.prize_amount
               ORDER BY run.source_observed_at, run.id
             ) prior_remaining_count
      FROM game_snapshots snapshot
      JOIN scrape_runs run ON run.id = snapshot.scrape_run_id
      JOIN prize_tier_snapshots tier ON tier.game_snapshot_id = snapshot.id
      WHERE run.workflow = 'unpaid_prizes'
        AND run.status = 'success' AND run.is_complete
    ) ordered
    WHERE remaining_count > prior_remaining_count
  ) THEN
    RAISE EXCEPTION 'audit failed: remaining-count reversal';
  END IF;

  IF EXISTS (
    SELECT source_sha256
    FROM scrape_runs
    WHERE workflow = 'unpaid_prizes' AND status = 'success' AND is_complete
    GROUP BY source_sha256 HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'audit failed: duplicate unpaid-prizes source hash';
  END IF;
END
$audit$;

ROLLBACK;
