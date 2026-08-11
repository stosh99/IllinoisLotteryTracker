# Track 1 milestone 2 evaluation

Last updated: 2026-08-11

Status: implementation and engineering evaluation complete; observed-user
comprehension evaluation pending

## Outcome

U-14 and U-16 are implemented. Every ranking card now states the metric that
orders the current view and explains whether the game leads, ties, or trails
the leader. Cards also state the share of full estimated return attributable to
the top prize. Game detail expands that decomposition into full return, return
without the top prize, and top-prize contribution.

No ranking formula, API response, database value, publication rule, or lag
assumption changed.

## Mathematical checks

- Return-strategy explanations compare the current metric with the leader in
  cents per dollar.
- Probability explanations compare one-in-X values and fall back to percentages
  only when one-in-X is unavailable.
- Dense-rank ties are described as ties rather than sole leaders.
- Price-filtered views use the within-price rank.
- Jackpot dependence is calculated from existing full and ex-top return values.
- Missing, negative, zero, or materially inconsistent decomposition inputs
  produce an unavailable result rather than a guessed or clamped percentage.
- The non-top and top-prize shares reconcile to the full estimated return.

## Automated results

| Check | Result |
| --- | --- |
| Frontend unit and component tests | 60 passed across 13 files |
| TypeScript and production build | Passed |
| Chrome Playwright tests | 16 passed across desktop and 390px mobile projects |
| Whitespace validation | `git diff --check` passed |

## Browser and visual evaluation

Chrome was evaluated at 1366 by 900 and 390 by 844. Full-page comparison and
detail captures were reviewed.

- All five strategy selections displayed the matching ranking basis.
- Repeated carousel movement, range labels, and filters remained correct after
  the cards gained explanatory content.
- Card bottoms and links were not clipped, and visible cards remained aligned.
- The detail decomposition showed 74.2 cents per dollar for all prizes, 70.4
  cents without the top prize, and 3.8 cents from the top prize for the test
  game; the displayed 5.1% share reconciled with those values.
- The composition bar is subordinate to the direct numeric labels and has an
  accessible text description.
- Mobile uses a text-first single-column reading path and introduces no
  page-level horizontal overflow.
- No essential meaning depends on hover, animation, or color.

No remaining functional or responsive defect was found.

## Interpretation risks retained for observed users

- “Comes from the top prize” may still be confused with the probability of
  winning the top prize.
- A player may treat lower jackpot dependence as universally better despite the
  explicit neutral explanation.
- A small gold bar segment may receive more or less attention than its numerical
  importance warrants.
- Some players may find the additional card explanation too dense even though
  it answers the ranking question.

When first-time users become available, ask them to explain why #1 outranks #2,
identify which game places more estimated return in the jackpot, and distinguish
the jackpot-share percentage from the chance of winning it.

## Recommended next milestone without user recruitment

Implement U-21 as a small navigation-state milestone: preserve strategy and
price context through detail/back navigation, refresh, browser history, and
shared public URLs. It is lower interpretation risk than adding another
analytical surface and improves evaluation of every later feature.
