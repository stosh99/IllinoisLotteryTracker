# Player-Style Database Datasets

## Scope

This document defines database outputs that a later application can place in
different recommendation tabs. It does not define UI, copy, colors, or a
single universal best-game score.

People play for different outcomes, so each dataset has one transparent
primary metric and supporting primitives. Version 1 uses no weighted composite
scores.

All current estimates are built by summing independently scored tier
probabilities from `analytics_tier_metrics`. High tiers use lag-aligned
probabilities. A target set is rank-eligible only when every tier belonging to
that target has a valid estimate and the game is present in both the current
unpaid-prizes source and current mapped retail catalog. Source-only games keep
their analytics but receive no default recommendation rank.

## Common Per-Game Inputs

For each current game, persist:

- ticket price;
- published overall one-in odds and probability;
- estimated print-run and full-baseline progress;
- source/model cutoff and freshness;
- prize-source-current, catalog-current, and recommendation-current status;
- top prize amount and reported original/remaining counts;
- count/value coverage of valid tier scores;
- error/warning issue counts;
- model version and lag calibration status.

For a target predicate `S(i)`:

```text
estimated_probability(S) =
  sum(tier.current_probability for tiers where S(i))

estimated_ev(S) =
  sum(tier.prize_amount * tier.current_probability for tiers where S(i))
```

Launch comparisons use `N_i / T0_g` for the same tier set.

## Required Strategy Metrics

### Stay in the Game / Money Back

Store:

```text
p_any_win
p_break_even_exact
p_break_even_or_better
p_2x_or_better
one_in_any_win
one_in_break_even_exact
```

Predicates:

```text
any win:                 every prize tier
exact break-even:        prize == ticket_price
break-even or better:    prize >= ticket_price
2x or better:            prize >= 2 * ticket_price
```

`p_any_win` and `p_break_even_or_better` may be identical for games with no
prize below ticket price. Preserve both keys because they answer different
questions and source structures may change.

Primary ranking key: `p_break_even_exact` for players explicitly content to
get the ticket cost back. Show published overall win probability as a
supporting metric. A later product may offer `p_break_even_or_better` as a
secondary sort.

### Most Likely Profit Without the Top Prize

Store:

```text
p_strict_profit
p_strict_profit_ex_top
one_in_strict_profit_ex_top
profit_probability_vs_launch
```

Predicates:

```text
strict profit:          prize > ticket_price
strict profit ex top:   prize > ticket_price AND is_top_prize = false
```

Primary ranking key: `p_strict_profit_ex_top` descending.

This is intentionally different from expected value. A game can have a higher
chance of a small profit but a lower EV than a game dominated by rare prizes.

### Best Mathematical Value

Store:

```text
estimated_ev_full
estimated_ev_ex_top
estimated_payout_ratio_full
estimated_payout_ratio_ex_top
estimated_house_edge_full
estimated_house_edge_ex_top
ev_full_vs_launch
ev_ex_top_vs_launch
```

Formulas:

```text
estimated_payout_ratio = estimated_ev / ticket_price
estimated_house_edge = 1 - estimated_payout_ratio
```

Primary ranking keys are both retained:

- `value_full`: payout ratio including every valid tier;
- `value_ex_top`: payout ratio excluding the maximum tier.

Do not rank partial EV as full EV. Do not substitute a reported/unadjusted high
tier when lag scoring is unavailable.

### Moderate Upside

Store probability and one-in odds for:

```text
p_5x_or_better_ex_top
p_10x_or_better_ex_top
p_20x_or_better_ex_top
p_50x_or_better_ex_top
p_100_to_1000_ex_top
ev_5x_or_better_ex_top
ev_10x_or_better_ex_top
```

Multiplier predicates include equality and exclude the top tier. The fixed
dollar band includes both endpoints.

Primary ranking keys:

- `moderate_5x`: `p_5x_or_better_ex_top`;
- `moderate_10x`: `p_10x_or_better_ex_top`.

The database exposes both; a later application decides which is the default.

### Jackpot / Large Prize

Store:

```text
top_prize_amount
top_prizes_original_reported
top_prizes_remaining_reported
p_top_prize_estimated
one_in_top_prize_estimated
top_availability_index
top_confidence
p_1000_or_better
p_10000_or_better
p_100000_or_better
p_1000000_or_better
one_in_1000_or_better
one_in_10000_or_better
one_in_100000_or_better
```

Primary ranking keys:

- `jackpot_top_odds`: `p_top_prize_estimated`;
- `large_1000`: `p_1000_or_better`;
- `large_100000`: `p_100000_or_better`.

The raw top counts and confidence label are mandatory alongside a top-prize
estimate. Top tiers remain excluded from lag calibration even when they are
included in this dataset.

### Games to Review Carefully

This is a flag dataset, not a favorable ranking. Persist booleans/codes for:

- no top prizes reported remaining;
- game absent from current source;
- source stale;
- missing overall odds;
- structure change or count reversal;
- lag unavailable or lag-sensitive;
- full or ex-top metric partial;
- weak adjusted payout ratio versus launch;
- high-prize value dominated by lumpy tiers;
- analytics/source cutoff mismatch.

Threshold-based warnings such as weak payout ratio are model parameters, not
hard-coded report constants.

## Long-Form Ranking Keys

`current_strategy_rankings_v` exposes at least these keys:

| Key | Direction | Metric |
|---|---|---|
| `money_back_exact` | descending | `p_break_even_exact` |
| `profit_ex_top` | descending | `p_strict_profit_ex_top` |
| `value_full` | descending | `estimated_payout_ratio_full` |
| `value_ex_top` | descending | `estimated_payout_ratio_ex_top` |
| `moderate_5x` | descending | `p_5x_or_better_ex_top` |
| `moderate_10x` | descending | `p_10x_or_better_ex_top` |
| `jackpot_top_odds` | descending | `p_top_prize_estimated` |
| `large_1000` | descending | `p_1000_or_better` |
| `large_100000` | descending | `p_100000_or_better` |

For each key compute:

- rank across all eligible current games;
- rank within exact ticket price;
- metric value;
- one-in form when probability-based;
- launch metric and relative change when available;
- target-tier count;
- target count/value coverage;
- lowest contributing confidence label;
- metric status;
- source/model timestamps.

Use `dense_rank()` by metric value. A separate deterministic display ordering
may use game number after equal values; game number must not change the rank.

## Eligibility and Partial Results

A metric status is one of:

```text
complete
partial
unavailable
not_applicable
```

Rules:

- `complete`: every source tier matching the target predicate has a valid
  estimate;
- `partial`: at least one but not all target tiers has a valid estimate;
- `unavailable`: no complete estimate or required overall odds/reference is
  missing;
- `not_applicable`: the game has no tier matching the target predicate.

Only `complete` rows from `recommendation_current_games_v` receive ranks.
Preserve source-only and partial point totals for diagnosis, but never compare
them directly with complete recommendation-eligible totals.

Confidence does not remove a complete row by itself. The view exposes default
eligibility flags:

```text
eligible_all_confidence
eligible_moderate_or_high
contains_lumpy_tier
```

This lets a later product show jackpot rows while making their uncertainty
unavoidable.

## Reconciliation Requirements

For every game/run:

- sum of current tier probabilities equals `p_any_win` when complete;
- sum of `amount * probability` equals `estimated_ev_full` when complete;
- excluding-top metrics equal the full sum minus exactly the maximum tier;
- multiplier and fixed-dollar predicates are covered by parameterized tests;
- probability values are between zero and one;
- EV and payout ratios are nonnegative;
- one-in odds are the reciprocal of positive probability within Decimal
  tolerance;
- launch probabilities across all tiers sum to `1 / O_g` within Decimal
  tolerance;
- current estimates are not forced to that launch sum.

## No Hidden Recommendations

The database stores primitives, ranks, status, and confidence. It does not
store text such as `buy`, `best bet`, or `guaranteed`. A later product can
explain which player question a ranking answers while preserving the model's
estimated and negative-EV caveats.
