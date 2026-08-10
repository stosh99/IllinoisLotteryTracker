# Schema and Migration Design

## Design Principles

1. Observed source data and derived analytics are different data classes.
2. Observed rows are append-only after import except for explicit provenance
   backfills performed by a migration.
3. Derived rows are reproducible from an immutable source cutoff, model
   version, and parameter document.
4. Failed or partial computation is represented explicitly; it never becomes
   the current published result.
5. A migration must work both on a restored copy of the current database and
   on a new empty PostgreSQL database.
6. PostgreSQL is the integration target. SQLite remains acceptable for pure
   calculation unit tests, not migration or constraint verification.

## Migration Sequence

### Revision `0001_existing_schema_baseline`

Create a baseline revision matching the current five tables and their existing
columns, constraints, and indexes exactly.

Existing database procedure:

1. restore the pre-migration backup into a disposable database;
2. compare the restored schema with SQLAlchemy metadata;
3. run `alembic stamp 0001_existing_schema_baseline` on the restored copy;
4. run `alembic upgrade head` there;
5. only after verification, stamp and upgrade the development database.

New database procedure:

```text
create empty database
alembic upgrade head
run schema/invariant smoke test
```

`Base.metadata.create_all()` must be removed from normal setup instructions
after this revision exists.

### Revision `0002_source_provenance_and_constraints`

Add these columns to `scrape_runs`:

| Column | Type | Nullability/default | Purpose |
|---|---|---|---|
| `workflow` | `varchar(32)` | not null, default `unpaid_prizes` | `unpaid_prizes` or `instant_ticket_catalog` |
| `source_observed_at` | `timestamptz` | nullable during backfill | Canonical source capture time |
| `source_date` | `date` | nullable during backfill | Chicago calendar date |
| `source_sha256` | `char(64)` | nullable during backfill | Imported source identity |
| `is_complete` | `boolean` | not null, default false | Passed global source checks |
| `parsed_game_count` | `integer` | nullable | Unique parsed games |
| `parsed_prize_tier_count` | `integer` | nullable | Parsed tier rows |
| `pipeline_version` | `varchar(64)` | nullable | Code/parser provenance |
| `manually_approved_at` | `timestamptz` | nullable | Explicit completeness override |
| `manual_approval_reason` | `text` | nullable | Auditable override reason |

Backfill each historical imported run from its one `raw_source_snapshots` row
and child row counts. Calculate:

```sql
source_date =
  (source_observed_at AT TIME ZONE 'America/Chicago')::date
```

All 90 historical successful runs should backfill as complete. Backfill
`game_snapshots.captured_at` to the run's `source_observed_at`; this column's
canonical meaning becomes source observation time.

Add constraints after the backfill validates:

- allowed scrape statuses: `running`, `success`, `failed`, `quarantined`;
- allowed workflows: `unpaid_prizes`, `instant_ticket_catalog`;
- parsed counts are nonnegative;
- a complete successful unpaid run has source time/date/hash and positive
  parsed counts;
- `finished_at >= started_at` when finished;
- SHA values match 64 lowercase hexadecimal characters;
- game ticket price is positive when present;
- overall one-in odds are greater than one when present;
- snapshot counts/values are nonnegative when present;
- tier prize amount is positive;
- tier counts are nonnegative;
- `remaining_count <= original_count`;
- `claimed_count = original_count - remaining_count`.

Add a `structure_fingerprint char(64)` to `game_snapshots`. It is the SHA-256
of a canonical serialization of sorted `(prize_amount, original_count)` pairs.
Backfill it for all snapshots. The serialization format must be fixed and
unit-tested, for example:

```text
10.00:1000000|20.00:250000|1000.00:250|...
```

Add indexes:

```text
scrape_runs(workflow, is_complete, source_observed_at DESC)
scrape_runs(source_date)
raw_source_snapshots(scrape_run_id)
game_snapshots(scrape_run_id)
game_snapshots(game_id, captured_at DESC)     -- retain/rebuild existing
game_snapshots(game_id, structure_fingerprint)
prize_tier_snapshots(game_snapshot_id, prize_amount) -- existing unique index
```

Add a partial unique index preventing a second complete successful import of
the same unpaid-prizes content hash:

```text
(workflow, source_sha256)
WHERE workflow='unpaid_prizes' AND status='success' AND is_complete
```

Do not make `source_date` unique; more than one legitimate capture per day may
exist. Current selection is by timestamp.

### Revision `0003_current_source_views`

Create `current_complete_scrape_run_v` and `current_game_snapshots_v` using the
complete-run semantics below. This revision also adds any supporting partial
indexes needed by lifecycle queries. It introduces no analytics tables.

### Revision `0004_catalog_and_metadata_attempts`

Create `game_catalog_snapshots` to normalize current retail-catalog presence:

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` | primary key |
| `scrape_run_id` | FK | complete `instant_ticket_catalog` run |
| `game_id` | FK | nullable until URL/detail mapping succeeds |
| `detail_url` | `text` | not null |
| `slug` | `text` | nullable |
| `display_name` | `text` | not null |
| `ticket_price` | `numeric(10,2)` | not null |
| `top_prize_text` | `text` | nullable raw card value |
| `page_number` | `integer` | positive |
| `card_position` | `integer` | nonnegative |
| `created_at` | `timestamptz` | not null |

Unique `(scrape_run_id, detail_url)`. Index `(game_id, scrape_run_id)` and
`(detail_url)`. A catalog scrape run's `source_sha256` is the hash of a
canonical ordered manifest of its page hashes; it may have multiple
`raw_source_snapshots` children. Complete unpaid-prizes runs continue to
require exactly one raw child.

Create `current_complete_catalog_run_v`, `current_catalog_games_v`, and
`recommendation_current_games_v`. The last view intersects mapped catalog games
with `current_game_snapshots_v` and also exposes reconciliation status through
a companion `current_game_source_reconciliation_v`.

Create a small metadata retry table rather than adding volatile crawler state
to `games`:

Create a small metadata retry table rather than adding volatile crawler state
to `games`:

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` | primary key |
| `game_id` | FK | not null |
| `attempted_at` | `timestamptz` | not null |
| `candidate_url` | `text` | nullable |
| `outcome_code` | `varchar(32)` | stable code |
| `attempt_number` | `integer` | positive |
| `next_retry_at` | `timestamptz` | nullable |
| `error_message` | `text` | nullable |

Index `(game_id, attempted_at DESC)` and `(next_retry_at)` for targeted work.
This revision may be implemented after `0003` without blocking pure analytics,
but it is required before recommendation ranks become publishable.

### Revision `0005_analytics_core`

Create the versioned derived tables below. Use `bigserial` keys for analytics
history. Fractions use `numeric(18,12)`, money/value and estimated counts use
`numeric(24,6)`, and one-in odds use `numeric(30,6)`. Do not use binary floats
in persisted calculations.

#### `analytics_model_versions`

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` | primary key |
| `model_name` | `varchar(64)` | initially `core_ticket_model` |
| `semantic_version` | `varchar(32)` | initially `1.0.0` |
| `parameters` | `jsonb` | complete immutable parameter document |
| `parameters_sha256` | `char(64)` | canonical JSON hash |
| `code_version` | `varchar(64)` | git commit or build identifier |
| `created_at` | `timestamptz` | not null |
| `approval_status` | `varchar(16)` | `experimental`, `approved`, or `rejected` |
| `approval_backtest_run_id` | FK | promotion evidence used for the decision |
| `approval_decided_at` | `timestamptz` | required for a state change |
| `approval_reason` | `text` | required auditable decision reason |

Unique: `(model_name, semantic_version)`, with at most one approved version per
model name. Model identity and parameters are immutable; only approval fields
may change. PostgreSQL permits approval only when the referenced backtest
belongs to the version, completed successfully, and passed every promotion
gate. A failed backtest rejects the version and publication views require an
explicitly approved model. Any formula, threshold, boundary, interpolation,
or confidence-rule change creates a new semantic version.

Required version-1 parameter keys include:

```text
baseline_max_prize=500
high_prize_strictly_greater_than=600
lag_primary_original_count=500
lag_exploratory_original_count=250
lag_min_snapshots=30
lag_min_span_days=30
lag_min_overlap_fraction=0.075
lag_internal_quantiles=9
lag_max_interpolation_gap_days=3
lag_min_global_games=8
bootstrap_samples=10000
bootstrap_seed=20260808
reference_min_original_count=10000
wilson_z=1.959963984540054
confidence_min_tier_n=20
confidence_information_low_boundary=5
confidence_information_moderate_boundary=10
confidence_information_high_boundary=25
source_fresh_hours=36
source_stale_error_hours=72
```

#### `analytics_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` | primary key |
| `model_version_id` | FK | not null |
| `as_of_scrape_run_id` | FK | complete source cutoff |
| `as_of_observed_at` | `timestamptz` | copied cutoff for audit/query |
| `started_at`, `finished_at` | `timestamptz` | execution timing |
| `status` | `varchar(16)` | `running`, `success`, `failed` |
| `publishable` | `boolean` | false until every publication gate passes |
| `error_message` | `text` | nullable |
| `created_at` | `timestamptz` | not null |

Unique: `(model_version_id, as_of_scrape_run_id)`. Retry a failed row
idempotently; a successful row is immutable unless an explicit `--force`
operation deletes/rebuilds its children in one transaction and records an
audit issue.

#### `analytics_lag_calibrations`

One row per analytics run:

- `analytics_run_id` unique FK;
- method and all qualification parameters copied from the model version;
- candidate, primary-qualified, exploratory, positive, and excluded game
  counts;
- global median/Q1/Q3 lag days;
- bootstrap 95% lower/upper days;
- status: `available`, `insufficient`, or `failed`;
- reason code when unavailable.

#### `analytics_lag_game_estimates`

One row per game considered by calibration:

- analytics run and game FKs;
- `eligible_primary`, `eligible_exploratory`;
- exclusion code;
- top prize amount;
- adaptive high-band ceiling;
- selected high-band original count;
- snapshot count and history span;
- common progress lower/upper/width;
- valid quantile count;
- median/Q1/Q3 game lag;
- `used_in_global`.

Unique: `(analytics_run_id, game_id)`.

#### `analytics_game_metrics`

One row per current game in the run:

- analytics run, game, and as-of game snapshot FKs;
- structure fingerprint;
- source observed time;
- baseline tier/original/remaining/claimed counts;
- baseline remaining and progress fractions;
- estimated original, sold, and remaining ticket counts;
- published overall odds;
- full-tier score coverage by count and original prize value;
- high-tier score coverage by count and original prize value;
- prize-source-current, catalog-current, and recommendation-current status plus
  catalog cutoff when available;
- data status and publishable flag.

Unique: `(analytics_run_id, game_id)`.

#### `analytics_tier_metrics`

One row per prize tier in every current game:

- analytics run, game, game snapshot, and tier snapshot FKs;
- `is_top_prize`;
- `process_group`: `baseline`, `retail_gap`, or `high`;
- `reference_method`: `leave_one_tier_out`, `current_baseline`,
  `lagged_baseline`, or `unavailable`;
- reference observation time and lag days used;
- whether the lag included the scored game;
- current and reference remaining fractions;
- observed survival fraction;
- expected reported remaining count;
- availability point estimate and Wilson lower/upper;
- lag-sensitivity availability minimum/maximum;
- launch probability and one-in odds;
- estimated current probability and one-in odds;
- equivalent current remaining count;
- confidence label and information count;
- evidence classification;
- status and exclusion reason.

Unique: `(analytics_run_id, prize_tier_snapshot_id)`.

Store copied point inputs that are necessary to reproduce a displayed number,
but retain the FK to the immutable observed row as the authority.

#### `analytics_strategy_metrics`

One row per current game containing the exact primitives defined in
`06_strategy_datasets.md`, including:

- any-win and break-even probabilities;
- exact-break-even and strict-profit probabilities;
- strict-profit excluding top;
- multiplier-threshold probabilities;
- fixed-dollar-threshold probabilities;
- adjusted EV and payout ratios, full and excluding top;
- top-prize probability and odds;
- valid target-set coverage and status for every metric family.

Unique: `(analytics_run_id, game_id)`.

#### `analytics_quality_issues`

- analytics run FK;
- stable issue code;
- severity: `info`, `warning`, `error`;
- entity type: `run`, `game`, `snapshot`, or `tier`;
- nullable entity IDs;
- short message;
- structured `details jsonb`;
- created time.

Index `(analytics_run_id, severity, code)` and `(game_id, code)`.

### Revision `0006_backtesting`

Create:

#### `analytics_backtest_runs`

- model version FK;
- cutoff range;
- horizon array/configuration;
- parameters JSON and hash;
- start/finish/status/error;
- aggregate result JSON for convenient audit.

#### `analytics_backtest_predictions`

One row per cutoff/game/tier/horizon/model variant:

- backtest run;
- cutoff and target scrape-run IDs;
- game/tier identifiers;
- horizon days;
- model variant (`aligned`, `no_lag`, `legacy`);
- inputs available at cutoff;
- predicted remaining count/fraction and interval;
- later observed remaining count/fraction;
- absolute, signed, and standardized errors;
- eligibility/exclusion code.

Index by `(backtest_run_id, horizon_days, model_variant)` and
`(game_id, prize_amount, cutoff_scrape_run_id)`.

#### `analytics_backtest_summaries`

One row per backtest run/horizon/model/tier group containing eligible count,
game count, MAE, median absolute error, bias, interval coverage, and comparison
improvement versus no-lag.

## Canonical Views

Migrations create or replace these read-only views:

### `current_complete_scrape_run_v`

Exactly one newest complete successful unpaid run ordered by
`source_observed_at DESC, id DESC`.

### `current_game_snapshots_v`

Game snapshots belonging to `current_complete_scrape_run_v`. This is the only
authoritative input for current prize-source analytics.

### `current_complete_catalog_run_v` and `current_catalog_games_v`

The newest complete catalog crawl and its mapped game entries.

### `recommendation_current_games_v`

The intersection of `current_game_snapshots_v` and
`current_catalog_games_v`. Strategy ranking views use this membership;
historical/tier analytics may retain all current prize-source games.

### `current_analytics_run_v`

The successful, publishable analytics run for the current complete source run
and active `core_ticket_model` version. It returns zero rows if source and
analytics cutoffs do not match.

### `current_game_metrics_v`, `current_tier_metrics_v`,
`current_strategy_metrics_v`

Children of `current_analytics_run_v`. They never fall back silently to an
older source cutoff.

### `current_strategy_rankings_v`

A long-form view with:

```text
analytics_run_id
game_id/game_number
ticket_price
strategy_key
metric_value
metric_status
confidence/coverage
rank_overall
rank_within_ticket_price
```

Rank only complete eligible rows whose games are in
`recommendation_current_games_v`. Use `dense_rank`, deterministic ties by game
number for display order, and no composite weights.

## Legacy-Column Transition

1. Add new analytics storage without changing old report behavior.
2. Backfill all historical cutoffs supported by the model.
3. Produce a comparison report explaining every legacy/new difference.
4. Change database-facing reports to new current views.
5. Stop nightly writes to legacy estimated columns.
6. Keep columns for one release/migration cycle with database comments naming
   the replacement.
7. Drop them only after backup/restore and report tests pass.

Never overwrite legacy values with the new formulas; that would destroy the
ability to audit the transition.

## Migration Safety Requirements

- Every revision has an explicit downgrade or documents why downgrade is data
  destructive and requires restore.
- Constraint additions use validate-after-backfill where practical.
- No migration fetches network data.
- Long backfills are separate commands, not import-time migration code.
- Migrations run first on a restored clone and in PostgreSQL CI.
- Before/after row counts and the invariant SQL are captured in the migration
  log.
- `alembic current` and `alembic heads` must show one head.
