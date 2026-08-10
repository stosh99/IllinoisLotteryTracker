# Validation and Backtesting

## What Can and Cannot Be Validated

The database contains reported remaining-prize histories, not ticket-level
sales or the locations of winners. Backtesting can validate whether the model
aligns and predicts later reported depletion better than simpler alternatives.
It cannot prove the exact number of tickets physically available at a retailer
or the result a buyer would receive.

Validation has four layers:

1. deterministic formula tests;
2. source/database invariant tests;
3. walk-forward predictive tests;
4. model-promotion and regression gates.

## No-Look-Ahead Contract

For a backtest cutoff source run `s_t`:

- model parameters and lag calibration use only complete observations with
  source time at or before `s_t`;
- the scored tier uses its count at `s_t` only;
- interpolation for `t-D` uses observations at or before `s_t`;
- future observations are accessed only after prediction rows are frozen;
- code must fail a test if a query includes a source run after the cutoff in a
  feature/calibration CTE.

Backtesting the current code against a future-fitted 24-day lag would be data
leakage. Each cutoff must refit or use a calibration version approved using
only prior data.

## Deterministic Unit Tests

Pure calculation tests cover:

- count-weighted baseline progress;
- leave-one-tier-out reference math;
- `$500`, `$600`, and `>$600` boundary behavior;
- estimated print-run calculation without premature rounding;
- availability/probability/one-in equivalence;
- zero remaining count behavior;
- top-tier identification and calibration exclusion;
- adaptive high-band selection at 250 and 500 counts;
- progress crossing and interpolation;
- no extrapolation and maximum-gap rejection;
- equal-game global median;
- deterministic bootstrap seed/result;
- leave-one-game-out lag selection;
- high-tier date adjustment and equivalent count;
- Wilson interval and confidence labels at every threshold;
- lag-sensitivity direction;
- aggregate probability and EV sums;
- null/status propagation.

The numeric examples in `02_analytics_specification.md` are executable test
vectors, not illustrative prose only.

## PostgreSQL Integration Tests

CI starts a supported PostgreSQL service and verifies:

1. `alembic upgrade head` from an empty database;
2. seed import of at least three games and multiple source dates;
3. source constraints reject invalid and inconsistent counts;
4. current-game views follow latest complete membership, not `is_active`;
5. an incomplete newer run does not replace the prior current run;
6. the same complete source hash cannot be imported twice;
7. structure changes and reversals create quality issues/exclusions;
8. analytics persistence is idempotent per model/cutoff;
9. a failed analytics run never appears in current views;
10. deleting a source parent follows the intended FK policy in a disposable
    fixture only;
11. numeric precision matches pure Decimal calculations;
12. all views return zero/explicit unavailable state when prerequisites fail.

At least one fixture uses a Chicago/UTC date boundary to verify source-date
semantics.

## Walk-Forward Dataset

Use complete source runs as cutoffs after at least 30 prior calendar days of
history. Evaluate horizons of 7, 14, and 30 calendar days. Select the first
complete target observation within plus/minus one day of the requested horizon;
otherwise exclude that prediction with `TARGET_DATE_MISSING`.

Do not manufacture daily rows for the two known missing source dates.

Store every eligible and excluded prediction so sample-size changes are
auditable.

## Conditional Depletion Prediction

The availability model implies a direct prediction for later remaining count.

For a regular tier scored at cutoff `t` and evaluated at `u`:

```text
predicted R_i(u) = R_i(t) * b_ref_i(u) / b_ref_i(t)
```

For a high tier with lag `D_t` estimated at the cutoff:

```text
predicted R_i(u) =
  R_i(t) * b_g(u - D_t) / b_g(t - D_t)
```

Only baseline observations available by the relevant cutoff/target are used.
The prediction preserves the tier's estimated enrichment/depletion at `t` and
then assumes unbiased depletion afterward.

Compare at least three model variants:

1. `aligned`: the canonical formulas above;
2. `no_lag`: high tiers use current same-date baseline progress;
3. `legacy`: denominator based on all reported remaining winning tickets and
   published overall odds.

For regular tiers, `aligned` means leave-one-tier-out; `no_lag` is identical
for non-high tiers and need not be duplicated.

## Backtest Measures

Persist by horizon, tier process group, confidence label, ticket-price group,
and model variant:

- prediction and observed counts;
- signed count error;
- absolute count error;
- signed and absolute remaining-fraction error;
- error normalized by `max(1, expected binomial standard deviation)`;
- median absolute error;
- mean absolute error, reported only with median;
- median bias;
- number of predictions, unique games, and unique tiers;
- favorable/neutral/unfavorable cohort results;
- lag model improvement versus no-lag.

Do not use mean percentage error when an observed count can be zero.

For strategy metrics, group game/tier scores into quartiles at each cutoff and
test whether later relative depletion is ordered in the expected direction.
This is a calibration check, not a simulated guarantee of purchase results.

## Lag Calibration Validation

Perform two complementary validations:

### Leave-one-game-out

For each qualifying game, fit global lag without it and measure the held-out
high curve's absolute progress error under:

- zero-day lag;
- leave-one-out median lag.

### Walk-forward

At each eligible historical cutoff, fit lag using history available then and
evaluate later high-tier progress. Record how the median, IQR, bootstrap
interval, and qualified-game set evolve.

This reveals whether an apparent stable 24-day value is merely a property of
the current 90-day window.

## Promotion Gates

Version 1 calculations may be persisted as `experimental` immediately, but a
model version becomes `publishable` for database ranking datasets only after:

### Source/progress model

- zero invariant failures on every historical complete run;
- current membership matches the latest complete run;
- at least 95% of current games have absolute-odds inputs or are explicitly
  excluded rather than imputed;
- no result depends on legacy estimated-ticket columns.

### Lag model

- at least eight primary calibration games;
- at least 80% positive game lags;
- bootstrap 95% lower bound above zero;
- held-out median absolute high-progress error at least 10% lower than the
  zero-lag model;
- improvement is nonnegative at both 14- and 30-day horizons;
- no single game changes the global point estimate by more than seven days;
- qualification and result tables are fully persisted.

### Strategy datasets

- 100% target-tier coverage for any row eligible to rank;
- deterministic reproduction from the same model/cutoff;
- formula tests for every strategy key;
- no rank includes a stale/noncurrent game;
- ranking status and confidence filters work in PostgreSQL integration tests.

If a gate fails, keep the output for analysis with `publishable=false`. Do not
tune a threshold against the same failed backtest and rerun under the same
model version.

## Model Regression Report

Every new model version produces a comparison against the current approved
version:

- number of source/game/tier rows affected;
- current game additions/removals caused by data status;
- lag estimate and eligible-game changes;
- distribution of availability changes;
- top ten ranking changes per strategy key;
- backtest metric changes by horizon;
- newly unavailable/partial metrics;
- parameter and formula diff.

Approval is a documented database/model decision. A code deployment alone
does not activate a new model version.

## Minimum Current-History Interpretation

The cutoff database has only 90 stored source days and ten game launches inside
the observed window. Current lag results are therefore provisional even though
the signal is positive and passes the primary game-count rule. The first
implementation must expose sample sizes and run the backtest; it must not hard
code `25` as an unquestioned business constant.
