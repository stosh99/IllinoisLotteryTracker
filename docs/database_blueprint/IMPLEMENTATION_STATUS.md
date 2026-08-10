# Database Blueprint Implementation Status

This log records the packet gates executed while implementing the canonical
database blueprint. It is an implementation record, not a replacement for the
specification or test suite.

## DB-01 — Complete (2026-08-08)

- Added Alembic configuration and the exact five-table pre-migration baseline.
- Added PostgreSQL CI and migration smoke tests.
- Added atomic custom-format backup and guarded disposable-restore tools.
- Removed `create_all` from normal setup instructions and documented the
  manual pre-Alembic stamp gate.
- Added backup safety/dry-run tests and fixed the two pre-existing Ruff issues.

Gate evidence:

- `alembic heads`: one head, `0001_existing_schema_baseline`.
- Empty disposable PostgreSQL upgrade: passed.
- ORM table/column comparison on disposable PostgreSQL: 2 tests passed.
- Custom-format backup, SHA-256 manifest, restrictive permissions, disposable
  restore, revision check, row-count check, and baseline SQL audit: passed.
- Full local suite: 370 passed, 2 PostgreSQL tests skipped without
  `TEST_DATABASE_URL`; those same 2 tests passed against the disposable DB.
- Ruff: passed.
- Development data rows modified: zero.

## DB-02 — Complete (2026-08-08)

- Added canonical workflow, source timestamp/date/hash, completeness, parsed
  counts, pipeline-version, and manual-approval provenance.
- Backfilled all historical runs and changed snapshot time semantics to the
  source observation timestamp.
- Added deterministic tier-structure fingerprints shared by Python and
  PostgreSQL.
- Added PostgreSQL checks and indexes for source status, hashes, dates, game
  metadata, snapshot totals, and tier count identities.
- Updated the importer/pipeline to validate source structure, populate every
  provenance field, and reject immutable duplicate complete content.
- Added a read-only text/JSON source audit command.

Gate evidence:

- Empty PostgreSQL upgrade through revision `0002`: passed.
- PostgreSQL constraint/fingerprint suite: 6 passed.
- Pre-migration development backup restored into a disposable database; its
  five-table schema matched the pre-change ORM before the disposable copy was
  stamped.
- Historical upgrade retained 90 runs, 5,128 snapshots, and 65,911 tiers.
- All 90 historical runs are complete across 90 source dates; documented gaps
  remain 2026-05-14 and 2026-07-23.
- Source audit: zero tier, rollup, fingerprint, provenance, duplicate-hash, or
  captured-time failures.
- Full local suite: 381 passed, 6 PostgreSQL-only tests skipped locally; all
  PostgreSQL tests passed against disposable databases.
- Ruff: passed.
- Development data rows modified: zero.

## DB-03 — Complete (2026-08-08)

- Added absolute and 80%-of-prior completeness decisions with narrowly scoped,
  auditable manual approval.
- Persist incomplete parsed sources as quarantined provenance with no game/tier
  children; they cannot replace the prior complete cutoff.
- Added canonical latest-complete-run and current-game PostgreSQL views.
- Synchronized `games.is_active` as a compatibility cache during migration and
  each complete import.
- Redirected the legacy metrics report and latest snapshot comparisons to one
  complete source cutoff on PostgreSQL.
- Added source freshness states at 36/72-hour boundaries.

Gate evidence:

- Empty PostgreSQL upgrade through revision `0003`: passed.
- PostgreSQL migration/constraint/current-view suite: 8 passed.
- Historical disposable upgrade exposes exactly 1 current run, 57 current
  games, and 738 current tiers.
- Compatibility cache contains 57 active games with zero view mismatches; the
  18 absent historical games are excluded.
- Database-facing metrics report returns 57 games from exactly one source run.
- Quarantined-newer and legitimate membership-change fixtures: passed.
- Full local suite: 388 passed, 8 PostgreSQL-only tests skipped locally; all 8
  passed against fresh and restored PostgreSQL databases.
- Source audit and Ruff: passed.
- Development data rows modified: zero.

## OP-01 — Complete (2026-08-08)

- Added normalized, multi-page catalog runs with page-level raw hashes and one
  row per unique retail detail URL.
- Added URL-first and normalized-name-plus-price mapping, canonical catalog,
  recommendation-intersection, and source-reconciliation views.
- Replaced daily full detail crawling with due-only plausible candidate
  fetching, explicit ambiguous/no-candidate outcomes, and persisted
  1/3/7/30-day retry state; weekly full refresh remains a separate CLI mode.
- Changed new raw collection to immutable content-addressed blobs with
  per-capture hard links and collision-safe filenames.
- Added category/hash/byte/projected-savings audit reporting and guarded,
  explicit-root maintenance manifests. Maintenance is non-destructive and
  excludes unpaid-prizes history from every proposed retention action.

Gate evidence:

- Targeted fixture with one missing game fetched exactly one of two catalog
  candidates; ambiguous matches fetched zero pages and persisted an issue.
- Retry fixture prevented a premature second attempt.
- Real 2026-08-08 hub captures produced 3 pages (20/20/13), 53 unique entries,
  53 mapped games, and zero unmapped/ambiguous entries.
- Restored 90-run history reconciliation: 53 source+catalog, 4 source-only, 0
  catalog-only, and 53 recommendation-current games. Source history remained
  90 runs, 5,128 game snapshots, 65,911 tiers, 57 current games, and 738
  current tiers.
- Raw audit inventoried 11,551 existing files and 931,961,706 bytes with 8,035
  unique hashes and 271,134,894 projected duplicate bytes. Dry-run maintenance
  wrote 562 duplicate groups, deleted/replaced zero files, and retained all 110
  unpaid-prizes captures indefinitely.
- Empty PostgreSQL migration and integration suite: 9 passed.
- Full local suite: 396 passed, 9 PostgreSQL-only tests skipped locally; all 9
  passed against the disposable PostgreSQL database.
- Source audit, Ruff, and diff whitespace checks: passed.
- Development data rows and existing raw files modified or removed: zero.

## AN-01 — Complete (2026-08-08)

- Added a pure analytics package built exclusively on immutable inputs and
  `Decimal` math.
- Implemented count-weighted `<= $500` game progress, estimated ticket totals,
  exact `$500`/`$600` grouping, leave-one-tier-out regular scoring, supplied
  lag-reference high-tier scoring, depleted and unavailable states, and
  missing-odds relative-only results.
- Implemented Wilson availability intervals, information count, deterministic
  confidence/evidence labels, and Q1/median/Q3 lag sensitivity ranges.
- Added transparent probability/EV aggregation with original-count and
  original-prize-value coverage plus complete/partial/unavailable/not-applicable
  states.

Gate evidence:

- Canonical regular vector: availability 1.375, probability 0.034375, and
  current one-in 29.090909.
- Canonical high vector: expected count 80, availability 1.25, probability
  0.0000625, one-in 16,000, and equivalent count 75.
- Exact `$500` and `$600` boundary, leave-one-out, missing odds, depleted tier,
  confidence thresholds, Wilson/evidence, sensitivity, and partial-coverage
  tests: 17 passed.
- Analytics package contains no database, filesystem, clock, network, or float
  dependency.
- Full local suite: 413 passed, 9 PostgreSQL-only tests skipped locally.
- Ruff and diff whitespace checks: passed.

## AN-02 — Complete (2026-08-08)

- Added all versioned core analytics tables for model definitions, runs, lag
  calibration audit, game/tier metrics, strategy primitives, and quality
  issues using PostgreSQL exact numerics.
- Seeded immutable `core_ticket_model` `1.0.0` with the complete canonical
  parameter document and deterministic SHA-256.
- Added database ownership constraints and triggers that preserve model
  versions and published successful analytics runs while cascading disposable derived
  children only from non-successful runs.
- Added idempotent run acquisition, failed-run retry, quality-issue insertion,
  and success/failure finalization scaffolding.
- Added cutoff-strict current analytics/game/tier/strategy views; running,
  failed, non-publishable, and older-cutoff results never fall through.

Gate evidence:

- Empty PostgreSQL zero-to-head upgrade through `0005`: passed.
- PostgreSQL schema/persistence suite: 15 passed, including exact
  `numeric(18,12)` and `numeric(30,6)` Decimal round trips, immutable seed and
  successful-run checks, idempotent run/child behavior, retry behavior,
  cascade/restrict ownership, and cutoff mismatch.
- Restored 90-run history upgraded cleanly with one seeded model, zero derived
  runs, 57 current games, and 738 current tiers; every source audit invariant
  remained zero.
- Full local suite: 413 passed, 15 PostgreSQL-only tests skipped locally; all
  15 passed against the disposable PostgreSQL database.
- One Alembic head, Ruff, and diff whitespace checks: passed.

## AN-03 — Complete (2026-08-08)

- Added cutoff-strict current-source queries and a versioned computation
  service for game progress and every tier through `$600`.
- Persisted count-weighted baseline totals, progress, estimated ticket context,
  leave-one-tier-out baseline scores, current-baseline retail-gap scores,
  Wilson intervals, confidence/evidence, coverage, and quality issues.
- Persisted every high tier as explicitly unavailable with
  `LAG_NOT_AVAILABLE`; no unadjusted substitute is used.
- Added idempotent successful-run reuse, failed-run child cleanup, immutable
  force rules, and compute/report CLIs with cutoff, model-version, and dry-run
  controls.

Gate evidence:

- Cutoff restore computed exactly 57 game rows and 738 tier rows: 537 regular
  scores and 201 explicitly pending high-tier rows.
- Every baseline tier uses `leave_one_tier_out`; every retail-gap tier uses
  `current_baseline` (zero mismatches).
- Games `7602` and `7669` retain relative availability but have null estimated
  ticket/probability outputs and `MISSING_OVERALL_ODDS` issues.
- A second computation reused analytics run 1 with unchanged 57/738 child
  counts.
- Focused SQLite service and PostgreSQL computation fixtures passed; CLI help
  and explicit report output passed.
- Full local suite: 414 passed, 16 PostgreSQL-only tests skipped locally; the
  AN-03 PostgreSQL test passed against the restored disposable database.
- Ruff and diff whitespace checks: passed.

## AN-04 — Complete (2026-08-08)

- Added strict-`> $600` adaptive band selection by original winner count with
  unconditional maximum/top-tier exclusion and separate 500/250 primary and
  exploratory eligibility.
- Added cutoff-bounded historical curve queries with complete-source,
  stable-structure, ordered-time, and no-look-ahead guarantees.
- Implemented 30-snapshot/day qualification, reversal checks, 7.5-point common
  progress, nine internal crossings, three-day interpolation limit,
  equal-game medians, Q1/Q3, deterministic 10,000-resample bootstrap, and
  leave-one-game-out lag retrieval.
- Persisted one auditable candidate row per current game plus the full
  calibration parameter/count/result record; reruns reuse it idempotently.

Gate evidence:

- Synthetic five-day horizontal shift returned exactly five days; top-band,
  four-day-gap, no-extrapolation, reversal, bootstrap, and leave-one-game-out
  tests passed.
- PostgreSQL synthetic cutoff query excluded its future observation and
  persisted the candidate/qualification audit row.
- Restored cutoff result exactly matched the blueprint design check: 9 primary
  games, 9 positive, median `24.2072` days, Q1/Q3 `20.2099`/`29.0017`, and
  bootstrap 95% `19.8971`–`29.4598` days.
- A second calibration reused the same stored result without duplicate rows.
- Full local suite: 421 passed, 17 PostgreSQL-only tests skipped locally; the
  focused AN-04 PostgreSQL test passed against the restored database.
- Ruff and diff whitespace checks: passed.

## AN-05 — Complete (2026-08-08)

- Added same-game, cutoff-bounded interpolation at each game’s
  leave-one-game-out/global lag with no extrapolation and the three-day gap
  rule.
- Scored every eligible `> $600` tier, including top tiers, with expected and
  equivalent counts, availability/probability/odds, Wilson interval,
  information/confidence/evidence, and Q1/point/Q3 lag sensitivity ranges.
- Preserved new-game/no-history tiers as explicit
  `LAG_REFERENCE_NOT_AVAILABLE` partial results and retained raw top counts.
- Populated all player-style probability, one-in, EV, payout/house-edge,
  multiplier, fixed-dollar, top-prize, coverage, confidence, and status
  primitives for every current source game.
- Added cutoff-strict long-form dense ranking views that include only complete
  metrics in the current mapped source/catalog intersection. The full compute
  command now runs regular scoring, calibration, high scoring, strategy
  aggregation, and publication atomically.

Gate evidence:

- Canonical high vector remains availability 1.25, one-in 16,000, equivalent
  count 75; synthetic service scored top tiers while labeling small tops
  `lumpy`, and kept a no-history game partial.
- Restored cutoff: 182 of 201 high tiers scored (173 available, 9 depleted),
  19 explicitly unavailable; 57 strategy rows persisted.
- Top-tier confidence: 43 lumpy, with raw original/remaining counts retained.
- Strategy audits returned zero probability, full/ex-top EV, exact top
  subtraction, launch-probability, and bounds failures at persisted Decimal
  tolerance.
- Ranking audits returned zero partial-ranked and zero source-only-ranked rows;
  the nine required ranking keys are exposed, with 49 fully eligible games for
  the complete full/ex-top value and profit families at this cutoff.
- Fully published rerun remained one run, 57 games, 738 tiers, one calibration,
  and 57 strategies.
- Full local suite: 424 passed, 18 PostgreSQL-only tests skipped locally; all
  18 passed on a fresh zero-to-head PostgreSQL database.
- Ruff and diff whitespace checks: passed.

## VA-01 — Complete (2026-08-08)

- Added versioned backtest runs, immutable cutoff/game/tier/horizon/variant
  prediction facts, grouped summaries, and persisted promotion reports.
- Implemented 7/14/30-day targets using the nearest complete observation
  within plus or minus one day, preserving every missing target and other
  exclusion as an auditable row.
- Enforced two-phase evaluation: cutoff features and cutoff-refitted
  leave-one-game-out lag are frozen and checked before target rows are read.
- Implemented conditional-depletion predictions for aligned, no-lag, and
  legacy all-winner-denominator variants, Decimal error/interval measures,
  confidence, price, process, and evidence-cohort summaries.
- Used paired identical cutoff/game/tier/horizon rows for lag-versus-no-lag
  comparisons, preventing selection bias from the larger no-lag population.
- Added explicit promotion gates whose failure retains experimental results
  and whose parameter identity prevents silent threshold reuse.

Gate evidence:

- Deliberate future-feature input raised `NO_LOOKAHEAD_VIOLATION`; the restored
  result had zero persisted cutoff timestamps after their authoritative run.
- Synthetic aligned data favored aligned, while synthetic zero-lag data did
  not falsely favor lag; exact target tolerance and reference-reversal tests
  passed.
- Restored 90-day history completed 60 cutoffs and stored 297,264 predictions:
  182,788 eligible and 114,476 explicitly excluded, plus 142 summary rows.
- The honest promotion result is `failed`: the paired held-out median
  improvement is `-17.99%`, 14-day paired MAE improvement is `-13.21%`, and
  no eligible aligned 30-day comparison exists. The latest cutoff still has
  9/9 positive primary lag games, positive bootstrap lower bound, and maximum
  leave-one-out influence of 1.43 days.
- Re-running reused the same successful backtest and retained identical row
  counts.
- Fresh PostgreSQL zero-to-head migration and all 19 integration tests passed.
- Full local suite: 430 passed, 19 PostgreSQL-only tests skipped locally; Ruff,
  one-head, and diff whitespace checks passed.

## OP-02 — Complete (2026-08-08)

- Added a project-specific PostgreSQL session advisory lock on an autocommit
  connection; concurrent orchestration exits zero as `already_running`, and
  network collection holds no open database transaction.
- Separated source import and versioned analytics into independently committed
  stages. Analytics exceptions retain the complete source, persist a failed
  non-publishable analytics run, and cannot make an older cutoff appear current.
- Added ascending, one-cutoff-per-transaction analytics backfill with date
  bounds, dry-run, failed-run resume/force behavior, idempotent successful-run
  skipping, nonzero failure exit, and final counts.
- Corrected early-history behavior so insufficient lag calibration publishes
  explicit unavailable high tiers and partial strategies rather than failing
  an otherwise valid source/progress analytics run.
- Added a complete JSON nightly status surface for source/catalog age and
  hashes, parsed/current counts, membership changes/reconciliation, metadata
  misses, model/cutoff, lag audit, scored/partial/unavailable counts, quality
  issues, stage timings, backup/restore ages, and alerts.
- Updated systemd to explicit `America/Chicago` schedules, documented resumable
  repair and stage isolation, added a paginated daily catalog stage whose
  collection occurs outside its separate transaction, removed metadata network
  work from the nightly database transaction, and changed `.env` permissions
  from 664 to 600.

Gate evidence:

- SQLite and PostgreSQL concurrent-lock fixtures each produced one worker and
  one clean skip, followed by successful acquisition after release.
- Injected analytics failure preserved the committed complete source and
  persisted only a failed, non-publishable matching analytics row.
- Injected cutoff failure resumed only the failed cutoff and skipped two
  independently committed successes; a non-resume run skipped the failed row.
- Restored history completed all 90 analytics cutoffs. The discovery/fix/resume
  sequence performed more work than a clean run yet finished in 419.48 seconds,
  below the 15-minute gate; a fully idempotent rerun skipped 90 in 1.58 seconds.
- A new same-parameter latest-cutoff performance run completed full regular,
  lag, high-tier, and strategy analytics in 8.57 seconds, below 60 seconds.
- Nightly status against restored history returned 57 games, 738 tiers, 53
  mapped catalog games, 4 source-only games, 3 metadata misses, full lag and
  quality counts, fresh source/catalog states, and explicit unknown protection
  alerts when no backup directory was supplied.
- `systemd-analyze verify` passed. Full local suite: 436 passed, 21 PostgreSQL
  tests skipped locally; all 21 passed on PostgreSQL. Ruff and diff whitespace
  checks passed.

## DB-04 — Complete (2026-08-08)

- Changed source import/nightly metric computation to observed-ratio-only mode;
  it neither writes nor clears any retained legacy estimated column.
- Kept explicit legacy formula functions for transition tests and placed their
  CLI writes behind `compute_metrics.py --legacy` with a superseded label.
- Disabled `report_metrics.py` with a clear replacement message. Current
  database reporting and ranking read only exact source/model analytics views.
- Added migration `0007_legacy_metric_comments`, labeling all ten retained
  legacy game/snapshot columns with their versioned replacements without
  dropping or overwriting historical values.
- Added a reproducible one-time comparison command and archived the 57-game
  `core_ticket_model 1.0.0`/source-run-91 result in
  `legacy_comparison_1.0.0_2026-08-08.md`.
- Reconciled README, project brief/synopsis, systemd instructions, and the
  superseded lag note with the implemented <=$500 / $500-$600 / strict >$600
  model, versioned analytics, failed promotion result, and current command
  surface.

Gate evidence:

- Comparison coverage was 55 paired games for absolute metrics. Median new
  minus legacy full EV was `-0.020935`; mean absolute full-EV difference was
  `0.139955`, demonstrating why the formulas were not silently overwritten.
- An observed-only unit fixture preserved sentinel legacy values while
  updating direct reported ratios; a pipeline fixture with available odds
  wrote zero legacy EV rows.
- Restored current analytics/status returned one exact model/source cutoff and
  57 games. Current value rankings returned 49 complete recommendation-current
  games and no legacy report query remained enabled.
- Warm PostgreSQL execution times were 1.16 ms for the current 57-game/738-tier
  dataset, 5.31 ms for one game's 90-day tier history, and 6.93 ms for a
  current strategy ranking, all below their 250/100/250 ms gates.
- All retained-column database comments were present. Full local suite: 438
  passed, 21 PostgreSQL tests skipped locally; all 21 passed on PostgreSQL.
  One Alembic head, Ruff, and diff whitespace checks passed.

## Final Validation Gate — Complete (2026-08-08)

- Completed every packet in the required order and retained one Alembic head,
  `0007_legacy_metric_comments`.
- Migrated a genuinely empty PostgreSQL database from zero through all seven
  revisions and passed the complete PostgreSQL integration suite against it.
- Audited the restored 90-cutoff history: every rollup, count identity,
  provenance relationship, structure fingerprint, and count-reversal query
  returned zero failures. Current source/catalog reconciliation was 53 games
  in both sources and 4 source-only games.
- Verified the raw archive (11,551 files, 931,961,706 bytes), created a final
  custom-format backup, checked its SHA-256, restored it into a guarded
  disposable database, and passed revision, row-count, and source-audit checks
  against the restore.
- Confirmed daily catalog persistence records unchanged manifests on a new
  Chicago date while remaining idempotent within a date. Duplicate unpaid-page
  skips still run catalog refresh, current-cutoff analytics verification, and
  the comprehensive nightly status report without holding a source transaction
  open during network work.
- Final regression results: 438 local tests passed (21 PostgreSQL-only skips),
  all 21 PostgreSQL tests passed, Ruff passed, `git diff --check` passed, and
  `systemd-analyze verify` passed for both units.

Final backup evidence:

- dump: `/tmp/illinois-final-backup-20260808/final-release.dump`
- SHA-256: `248c5b97a27b8ed337e1e055da821a515d8f633bc6e60f784a104fde7a7ab203`
- restore marker:
  `/tmp/illinois-final-backup-20260808/final-release.dump.restore-verified.manifest.json`

## Post-Review Remediation Gate — Complete (2026-08-10)

This gate supersedes the earlier final-validation counts above and records the
independent review remediations plus their application to the sole development
database.

- Added revision `0008_review_remediations` and removed max-model-ID
  publication. A model must now be explicitly approved with a successful,
  passing promotion backtest; PostgreSQL enforces the evidence relationship
  and one-approved-version rule. Failed new or reused promotion backtests
  automatically reject the version.
- Made strategy publication fail closed on approved-model, exact-cutoff, source
  freshness, and catalog freshness gates. Added an explicit ranking-status
  view instead of silently returning an older result.
- Added per-strategy one-in, launch, relative-to-launch, target-tier,
  count/value coverage, confidence, lumpiness, and timestamp fields, plus the
  required careful-review flag view.
- Excluded any game with a structure change or remaining-count reversal from
  high-tier scoring as well as calibration; its high tiers remain explicitly
  unavailable with the source-quality reason.
- Hardened catalog completeness to require a contiguous captured pagination
  chain and exact source-total reconciliation. Unknown URLs no longer map from
  name and price alone; unresolved/ambiguous cards persist quality issues and
  reconcile only after a verified detail URL is stored.
- Separated metadata planning, network collection, and transactional writes;
  PostgreSQL metadata writes reject in-transaction network collection. The
  metadata path no longer rewrites retained legacy estimates.
- Made backup manifests and dumps use one exported repeatable-read snapshot.
  Restore verification now fails closed on SQL/source audits and runs the full
  PostgreSQL smoke suite. Added guarded legacy restore rehearsal with an exact
  revision-0001 schema comparison before any disposable stamp/upgrade.
- Added source/catalog/model/invariant/lag-regression/raw-growth and
  backup/restore monitoring fields and alerts. Repeated daily catalog hashes
  are valid; repeated complete unpaid-prizes hashes remain prohibited.
- Added offline catalog replay from preserved raw page files. Detail metadata
  imports now skip the entire row on conflicting game number/name, price, or
  existing URL instead of partially mutating the wrong game.

Development-database migration and data evidence:

- Created pre-migration backup
  `data/backups/pre_alembic_remediation_20260810.dump`, SHA-256
  `29544f5ee1666ff949f372058d36b0cf74fafa50ae6c2a563019460ed177a7d1`.
- Restored it, matched its five-table schema exactly to a separately created
  revision-0001 database, migrated the restore through `0008`, preserved all
  original row counts, passed audits/tests, and only then stamped/upgraded the
  development database.
- Development database is at `0008_review_remediations`: 75 games, 90 source
  runs, 5,128 game snapshots, and 65,911 prize tiers. Every provenance,
  fingerprint, rollup, tier identity, structure-change, captured-time, and
  remaining-count-reversal audit count is zero.
- Replayed the complete archived 2026-08-08 retail catalog: 53 cards, 52
  verified URL mappings, and one audited unresolved card (`Galaxy Blast`). Its
  official archived detail page is internally inconsistent (page/table game
  number `7663`, while its name and asset filenames indicate game `7669`), so
  no unsafe mapping or metadata mutation was made.
- Backfilled 90 analytics cutoffs successfully with zero failures; an
  idempotence rerun skipped all 90. Persisted backtest 1 with 60 cutoffs,
  297,264 predictions, 182,788 eligible comparisons, and 142 summaries; its
  idempotence rerun reused the same rows.
- Promotion correctly failed: held-out median improvement `-17.99%`, 14-day
  improvement `-13.21%`, and no eligible 30-day comparison. Model 1.0.0 is
  `rejected`; all 90 analytics runs are successful but non-publishable and
  current rankings are explicitly unavailable as `MODEL_NOT_APPROVED`.
- Live 2026-08-10 source and catalog refreshes returned Illinois/Cloudflare
  challenge pages. Both paths failed before database import; the last valid
  source/catalog therefore remain in warning-age state rather than being
  replaced by invalid content.
- Created post-remediation backup
  `data/backups/post_remediation_20260810.dump`, SHA-256
  `fed7c93c5e3c00b1b5481b09ff139117be70feea19805a69aeb811597c22ffce`,
  and restored it into a guarded disposable database. Revision, manifest row
  counts, fail-closed SQL/source audits, and all PostgreSQL tests passed; the
  disposable database was dropped and a restore-verification marker retained.

Final regression evidence:

- Added a populated revision-boundary regression that creates a `0007`
  database with an existing failed promotion backtest and upgrades it to
  `0008`. The test first reproduced the legacy immutability-trigger failure;
  `0008` now replaces that trigger function before backfilling model approval
  state.
- Full local suite: 442 passed, 25 PostgreSQL-only skips.
- Fresh zero-to-head and restored-data PostgreSQL suites: 25 passed.
- One Alembic head: `0008_review_remediations`.
- Ruff, Python compilation, `git diff --check`, and both systemd unit
  verification checks passed.
