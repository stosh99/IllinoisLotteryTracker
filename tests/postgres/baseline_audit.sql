BEGIN TRANSACTION READ ONLY;

SELECT count(*) AS unexpected_scrape_runs FROM scrape_runs;
SELECT count(*) AS unexpected_games FROM games;
SELECT count(*) AS unexpected_raw_snapshots FROM raw_source_snapshots;
SELECT count(*) AS unexpected_game_snapshots FROM game_snapshots;
SELECT count(*) AS unexpected_prize_tiers FROM prize_tier_snapshots;

SELECT count(*) AS missing_baseline_tables
FROM unnest(
    ARRAY[
        'scrape_runs',
        'games',
        'raw_source_snapshots',
        'game_snapshots',
        'prize_tier_snapshots'
    ]
) AS expected(table_name)
WHERE to_regclass('public.' || table_name) IS NULL;

ROLLBACK;
