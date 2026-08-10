# Canonical Analytical Specification

## Purpose and Interpretation

The model estimates how the published prize mix appears to have changed among
tickets that may still be available. It does not observe ticket sales,
retailer inventory, the location of winning tickets, or individual claim
processing times.

Every public-facing number derived from this model is an estimate. Internally,
use these terms:

- **reported**: directly calculated from public original/unclaimed counts;
- **estimated**: calculated from the `<= $500` progress proxy;
- **lag-aligned**: a high-tier observation compared with an earlier low-tier
  progress state;
- **availability index**: relative prize survival versus the neutral model;
- **equivalent remaining count**: a fractional analytical count, not a claim
  that this many physical winners are present.

## Fixed Definitions

For game `g`, source observation time `t`, and prize tier `i`:

| Symbol | Definition |
|---|---|
| `a_i` | Prize amount |
| `N_i` | Original winner count |
| `R_i(t)` | Reported remaining/unclaimed count |
| `C_i(t)` | Reported claimed count, `N_i - R_i(t)` |
| `O_g` | Published overall odds in one-in form |
| `T0_g` | Estimated original ticket count |
| `B_g` | Baseline tier set, all `a_i <= 500` |
| `D` | Estimated relative high-tier reporting lag in calendar days |

Prize-process groups are exact:

```text
baseline:       prize <= 500
retail gap:     500 < prize <= 600
high:           prize > 600
top tier:       maximum prize amount in that snapshot (independent flag)
```

The `$500` baseline is a product decision. Exact `$600` is not high. Values
between `$500` and `$600` are scored but do not influence the progress proxy.
Do not silently change these boundaries through configuration.

## Required Source Invariants

A tier can be scored only if:

- `N_i` and `R_i` are present;
- `N_i > 0`;
- `0 <= R_i <= N_i`;
- the game's original tier fingerprint is stable for the history used;
- source observations are from complete runs and strictly ordered by canonical
  source time.

The full baseline requires at least two tiers and at least 10,000 original
winners. A leave-one-tier-out reference also requires at least one remaining
reference tier and 10,000 reference originals. The live data comfortably
exceeds this: all current/historical games have at least two `<= $500` tiers,
and the smallest full baseline contains 485,954 original winners.

## Estimated Original Ticket Count

Let:

```text
W0_g = sum of N_i across every prize tier
```

Then:

```text
T0_g = W0_g * O_g
```

Keep `T0_g` as a high-precision decimal for calculations. The published odds
are rounded, so an integer-looking result is still an estimate. Round only for
display.

When `O_g` is missing, relative remaining fractions and availability indexes
may still be calculated, but absolute probabilities, one-in odds, EV, and
strategy rankings that require them are null with `MISSING_OVERALL_ODDS`.

## Game Progress Proxy

The full baseline uses count-weighted totals, never an average of tier
percentages:

```text
N_B = sum(N_i for i in B_g)
R_B(t) = sum(R_i(t) for i in B_g)

b_g(t) = R_B(t) / N_B
p_g(t) = 1 - b_g(t)
```

`b_g(t)` is estimated game fraction remaining; `p_g(t)` is estimated game
progress/claimed fraction.

Context-only ticket totals are:

```text
estimated tickets remaining = T0_g * b_g(t)
estimated tickets sold       = T0_g * p_g(t)
```

These replace the legacy use of all reported unclaimed winning tickets. They
must be labeled estimates and must not be rounded before downstream math.

## Non-Circular Tier Score for Prizes at or Below $600

### Baseline tiers (`a_i <= 500`)

Because tier `i` contributes to the full baseline, remove it from the
reference used to score itself:

```text
b_ref_i(t) = (R_B(t) - R_i(t)) / (N_B - N_i)
```

### Retail-gap tiers (`500 < a_i <= 600`)

These tiers are not in the baseline and do not require the large-claim lag:

```text
b_ref_i(t) = b_g(t)
```

### Common score

For either regular group:

```text
reported survival_i = R_i(t) / N_i

availability_i = reported survival_i / b_ref_i(t)

launch probability_i = N_i / T0_g

estimated current probability_i =
  launch probability_i * availability_i
  = R_i(t) / (T0_g * b_ref_i(t))

launch one-in odds_i = T0_g / N_i

estimated current one-in odds_i =
  launch one-in odds_i / availability_i
  = T0_g * b_ref_i(t) / R_i(t)
```

Interpretation:

- availability `1.00`: tier depleted proportionally to its reference;
- availability above `1.00`: relatively more prizes survive;
- availability below `1.00`: relatively fewer prizes survive;
- smaller one-in odds are better, but remain estimates.

If `R_i = 0`, probability is zero, availability is zero, and one-in odds are
null with status `depleted`; do not store infinity.

## High-Tier Lag Calibration (`a_i > 600`)

Lag calibration and tier scoring are separate jobs. The stable calibration
band estimates a process-level lag; it is not the set of tiers ultimately
shown or ranked.

### Adaptive calibration band

For each game at the as-of snapshot:

1. remove the maximum/top prize tier;
2. select remaining tiers strictly above `$600`;
3. order them by prize amount ascending;
4. accumulate original counts;
5. choose the smallest prize ceiling whose cumulative count is at least 500;
6. include every selected tier from the lowest high tier through that ceiling.

If 500 cannot be reached, the game is not a primary calibrator. A separate
exploratory result may use 250, but it cannot replace the primary global lag.
Never raise a dollar ceiling merely to force a low-count game into the model.

Current prize tables demonstrate why this rule is necessary: some `$1` games
have a `$1,000` top tier with only 25 originals, and others a `$3,000` top tier
with 75. Those observations are too lumpy to calibrate timing.

### Calibration curves

For each candidate game and each valid observation:

```text
low progress L_g(t) = 1 - sum(R_i for a_i <= 500) / sum(N_i for a_i <= 500)

high progress H_g(t) =
  1 - sum(R_i in adaptive high band) / sum(N_i in adaptive high band)
```

A primary game estimate requires:

- adaptive high-band original count at least 500;
- at least 30 distinct snapshots;
- at least 30 calendar days of history;
- stable tier membership and original counts;
- no progress reversal;
- at least 7.5 percentage points of common observed progress;
- no extrapolation;
- every interpolated crossing bracketed by observations no more than three
  calendar days apart.

### Horizontal-shift estimator

Let the common progress interval be:

```text
q_low  = max(first observed L_g, first observed H_g)
q_high = min(last observed L_g,  last observed H_g)
```

Require `q_high - q_low >= 0.075`. Select nine internal progress points:

```text
q_k = q_low + k * (q_high - q_low) / 10, for k = 1..9
```

Find the linearly interpolated source time when each curve first reaches
`q_k`:

```text
d_g(k) = time_high_g(q_k) - time_low_g(q_k)
```

The per-game lag is the median of at least seven valid `d_g(k)` values. The
global point estimate is the equal-game-weight median of per-game estimates.
Do not weight by high-band count; large-print games must not dominate the
process estimate.

Store the global median, game-level IQRs, the across-game Q1/Q3, and a
deterministic 10,000-resample equal-game bootstrap interval using seed
`20260808` for model version 1.0.

### Minimum global evidence

A new calibration is usable only when:

- at least eight primary game estimates qualify;
- at least 80% of game estimates are positive;
- the bootstrap 95% lower bound is above zero.

Otherwise mark the calibration `insufficient`. The analytics job may continue
with regular tiers but must not generate new high-tier adjusted values. It may
retain the previous approved calibration for a separate comparison report, but
must not label that stale calibration as current.

### Leave-one-game-out use

When scoring game `g`, calculate `D_-g` from the other primary calibration
games if at least eight remain. If excluding `g` leaves fewer than eight,
use the global estimate and set `lag_includes_scored_game = true`. A scoring
tier never influences band selection or lag parameters through its observed
remaining percentage.

### Empirical design check

Applying the rules above to the cutoff database yields:

- nine primary qualifying games;
- nine of nine positive game lags;
- median `24.21` calendar days;
- across-game Q1/Q3 `20.21` to `29.00` days;
- deterministic bootstrap 95% interval `19.90` to `29.46` days.

This is evidence for a provisional relative lag near 24–25 days, not a
hard-coded constant. Nightly analytics must use the stored calibration result.

## Date-Aligned High-Tier Score

For a high tier in game `g` observed at `t`:

1. obtain the game's leave-one-out/global lag `D_g`;
2. set reference time `t_ref = t - D_g`;
3. find bracketing complete observations of the game's full `<= $500`
   remaining curve;
4. linearly interpolate `b_g(t_ref)`;
5. refuse to extrapolate or interpolate across more than three days.

Then:

```text
b_lag_i = b_g(t_ref)

expected reported remaining_i = N_i * b_lag_i

availability_i = (R_i(t) / N_i) / b_lag_i

estimated current probability_i =
  R_i(t) / (T0_g * b_lag_i)

estimated current one-in odds_i =
  T0_g * b_lag_i / R_i(t)
```

The equivalent count at today's full-baseline inventory level is:

```text
equivalent current remaining_i =
  R_i(t) * b_g(t) / b_lag_i
```

This fractional count is useful for reconciliation and value sums. Probability
is the primary value; it does not require pretending the fractional count is a
physical observation.

The projection assumes tickets sold between `t-D` and `t` are an unbiased
sample of the inventory inferred at `t-D`. If ticket distribution is clustered
by pack, geography, or retailer, uncertainty is wider than the binomial model.

## Top-Prize Treatment

The top tier is always the maximum prize amount in the as-of snapshot.

- It is never part of lag calibration.
- If it is strictly above `$600`, it may use the calibrated high-tier formula.
- If it is `$600` or less, it uses the appropriate regular-tier formula.
- Reported integer remaining/original counts are always preserved next to any
  adjusted probability.
- Small top tiers will normally be classified `lumpy`; an apparently large
  availability index is not automatically evidence of a favorable game.

## Lag Sensitivity

For every high tier, repeat the date-aligned calculation using the calibration
Q1, median, and Q3 lag. Store:

- point availability at the median lag;
- minimum and maximum availability over Q1/median/Q3;
- point odds and the corresponding range;
- whether the direction versus `1.0` changes.

If direction changes, set `LAG_SENSITIVE`. Do not average the three scores.

## Statistical Uncertainty

The neutral model expects a claimed proportion:

```text
p_ref_i = 1 - b_ref_i
```

where `b_ref_i` is leave-one-tier-out, current full baseline, or lagged full
baseline according to tier group. With `x = C_i` and `n = N_i`, calculate the
95% Wilson interval for the observed claimed proportion using:

```text
z = 1.959963984540054
phat = x / n
denominator = 1 + z^2 / n
center = (phat + z^2 / (2n)) / denominator
half_width =
  z / denominator * sqrt(phat*(1-phat)/n + z^2/(4*n^2))
```

Clamp the Wilson claimed interval to `[0, 1]`, transform it to a remaining
interval, and divide by `b_ref_i` to obtain an availability interval.

Reference information is:

```text
information_count_i = min(N_i * p_ref_i, N_i * (1 - p_ref_i))
```

Use deterministic confidence labels:

| Label | Rule |
|---|---|
| `lumpy` | `N_i < 20` or information count `< 5` |
| `low` | information count `>= 5` and `< 10` |
| `moderate` | information count `>= 10` and `< 25` |
| `high` | information count `>= 25` |

Evidence classification is separate from confidence:

- `favorable`: Wilson availability lower bound is above `1.0`, every lag
  sensitivity point is above `1.0`, and confidence is not `lumpy`;
- `unfavorable`: Wilson availability upper bound is below `1.0`, every lag
  sensitivity point is below `1.0`, and confidence is not `lumpy`;
- `indeterminate`: otherwise;
- `unavailable`: required inputs failed.

These are statistical descriptions, not a guarantee of a win.

## Aggregating Tiers Without Reintroducing Circularity

Every valid tier produces its own estimated current probability using the
proper independent reference above. Game-level probability and expected value
metrics are sums of those tier estimates:

```text
P(target set S) = sum(current probability_i for i in S)

EV(target set S) =
  sum(prize amount_i * current probability_i for i in S)
```

Do not divide a target group's reported remaining count by an all-winning-tier
denominator that contains the same target. Do not force summed probability to
equal the published launch win probability; deviation is the analytical
signal. Store both the estimated current sum and the published launch value.

If any required tier is unavailable, store the valid probability/value
coverage and mark the aggregate `partial`. A full adjusted ranking requires
100% count coverage for its target set; reports may show partial values but
must not rank them as equivalent to complete values.

## Deterministic Test Vectors

### Regular baseline tier

```text
T0 = 4,000
target: N=100, R=55
other <=$500 tiers combined: N=900, R=360

b_ref = 360/900 = 0.4
availability = (55/100)/0.4 = 1.375
launch probability = 100/4,000 = 0.025
current probability = 0.034375
launch odds = 1 in 40
current odds = 1 in 29.090909...
```

### Date-aligned high tier

```text
T0 = 4,000,000
today's full-baseline remaining fraction = 0.30
lagged baseline remaining fraction = 0.40
high tier: N=200, reported R=100

expected reported remaining = 80
availability = 1.25
launch probability = 0.00005       (1 in 20,000)
current probability = 0.0000625    (1 in 16,000)
equivalent current remaining = 100 * 0.30/0.40 = 75
```

### Adaptive band selection

```text
non-top high tiers:
  $700:   N=100
  $1,000: N=450
  $5,000: N=20
top tier:
  $100,000: N=5

primary target 500 selects ceiling $1,000 and N=550.
The $5,000 and top tiers are not included.
```

### Synthetic lag curve

A test fixture whose high progress curve is exactly the low progress curve
shifted five days must return a five-day per-game lag within interpolation
tolerance. Separate tests must prove that top tiers are excluded, a four-day
observation gap rejects the affected crossing, and no point before the first
observation is extrapolated.
