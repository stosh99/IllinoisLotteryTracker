# Schema and Migrations

## Source and catalog authority

`scrape_runs`, raw snapshots, game snapshots, prize-tier snapshots, catalog
snapshots, and reconciliation views remain the immutable official-data layer.
Completeness/provenance constraints and current-run views choose the newest
valid source independently for unpaid prizes and the retail catalog.

## Analytics model 2.0.0

`analytics_model_versions` stores an immutable semantic version, complete JSON
parameter document, canonical SHA-256, code version, and creation time. It has
no operational approval state.

Model 2.0.0 parameters include:

```text
baseline_max_prize=600
high_prize_strictly_greater_than=600
high_prize_minimum_original_count=300
mail_claim_reporting_lag_days=24
reference_min_original_count=10000
source_fresh_hours=36
source_stale_error_hours=72
```

`analytics_runs` is unique by model version and source cutoff. Status is
`running`, `success`, or `failed`; successful runs are immutable.

`analytics_game_metrics` stores ordinary-progress rollups, ticket estimates,
coverage, source/catalog membership, cutoff provenance, and data status.

`analytics_tier_metrics` stores one row per source tier, including:

- source/model/run/game/tier identity;
- ordinary or high process group;
- reference method and observation time;
- `adjustment_eligible`;
- `adjustment_status` (`applied`, `reported_only`, or
  `reference_unavailable`);
- integer `lag_days_used` (24 only when applied);
- official remaining count;
- estimated pending count;
- adjusted remaining count;
- availability, probability, EV inputs, confidence, and status.

`analytics_strategy_metrics` stores explicit strategy probabilities, one-in
values, EVs, payout ratios, coverage, confidence, top-prize facts, and per-key
metric detail JSON.

`analytics_quality_issues` stores stable issue codes and entity provenance.

## Revision 0010

`0010_simplified_high_prize_adjustment` is an intentional cleanup migration:

- drops the superseded derived analytics tables;
- drops approval/publication and sensitivity fields;
- deletes model-1 derived runs while preserving all source/catalog data;
- adds explicit fixed-adjustment fields and constraints;
- seeds immutable model 2.0.0;
- recreates current and ranking views; and
- makes all successful analytics runs immutable.

The cleanup is not downgradable because removed rows are derived and the old
schema is intentionally unsupported. Recovery uses the required pre-migration
database backup.

## Current views

`current_analytics_run_v` requires a successful model-2.0.0 run tied to the
current complete unpaid-prizes source. Child views expose current game, tier,
and strategy metrics. Ranking status separately checks source/catalog presence
and freshness. Ranking rows require complete metrics and membership in the
current mapped source/catalog intersection.
