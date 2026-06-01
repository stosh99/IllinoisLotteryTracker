# Mail-In Prize Lag Model

## Purpose

Illinois instant-ticket prizes of `$600` or more generally require submission to
lottery headquarters rather than ordinary retailer redemption. That creates a
possible reporting lag in public unclaimed-prize data.

This document describes a future analytics model for estimating that lag. It is
not implemented yet because the project does not have enough historical
snapshots to fit or validate the model responsibly.

## Core Caveat

Public unclaimed-prize counts are not the same as unsold tickets. For large
prizes, a winning ticket may have been found but not yet processed into the
public remaining-prize data.

Any adjustment based on this document should be presented as an estimate based
on public remaining-prize data, not as a fact about ticket sales or unclaimed
physical tickets.

## Tier Groups

The model should separate prize tiers into three groups:

- Low tiers: prizes below `$600`
- Mail-in tiers: prizes `>= $600`, excluding the top prize tier
- Top prize tier: the largest prize amount for a game

Top prize tiers should be excluded from the mail-in lag model.

Top prizes are usually limited to a very small count, often `1-5` total prizes.
That makes them structurally lumpy. A single claim can move the tier by 20%,
33%, 50%, or 100%. For top prizes, variance dominates, so smoothing or
lag-adjusting the tier can create false precision.

Top prize handling should remain separate:

- reported top prizes remaining
- top prize depleted
- estimated EV including top prize
- estimated EV excluding top prize

## Basic Percent Comparison

For each game and source date:

```text
low_tier_remaining_pct =
  remaining prize count for tiers < $600
  / original prize count for tiers < $600

mail_in_remaining_pct =
  remaining prize count for non-top tiers >= $600
  / original prize count for non-top tiers >= $600

mail_in_gap_pct =
  mail_in_remaining_pct - low_tier_remaining_pct
```

If mail-in prizes are reported with delay, the mail-in tier should often show a
higher remaining percentage than the low tier for the same game.

Example:

```text
Low tiers:       40% remaining
Mail-in tiers:   46% remaining
Observed gap:     6 percentage points
```

This does not prove every game has exactly a 6-point lag. It is a cross-game
estimate of reporting delay pressure.

## Days-Behind Estimate

Once enough history exists, estimate how many days behind the mail-in tier
appears to be.

For a given game and source date:

```text
today_mail_in_remaining_pct = non-top >=$600 remaining percentage today
```

Then find the earlier date where:

```text
low_tier_remaining_pct ~= today_mail_in_remaining_pct
```

If the closest low-tier percentage occurred 5 days earlier, then the mail-in
tier appears roughly 5 days behind the low-tier curve for that game.

Average this across qualifying games:

```text
average_mail_in_lag_days
median_mail_in_lag_days
```

The median may be more robust than the mean because individual games and prize
tiers can be noisy.

## Same-Day Adjustment

A simpler report-only adjustment can be computed before enough data exists for
a stable days-behind model.

Across qualifying games and dates:

```text
expected_mail_in_gap_pct =
  median(mail_in_remaining_pct - low_tier_remaining_pct)
```

Then for an individual game:

```text
adjusted_mail_in_remaining_pct =
  max(mail_in_remaining_pct - expected_mail_in_gap_pct, 0)
```

This can be translated into an adjusted count or adjusted prize value:

```text
adjusted_mail_in_remaining_count =
  original_mail_in_count * adjusted_mail_in_remaining_pct

adjusted_mail_in_value =
  adjusted_mail_in_remaining_count * prize_amount
```

Fractional adjusted counts are acceptable. They represent expected value, not a
literal number of tickets.

## Suggested Report Metrics

Future reports should show multiple views side by side:

```text
reported_estimated_ev
estimated_ev_excluding_top_prize
estimated_ev_excluding_all_>=600_prizes
mail_in_lag_adjusted_ev
```

The report should also classify games:

```text
Value survives lag adjustment
Reported value likely driven by mail-in lag
Reported value mostly top-prize driven
Insufficient data
```

These labels should be descriptive, not gambling advice.

## Qualification Rules

The model should ignore weak or noisy inputs.

Recommended exclusions:

- top prize tier
- games with too few stored snapshots
- games with too few low-tier prize counts
- mail-in tiers with very small original counts
- brand-new games where all tiers are near 100% remaining
- nearly exhausted games where denominator effects are large
- games with prize-structure changes between compared snapshots

Possible minimums:

```text
minimum snapshots per game: 14
minimum low-tier original count: 1,000
minimum mail-in original count: 20 or 50
```

These thresholds should be tuned after observing real data.

## Open Questions

- Should the model be global across all games, or grouped by ticket price?
- Does the lag differ for `$600-$999`, `$1,000-$4,999`, and `$5,000+` prizes?
- How many snapshots are needed before the estimate stabilizes?
- Should weekends and holidays be modeled separately?
- Should source-date gaps, such as a failed scrape day, be interpolated or left
  as missing?

## Current Recommendation

Do not persist mail-in lag adjusted metrics yet.

For now:

- keep raw public counts unchanged
- keep existing EV and payout-ratio metrics unchanged
- continue collecting daily snapshots
- use this model as report-only exploratory analytics once enough history exists

