# Implementation Work Packets

## Execution Rules

These packets are deliberately ordered for a lower-effort coding agent.

- Implement one packet per branch/agent task.
- Do not combine packets unless explicitly directed.
- Read this blueprint's README plus every document referenced by the packet.
- Preserve raw observed data and unrelated working-tree changes.
- Add tests in the same packet as behavior.
- Run the packet-specific success commands and the full existing suite.
- Stop when the packet's success criteria pass; do not begin the next packet.
- Never improvise a replacement analytical formula. Persist an unavailable
  status when the specified input is missing.

Dependency flow:

```text
DB-01 -> DB-02 -> DB-03 -> AN-01 -> AN-02 -> AN-03 -> AN-04 -> AN-05
                  |                                      ^         |
                  +-> OP-01 -----------------------------+         +-> VA-01
                                                         |
                                      OP-02 <-------------+
                                                         |
                                      DB-04 <-------------+
```

`OP-01` may proceed after source lifecycle is correct. Everything else follows
the line above.

## DB-01 — Backup Gate, Alembic Baseline, and PostgreSQL CI

### Scope

- Add Alembic and its configuration.
- Create `0001_existing_schema_baseline` matching the live schema.
- Add a safe custom-format backup script and manifest.
- Add a PostgreSQL integration-test service in CI.
- Remove `create_all` from normal setup instructions, but do not remove the
  helper until all tests/migrations have transitioned.

### Expected files

```text
alembic.ini
alembic/env.py
alembic/script.py.mako
alembic/versions/0001_existing_schema_baseline.py
scripts/backup_database.py
scripts/verify_database_restore.py
tests/postgres/test_migration_smoke.py
.github/workflows/ci.yml
README.md
pyproject.toml / lock file
```

### Required behavior

- `backup_database.py` uses an explicit target directory, custom format,
  restrictive permissions, atomic rename, SHA-256 manifest, migration
  revision, and row counts.
- It has `--dry-run` and refuses an existing target.
- CI upgrades an empty PostgreSQL database to head and runs integration tests.
- The existing database is stamped only through documented manual steps; no
  test automatically stamps a nonempty unknown schema.

### Success criteria

- A fresh PostgreSQL database upgrades from zero to `0001`.
- Schema tables/columns/indexes match SQLAlchemy metadata and the documented
  baseline.
- A development backup restores into a disposable database and all audit
  queries return expected values.
- `alembic heads` reports one head.
- `pytest` and Ruff pass.
- No production/development data row is modified by the packet itself.

## DB-02 — Source Provenance, Constraints, and Canonical Time

### Scope

Implement revision `0002_source_provenance_and_constraints`, source-run
backfill, structure fingerprints, and importer changes from the schema design.

### Expected files

```text
alembic/versions/0002_source_provenance_and_constraints.py
src/illinois_lottery_tracker/models.py
src/illinois_lottery_tracker/importer.py
src/illinois_lottery_tracker/pipeline.py
src/illinois_lottery_tracker/source_quality.py
tests/test_source_quality.py
tests/postgres/test_source_constraints.py
scripts/audit_source_data.py
```

### Required behavior

- Canonical source date is `America/Chicago`; timestamps are UTC-aware.
- Existing 90 runs backfill from raw source time/hash and child counts.
- `game_snapshots.captured_at` becomes the source observation time.
- New complete imports populate every provenance field and pipeline version.
- Invalid count rows and duplicate complete hashes are rejected by PostgreSQL.
- Structure fingerprint serialization is deterministic across Python and
  PostgreSQL fixtures.
- The audit command is read-only and has text plus machine-readable JSON
  output.

### Success criteria

- Restored historical data upgrades with 90 complete runs and unchanged
  game/tier row counts.
- Historical source dates remain 90 distinct days with the two documented
  gaps.
- All existing reconciliation invariants return zero failures.
- Constraint tests prove each invalid case is rejected.
- Importing a valid fixture remains idempotent.
- Full tests and Ruff pass.

## DB-03 — Complete-Run and Current-Game Semantics

### Scope

Implement unpaid-source completeness validation, canonical current
prize-source views, compatibility `is_active` synchronization, and stale-source
states. Catalog membership is added in OP-01.

### Expected files

```text
alembic/versions/0003_current_source_views.py
src/illinois_lottery_tracker/source_quality.py
src/illinois_lottery_tracker/lifecycle.py
src/illinois_lottery_tracker/pipeline.py
src/illinois_lottery_tracker/metrics_report.py
src/illinois_lottery_tracker/snapshot_changes.py
tests/test_lifecycle.py
tests/postgres/test_current_views.py
```

### Required behavior

- Implement absolute and 80%-of-prior completeness checks.
- A quarantined newer run never replaces the prior complete current run.
- `current_complete_scrape_run_v` returns exactly one row or none.
- `current_game_snapshots_v` derives membership from that row.
- On complete import, synchronize `games.is_active` for compatibility in the
  same transaction.
- Current reports use the view, not latest-per-active-game fallback.
- Fresh/stale states use source observation age and documented thresholds.

### Success criteria

- Against the cutoff restore, current views return 57 games and 738 tiers.
- The 18 absent games are not returned even if their compatibility flag starts
  true.
- A fixture with a partial newest run continues to return the previous run.
- Legitimate game removal/addition fixtures update current membership.
- Reports identify source cutoff and never mix snapshot dates.
- Full tests and Ruff pass.

## OP-01 — Targeted Metadata and Raw-Archive Control

### Scope

Normalize catalog snapshots, stop full daily detail crawling, add candidate
matching/retry state, and add a non-destructive raw storage
audit/deduplication design implementation.

### Expected files

```text
alembic/versions/0004_catalog_and_metadata_attempts.py
src/illinois_lottery_tracker/metadata_backfill.py
src/illinois_lottery_tracker/catalog.py
src/illinois_lottery_tracker/raw_collector.py
src/illinois_lottery_tracker/models.py
scripts/audit_raw_archive.py
scripts/maintain_raw_archive.py
tests/test_metadata_backfill.py
tests/test_raw_collector.py
tests/test_raw_archive.py
```

### Required behavior

- Match normalized hub name plus ticket price before detail fetch.
- Store one complete catalog run with multiple page hashes and one normalized
  entry per unique detail URL.
- Map known URLs without refetching their detail pages and fetch only unknown
  or ambiguous candidates.
- Create current catalog, recommendation intersection, and source
  reconciliation views.
- Fetch only plausible candidates for missing games.
- Persist 1/3/7/30-day retry state.
- Support weekly full refresh separately from targeted nightly work.
- Audit duplicate content and projected savings without deleting.
- Maintenance defaults to dry-run, requires an explicit validated root, writes
  a manifest, and never touches unpaid-prizes history under the detail-page
  retention rule.

### Success criteria

- A fixture with one missing game fetches only its candidate page, not every
  discovered detail URL.
- The latest cutoff hub fixture produces 53 unique catalog entries and exposes
  source-only/catalog-only reconciliation explicitly.
- Retry/backoff prevents a second premature attempt.
- Ambiguous matches write an issue and fetch no arbitrary page.
- Raw audit reports category/file/byte/hash counts.
- No existing raw file is removed in this packet.
- Full tests and Ruff pass.

## AN-01 — Pure Analytical Primitives

### Scope

Create the pure Decimal-based analytics package and implement all deterministic
formulas except database persistence and historical lag fitting.

### Expected files

```text
src/illinois_lottery_tracker/analytics/__init__.py
src/illinois_lottery_tracker/analytics/types.py
src/illinois_lottery_tracker/analytics/progress.py
src/illinois_lottery_tracker/analytics/tiers.py
src/illinois_lottery_tracker/analytics/confidence.py
src/illinois_lottery_tracker/analytics/strategies.py
tests/analytics/test_progress.py
tests/analytics/test_tiers.py
tests/analytics/test_confidence.py
tests/analytics/test_strategies.py
```

### Required behavior

- Implement the exact boundaries and equations in the analytical spec.
- Use `Decimal` for persisted-result math; no float conversion in core
  probability/value calculations.
- Implement leave-one-tier-out references and explicit unavailable reasons.
- Implement high-tier scoring when a lagged reference is supplied, but do not
  fit lag yet.
- Implement Wilson intervals, information count, confidence, evidence, and
  lag sensitivity.
- Implement strategy sums from already-scored tier probabilities.

### Success criteria

- Every deterministic vector in the analytical spec passes at documented
  precision.
- Boundary tests cover exactly `$500` and `$600`.
- Removing a tier from its own baseline is asserted explicitly.
- Missing odds produce relative scores but null absolute outputs.
- No function accesses a database, filesystem, clock, or network.
- Full tests and Ruff pass.

## AN-02 — Versioned Analytics Schema and Persistence

### Scope

Create migration `0005_analytics_core`, SQLAlchemy analytics models, current
analytics views, and idempotent persistence scaffolding.

### Expected files

```text
alembic/versions/0005_analytics_core.py
src/illinois_lottery_tracker/analytics_models.py
src/illinois_lottery_tracker/analytics/persistence.py
tests/postgres/test_analytics_schema.py
tests/postgres/test_analytics_persistence.py
```

### Required behavior

- Implement every core analytics table/constraint/index in the schema design.
- Seed model `core_ticket_model` version `1.0.0` with canonical JSON and hash.
- Successful model-version rows are immutable.
- Persistence is idempotent by model/cutoff.
- A run becomes current only when success, publishable, and tied to the current
  complete source run.
- Failed/running rows never appear in current views.

### Success criteria

- Empty PostgreSQL upgrades to head.
- Re-running persistence produces no duplicate run or child rows.
- Current-view cutoff mismatch returns zero rows.
- Numeric columns round-trip exact Decimal fixture values.
- Cascade/restrict behavior matches the documented ownership model.
- Full tests and Ruff pass.

## AN-03 — Baseline and Regular-Tier Analytics Job

### Scope

Compute/persist current game progress and tier results through `$600`, plus
quality issues. High tiers remain explicitly pending.

### Expected files

```text
src/illinois_lottery_tracker/analytics/service.py
src/illinois_lottery_tracker/analytics/queries.py
src/illinois_lottery_tracker/analytics/persistence.py
scripts/compute_analytics.py
scripts/report_analytics.py
tests/analytics/test_service_regular.py
tests/postgres/test_compute_analytics_regular.py
tests/test_script_help.py
```

### Required behavior

- Input games come only from current complete views.
- Calculate `T0`, full baseline progress, context ticket estimates, and
  leave-one-tier-out/current-baseline tier scores.
- Missing odds retain relative availability and issue codes, with absolute
  metrics null.
- Persist one row for every current tier, including high tiers with
  `LAG_NOT_AVAILABLE` until AN-04/AN-05.
- CLI supports cutoff, model version, dry-run, and force rules.

### Success criteria

- Cutoff restore produces 57 game metric rows and 738 tier metric rows.
- Every `<= $500` tier uses leave-one-tier-out; `$500 < prize <= $600` uses full
  baseline.
- Games `7602` and `7669` have null absolute outputs and explicit issues.
- No stale game appears.
- Running twice is idempotent.
- Full tests and Ruff pass.

## AN-04 — Adaptive Lag Calibration

### Scope

Implement historical curves, adaptive band selection, interpolation,
qualification, equal-game aggregation, bootstrap interval, and persisted
calibration audit rows.

### Expected files

```text
src/illinois_lottery_tracker/analytics/lag.py
src/illinois_lottery_tracker/analytics/queries.py
src/illinois_lottery_tracker/analytics/service.py
scripts/calibrate_claim_lag.py
tests/analytics/test_lag.py
tests/postgres/test_lag_calibration.py
```

### Required behavior

- Implement the specification verbatim: top exclusion, strict `>600`, adaptive
  count 500, 30 snapshots/days, 7.5-point overlap, nine internal quantiles,
  three-day gap, equal-game medians, deterministic bootstrap.
- Store every candidate and exact exclusion reason.
- Implement exploratory 250 results separately.
- Implement leave-one-game-out lag retrieval.
- No future source run may enter an as-of calibration query.

### Success criteria

- Synthetic five-day shift returns five days within tolerance.
- Gap/extrapolation/reversal/structure/top exclusions have focused tests.
- Against the cutoff restore, the primary method returns nine qualifying,
  nine positive games and a median approximately `24.21` days; allowable
  tolerance is `0.05` day.
- Cutoff aggregate Q1/Q3 and bootstrap bounds match the analytical spec within
  `0.10` day.
- Query-level no-look-ahead test passes.
- Full tests and Ruff pass.

## AN-05 — High-Tier Scoring, Confidence, and Strategy Metrics

### Scope

Use AN-04 calibration to score every `> $600` tier, including top tiers with
lumpy labels, then populate strategy metrics and ranking views.

### Expected files

```text
src/illinois_lottery_tracker/analytics/service.py
src/illinois_lottery_tracker/analytics/strategies.py
src/illinois_lottery_tracker/analytics/persistence.py
scripts/report_analytics.py
tests/analytics/test_service_high.py
tests/analytics/test_strategy_metrics.py
tests/postgres/test_strategy_rankings.py
```

### Required behavior

- Interpolate the same game's full baseline at `t-D`; never extrapolate.
- Score all high tiers with leave-one-game-out/global lag as specified.
- Persist expected reported count, availability, current probability/odds,
  equivalent count, Wilson interval, confidence, evidence, and lag sensitivity.
- Populate every strategy primitive/key in the strategy dataset document.
- Rank complete rows in the current prize-source/catalog intersection only,
  overall and within ticket price.
- Preserve raw top counts next to estimates.

### Success criteria

- High-tier numeric test vector returns availability `1.25`, one-in `16,000`,
  and equivalent count `75`.
- A new game without `t-D` history is explicitly unavailable/partial.
- A small top tier is scored but classified lumpy and never calibrates lag.
- Strategy reconciliation equations pass for every seeded game.
- No partial metric receives a rank.
- A prize-source-only game retains analytics but receives no recommendation
  rank.
- Full tests and Ruff pass.

## VA-01 — Walk-Forward Backtesting and Promotion Report

### Scope

Create migration `0006_backtesting`, walk-forward prediction storage, aligned
versus no-lag/legacy comparisons, and model-promotion reports.

### Expected files

```text
alembic/versions/0006_backtesting.py
src/illinois_lottery_tracker/analytics_models.py
src/illinois_lottery_tracker/analytics/backtest.py
scripts/backtest_analytics.py
tests/analytics/test_backtest.py
tests/postgres/test_backtest_no_leakage.py
```

### Required behavior

- Implement 7/14/30-day horizons and plus/minus-one-day target selection.
- Refit/use only information available at each cutoff.
- Store eligible and excluded predictions.
- Implement conditional depletion equations and all three model variants.
- Produce summary metrics and promotion-gate pass/fail reasons.
- A threshold/model change requires a new model version.

### Success criteria

- A deliberately future-leaking fixture fails the no-look-ahead guard.
- Synthetic aligned data favors the aligned model; synthetic zero-lag data
  does not falsely promote lag.
- Re-running a backtest is idempotent.
- The real 90-day backtest completes and records sample sizes even if promotion
  gates fail.
- Full tests and Ruff pass.

## OP-02 — Nightly Analytics Orchestration, Backfill, and Status Reports

### Scope

Integrate source import and analytics as separately committed stages, add
advisory locking, resumable analytics backfill, freshness/status reporting,
and systemd updates.

### Expected files

```text
scripts/run_nightly_unpaid_prizes_pipeline.py
scripts/backfill_analytics.py
scripts/report_analytics.py
src/illinois_lottery_tracker/pipeline.py
deploy/systemd/illinois-lottery-nightly.service
deploy/systemd/illinois-lottery-nightly.timer
deploy/SYSTEMD_SETUP.md
tests/test_pipeline.py
tests/test_backfill_analytics.py
tests/test_activity_report.py
```

### Required behavior

- Network collection holds no open DB transaction.
- Advisory lock prevents concurrent orchestration.
- Source commit survives analytics failure.
- Current analytics never silently lag the current source cutoff.
- Backfill is cutoff-ordered, resumable, idempotent, and summarized.
- Timer/source-date documentation uses America/Chicago explicitly.
- Nightly status includes every field listed in the operations document.

### Success criteria

- Concurrent-run fixture produces one worker and one clean skip.
- Analytics-failure fixture preserves source rows and publishes no mismatched
  analytics.
- Backfill resume continues after an injected failed cutoff.
- At current scale, one analytics run is under 60 seconds and 90-cutoff
  backfill is under 15 minutes on the development machine.
- Full tests and Ruff pass.

## DB-04 — Legacy Metric Cutover and Documentation Reconciliation

### Scope

After AN-05 and VA-01 pass, redirect database-facing reports to new views,
label/stop legacy metric writes, and reconcile project documentation.

### Expected files

```text
src/illinois_lottery_tracker/metrics.py
src/illinois_lottery_tracker/metrics_report.py
scripts/compute_metrics.py
scripts/report_metrics.py
README.md
docs/mail_in_prize_lag_model.md
docs/project-brief.md
docs/project-synopses.md
tests/test_metrics.py
tests/test_metrics_report.py
```

### Required behavior

- Produce a one-time legacy/new comparison report before cutover.
- Nightly stops writing legacy estimated columns.
- Existing commands either redirect with explicit new names or print a clear
  deprecation message; no silent formula change under an old label.
- Old lag note is marked historical/superseded.
- README reflects actual pipeline capabilities and migration setup.
- Do not drop legacy columns yet.

### Success criteria

- No current ranking/report query reads a legacy estimated column.
- Current reports use one source/model cutoff and 57 current games at the
  design restore.
- Comparison report is archived with model version/cutoff.
- Documentation contains no active contradictory `$600` boundary or legacy
  denominator instruction.
- Full tests and Ruff pass.

## Final Release Gate

The database-centric phase is complete only when:

- migrations, backup, and verified restore work;
- current source membership is correct;
- catalog membership and recommendation intersection are normalized;
- source invariants and PostgreSQL CI pass;
- baseline, regular, lag, high-tier, confidence, and strategy formulas have
  deterministic tests;
- backtesting has run and records promotion status honestly;
- nightly source and analytics stages are atomic and observable;
- reports use the versioned current views;
- legacy calculations are no longer publication inputs;
- no API, UI, login, or personal-play feature was added.
