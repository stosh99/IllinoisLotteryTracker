# Analytics Validation

Validation protects the fixed rule from implementation errors; it does not
select a different rule at runtime.

## Pure-function tests

- $600 is ordinary and $600.01 is high.
- 299 original prizes are ineligible; 300 are eligible.
- The reference timestamp is exactly 24 days earlier.
- Interpolation is deterministic and Decimal-based.
- Progress reversals estimate zero pending claims.
- Estimated pending claims cannot exceed the official remaining count.
- Missing history and noneligible tiers retain official counts.
- A pre-launch reference has zero progress.

## Service tests

- Every source tier produces one analytics tier row.
- Eligible tiers store official, pending, and adjusted counts.
- New games without history remain scored and appear in strategy data.
- Small/lumpy top tiers remain visible with official counts.
- Rerunning the same model/cutoff reuses the immutable successful run.
- Missing overall odds null only absolute metrics.

## PostgreSQL tests

- A zero-to-head migration matches ORM metadata.
- Upgrading a populated pre-0010 database preserves source data, deletes old
  derived analytics, and installs model 2.0.0.
- Removed analytics tables and columns are absent.
- Successful analytics runs and model definitions are immutable.
- Current views require a successful model-2.0.0 run tied to the current source.
- Ranking views include only complete strategy metrics in the current
  source/catalog intersection.

## Operational checks

The nightly status reports source/catalog freshness, invariant failures,
analytics counts, adjusted-tier count, reference-unavailable count, backup age,
and restore-verification age. There is no statistical approval or prediction
horizon gate.
