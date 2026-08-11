# Current State and Remediation

## Existing Data Flow

The current nightly workflow is:

1. fetch and preserve an unpaid-prizes HTML file;
2. validate the page marker and minimum parsed game count;
3. parse games and prize tiers;
4. insert `scrape_runs`, `raw_source_snapshots`, `game_snapshots`, and
   `prize_tier_snapshots` rows;
5. upsert stable fields on `games`;
6. recompute provisional metrics for every stored snapshot;
7. optionally crawl the instant-ticket hub and detail pages for missing
   metadata.

The normalized source model is fundamentally usable:

- `games` is the stable game dimension keyed by `game_number`;
- `scrape_runs` records pipeline executions;
- `raw_source_snapshots` records source files and source capture times;
- `game_snapshots` records a game's aggregate values in one source run;
- `prize_tier_snapshots` records the raw tier counts in a game snapshot.

The project also has read-only reconciliation, snapshot-change, activity, and
metric reports. The new work should extend this foundation rather than replace
the parser/importer.

## Verified Strengths

As of the design cutoff:

- every aggregate original count equals the sum of its tiers;
- every aggregate remaining count equals the sum of its tiers;
- aggregate original and remaining prize values equal the tier-value sums;
- every `claimed_count` equals `original_count - remaining_count`;
- all tier counts are non-null and nonnegative;
- no remaining count exceeds its original count;
- no tier's original structure changes within a game history;
- no remaining count increases between source observations;
- no game has duplicate snapshots on one Chicago source date;
- every imported run has exactly one recorded raw source snapshot;
- all 90 imported source hashes are distinct;
- all 365 existing tests pass.

The new constraints and tests must preserve those properties.

## Defects and Required Disposition

### P0 — lifecycle/current-game selection is wrong

All 75 historical games have `games.is_active = true`, while only 57 games are
present in the latest complete unpaid-prizes snapshot. Current reports
therefore mix 18 removed/stale games into rankings.

There is a second status: whether a game is still listed in the instant-ticket
catalog. The latest stored complete hub crawl contains 53 unique offerings.
Four games on the latest unpaid-prizes list appear absent from that catalog.
An unpaid-prizes row may remain claimable/reportable after retail catalog
removal, so the two sources must not be collapsed into one flag.

Required correction:

- define `prize_source_current` as presence in the newest complete
  unpaid-prizes run ordered by source observation time;
- define `catalog_current` as mapped presence in the newest complete
  instant-ticket catalog run;
- compute source analytics for `prize_source_current` games;
- make recommendation/ranking eligibility the intersection of both statuses;
- retain source-only and catalog-only reconciliation states;
- continue synchronizing `games.is_active` only as a compatibility cache of
  `prize_source_current` during transition;
- never use `is_active` as the source of truth.

The current prize-source view must return 57 games against the cutoff database.
After catalog snapshots are normalized, the recommendation-eligible view must
return the mapped intersection and expose all mismatches for review.

### P0 — provisional remaining-ticket and EV metrics are not suitable inputs

The current implementation calculates:

```text
estimated_tickets_remaining =
  total reported unclaimed winning tickets * published overall odds
```

That calculation assumes all prize tiers deplete proportionally and are
reported on the same schedule. It is exactly the assumption the new progress
and lag models are meant to test. Large-prize reporting lag also inflates the
denominator.

The following existing fields become legacy after the new analytics tables are
available:

- `games.est_total_tickets` (the concept remains, but moves into a versioned
  calculation and should not be stored as mutable game metadata);
- `game_snapshots.estimated_tickets_remaining`;
- `game_snapshots.estimated_ev`;
- `game_snapshots.estimated_ev_excluding_top_prize`;
- `game_snapshots.estimated_payout_ratio`;
- `game_snapshots.estimated_house_edge`;
- `game_snapshots.estimated_payout_ratio_excluding_top_prize`;
- `game_snapshots.launch_ev`;
- `game_snapshots.launch_payout_ratio`;
- `game_snapshots.ev_vs_launch_ratio`.

They must not be deleted until the new backfill and comparison report pass.
Afterward, stop writing them, label them legacy in reports, and drop them only
in a later cleanup migration.

The raw rollups and these direct observed ratios remain valid:

- original and remaining count/value totals;
- `remaining_prize_value_pct`;
- `remaining_winning_tickets_pct` as a descriptive reported-count ratio;
- top-prize reported counts and depletion state.

### P0 — no migration or recovery system

The live database was evolved with `create_all` and manual SQL. There is no
Alembic history, automated database backup, or tested restore procedure.

Before any schema change:

1. create a custom-format `pg_dump` and SHA-256 manifest;
2. restore it into a disposable database;
3. run the invariant audit against the restore;
4. introduce and stamp an Alembic baseline that exactly matches the live
   schema;
5. prove a new empty database can upgrade from zero to head.

No analytics migration is allowed before that gate passes.

### P1 — source completeness and source time are implicit

`scrape_runs.status = success` does not say whether the parsed snapshot passed
relative completeness checks. `game_snapshots.captured_at` is currently the
import time, normally zero to eight seconds after the raw source capture.

Required correction:

- store the canonical source observation timestamp, Chicago source date,
  content hash, parsed counts, workflow, and completeness state on each unpaid
  source run;
- backfill all 90 historical runs from their one raw source row;
- set `game_snapshots.captured_at` to the source observation timestamp for new
  imports and backfill existing rows;
- order all history by source observation time, never later import time;
- set and test `parser_version`/pipeline version on new runs.

The source timezone is `America/Chicago`, not the host's or user's timezone.
UTC remains the stored timestamp representation.

### P1 — nightly metadata crawling is wasteful

The raw archive is approximately 906 MB and contains 11,551 files:

- 10,770 instant-ticket detail pages;
- 627 hub pages;
- 110 unpaid-prizes files;
- supporting placeholder files.

The database itself is only about 20 MB. The missing-metadata workflow walks
the hub and fetches every detail page whenever an unresolved game remains,
even though most pages are unchanged.

Required correction:

- match hub cards to missing games by normalized name and ticket price before
  fetching detail pages;
- fetch only plausible candidate detail URLs;
- store metadata-attempt state with exponential retry/backoff;
- run a complete metadata refresh weekly or when a new game appears, not on
  every successful nightly retry;
- write raw content by hash or avoid a second physical copy when unchanged;
- compress HTML after parsing;
- retain unpaid-prizes source files indefinitely, but apply a documented
  retention policy to unchanged hub/detail pages.

No existing raw file is deleted until a verified backup and retention command
are implemented.

### P1 — nightly metric computation is full-history work

`compute_snapshot_metrics` loads and recomputes all 5,128 snapshots on every
run. The new engine must:

- compute one versioned analytics result for the newest complete source run;
- scan one game's cutoff-strict history only for the fixed 24-day reference;
- make historical backfill a separate resumable command;
- use an advisory lock so overlapping systemd attempts cannot compute or
  publish concurrently.

### P1 — metadata and provenance gaps

Against the latest 57 games:

- games `7602` and `7669` lack overall odds and therefore cannot receive
  absolute probability, odds, or EV estimates;
- games `7587`, `7602`, and `7669` lack some detail-page metadata;
- all 75 `games.top_prize_amount` values are null;
- all 75 `games.end_date` values are null;
- all 90 imported runs have a null `parser_version`.

Top prize amount must be derived from each snapshot's maximum prize tier for
analytics. Missing `end_date` does not determine current status. Missing odds
must produce an explicit `missing_overall_odds` status rather than a fallback
number.

### P1 — project hardening gaps

- `.env` is mode `664`; it must be `600` because it contains a database
  credential.
- There is no dependency lock.
- There is no CI configuration.
- Tests use SQLite only, so PostgreSQL constraints, migrations, partial
  indexes, and numeric behavior are not exercised.
- Foreign-key lookup indexes are incomplete, notably on run/source joins.
- Ruff currently reports two pre-existing, mechanically fixable findings: a
  quoted forward annotation in `metrics_report.py` and import ordering in
  `tests/test_metrics_report.py`.

The target CI runs fast pure/unit tests plus PostgreSQL integration tests that
apply migrations from an empty database.

### P2 — documentation is contradictory

The README must accurately describe the implemented parsing, EV, scheduling,
and fixed high-prize adjustment behavior.

The blueprint must be linked from the README and conflicting formulas removed.

## Canonical Current-Source Definition

A source run is complete only when all of these hold:

1. workflow is `unpaid_prizes`;
2. status is `success`;
3. a raw source row and SHA-256 are present;
4. content validation passed;
5. at least 40 unique games were parsed;
6. at least one valid prize tier exists for every parsed game;
7. aggregate/tier reconciliation passes;
8. parsed game and tier counts are each at least 80% of the previous complete
   run's count, or the run is manually approved after review;
9. no duplicate game number or duplicate prize amount within a game exists.

Historical counts range from 52 to 60 games and 671 to 771 tiers, so these
guards accept known-good history while quarantining clearly partial pages.

The canonical current run is the complete unpaid run with the greatest
`source_observed_at`, breaking ties by run ID. Current games are exactly its
game snapshots.

## Canonical Catalog and Recommendation Eligibility

A catalog run is one complete crawl of all paginated instant-ticket hub pages.
It records the ordered page hashes and every unique detail URL/card. Known
detail URLs map directly to `games.source_url`; only previously unknown or
ambiguous URLs require detail-page retrieval to discover a game number.

A catalog run is complete when:

1. every discovered pagination page was fetched and parsed;
2. its manifest hash and source observation time are stored;
3. the unique-card count reconciles with the source total after documented
   source duplicates;
4. every card has a URL, display name, and ticket price;
5. unmapped cards are recorded as quality issues rather than discarded.

`catalog_current` means mapped presence in the newest complete catalog run.
`recommendation_current` means both `prize_source_current` and
`catalog_current`. A source-only game remains in historical/claim analytics but
does not receive a recommendation rank by default. A catalog-only game remains
visible to reconciliation until its first unpaid-prizes snapshot appears.

## Data-Quality Codes

Implement these stable codes; reports and tests should match the code rather
than free-form prose:

| Code | Severity | Meaning |
|---|---|---|
| `SOURCE_STALE` | warning/error | Latest complete source exceeds freshness threshold |
| `SOURCE_INCOMPLETE` | error | Global source completeness failed |
| `GAME_NOT_PRIZE_SOURCE_CURRENT` | info | Game is absent from newest complete unpaid source |
| `GAME_NOT_CATALOG_CURRENT` | info | Game is absent from newest complete catalog |
| `CATALOG_STALE` | warning/error | Latest complete catalog exceeds freshness threshold |
| `CATALOG_UNMAPPED` | warning | Catalog URL/card has no mapped game number |
| `MISSING_OVERALL_ODDS` | error | Absolute probability/EV unavailable |
| `MISSING_BASELINE` | error | No valid `<= $600` reference set |
| `BASELINE_TOO_SMALL` | warning/error | Reference original count below model minimum |
| `INVALID_TIER_COUNT` | error | Null, negative, or remaining above original |
| `ROLLUP_MISMATCH` | error | Snapshot aggregate differs from tier sum |
| `STRUCTURE_CHANGE` | error | Original tier fingerprint changed |
| `COUNT_REVERSAL` | error | Later remaining count exceeds prior count |
| `HIGH_REFERENCE_UNAVAILABLE` | info | Eligible tier uses its official-count fallback |
| `TIER_LUMPY` | info | Expected claimed/remaining observations are too few |
| `METRIC_PARTIAL` | warning | Some required tiers could not be scored |

Raw rows with an issue remain stored. Error-level issues exclude the affected
entity from current analytics; they never cause source history to be
rewritten.
