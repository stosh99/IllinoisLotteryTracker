# Analytics Specification

## Purpose

The analytics compare the current supply of prizes with estimated remaining
ticket inventory. Illinois prizes above $600 require claim-center processing,
so their official remaining counts can temporarily include already-sold winning
tickets. The system makes one narrow correction for that reporting delay.

## Fixed high-prize adjustment

A prize tier is eligible only when both conditions are true:

- `prize_amount > 600`
- `original_count >= 300`

The ordinary reference population for the same game is every tier with
`prize_amount <= 600`. Its count-weighted progress is:

```text
ordinary_progress = 1 - ordinary_remaining / ordinary_original
```

For an eligible tier at observation time `t`, use the ordinary progress at
`t - 24 days`. If that point falls between two observations, interpolate
linearly. If it falls on or before the known launch date, progress is zero.

```text
newly_claimed_fraction = max(
  ordinary_progress(t) - ordinary_progress(t - 24 days),
  0
)

estimated_pending = min(
  original_count * newly_claimed_fraction,
  official_remaining_count
)

adjusted_remaining = official_remaining_count - estimated_pending
```

All arithmetic is Decimal. The clamps prevent a source reversal from adding
claims and prevent adjusted remaining prizes from becoming negative.

## Fallback behavior

The correction is optional; the game is not.

- A high tier with fewer than 300 original prizes uses the official count.
- An eligible tier without a usable 24-day reference uses the official count.
- Either case remains eligible for cards, strategies, and rankings.
- The tier records whether its status is `applied`, `reported_only`, or
  `reference_unavailable`.

Small high-prize tiers are correctly described as lumpy. That label is context,
not a publication gate.

## Tier scoring

Ordinary tiers use a leave-one-tier-out ordinary reference, preventing a tier
from supplying its own comparison. High tiers use current ordinary progress and
their adjusted or official fallback count. Published overall odds provide the
estimated original ticket total. If overall odds are absent, relative
availability remains available while absolute probability and EV fields are
null.

## Strategy aggregation

Tier probabilities aggregate into the supported strategy datasets. Top-prize
exclusion is exact, multiplier boundaries are inclusive, and every output
retains source, catalog, analytics-run, and model-version provenance.

## Availability

Rankings require current complete source and catalog captures and a successful
analytics run for the same current source cutoff. Source/catalog freshness and
structural data integrity remain fail-closed. A missing high-prize adjustment
reference is not an availability failure.
