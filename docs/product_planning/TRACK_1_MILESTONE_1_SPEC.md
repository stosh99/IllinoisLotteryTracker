# Track 1 milestone 1: understandable estimates

Last updated: 2026-08-10

Status: implemented and browser-verified; first-time-user comprehension sessions pending

## Objective

Make the existing comparison understandable to a player who does not know
lottery analytics. A successful user can tell what a number means, whether it is
official or estimated, what a one-in-X value does and does not say, and why a
sparse prize tier is presented differently.

This milestone implements U-07 through U-13, validates U-01 through U-06, and
uses U-22 as a mandatory acceptance layer. It does not change ranking formulas,
database logic, publication rules, or the API contract.

## User questions this milestone must answer

1. What outcome is this ranking comparing?
2. What does the large number on a card mean in ordinary language?
3. Is this value copied from the Illinois Lottery, calculated from official
   values, or estimated by this site?
4. Does “$7.42 return” mean my $10 ticket is likely to pay $7.42?
5. What does “1 in 15,679” mean, and why is the current value estimated?
6. Why was a 24-day adjustment used for one tier but not another?
7. If current rankings are unavailable, what happened and what information is
   still safe to view?

## Scope

### Build

- Replace bare analytical shorthand such as `EV`, `payout ratio`, generic
  `confidence`, and customer-facing `model` language with defined player-facing
  terms.
- Pair every primary ranking metric with an always-visible plain-language
  interpretation. Probability strategies show both one-in-X and percentage
  forms when both are available.
- Show expected prize return as a long-run game-wide average—for example,
  “$7.42 per $10 ticket over the long run”—rather than a bare dollar amount.
- Establish a reusable evidence key for official reported values, calculated
  values, estimates, and the narrow lag-adjusted estimate.
- Update the detail table so evidence type and fallback consequences are visible
  without hover or color alone.
- Explain the >=300 starting-prize rule and current 24-day working assumption.
  Sparse tiers retain official reported counts.
- Rewrite data-ready, unavailable, and failure states in player language while
  preserving fail-closed behavior.
- Replace the current pipeline-oriented methodology block with a layered “How
  to read the estimates” path, a worked example, and a compact glossary.
- Correct any U-01–U-06 regression found during implementation. In particular,
  every game in the selected comparison must be reachable from the card
  carousel, and its visible range label must agree with the cards on screen.

### Do not build

- New ranking formulas, strategies, API fields, database migrations, or lag
  calibration logic.
- “Why this ranks here,” outcome ladder, jackpot-dependence decomposition, or
  result-level change explanations; those remain the next milestone.
- Search, images, game comparison, watchlists, public auth release, or personal
  ticket tracking.
- A new chart renderer, chart type, dashboard, simulator, composite score,
  purchase recommendation, or hidden evidence filter.

## Evidence vocabulary

| Label | Meaning | Examples |
| --- | --- | --- |
| Official report | Directly reported by the Illinois Lottery source | Starting prizes; reported unclaimed prizes; published overall odds |
| Calculated | Exact arithmetic using reported inputs | Claimed = starting minus reported unclaimed |
| Estimate | Depends on inferred current ticket supply or another unpublished value | Current chance; current prize return; tickets sold/remaining |
| Lag-adjusted estimate | Estimate that applies the current 24-day assumption to an eligible >$600 tier with >=300 starting prizes | Estimated pending claims; estimated unclaimed now |
| Unavailable | Inputs do not support the value without guessing | Missing current chance or ranking |

The labels must use text as well as styling. Color may reinforce a class but
must never be the only distinction.

## Metric language contract

- **Estimated prize return:** the long-run average prize value represented by
  the current game-wide prize pool. It is not a likely payout for the next
  ticket and is not net profit.
- **Estimated return per $1:** the same long-run prize value normalized to one
  dollar of ticket cost. Prefer “about 70 cents in prizes per $1 over the long
  run” to “70% payout ratio.”
- **Estimated chance now:** an estimate using current prize counts and estimated
  current ticket supply. Show both “1 in X” and percentage when useful.
- **Estimated chance at launch:** a baseline inferred from the original prize
  structure and published overall odds; do not label it as an official tier
  probability.
- **Reported unclaimed:** an official source count. It can include a winning
  ticket that was sold but has not yet been processed as claimed.
- **Small prize sample:** evidence context, not the player’s chance of winning
  and not a reason to remove the game.
- **Compared with launch:** use “higher,” “lower,” or “about the same,” not an
  unexplained signed percentage.

## Worked-example contract

Use one internally consistent example:

- A $10 game with $7.42 estimated prize return represents about 74 cents in
  prizes per $1 over the long run.
- It does not mean an individual $10 ticket is expected to pay $7.42; that ticket
  can lose the full $10 or win a listed prize.
- A tier with 400 starting prizes and 150 officially reported unclaimed has 250
  calculated claimed prizes.
- Because the tier is over $600 and began with at least 300 prizes, the site may
  also display a lag-adjusted estimate—such as 143.5 estimated unclaimed—using
  the current 24-day working assumption.
- Both the official 150 and estimated 143.5 remain visible.

## Technical design

- **Analytical job:** comparison/ranking plus uncertainty and provenance
  interpretation.
- **Artifact family:** existing ranking cards, semantic tables, detail facts,
  time-series charts, exact-data disclosures, and explanatory prose.
- **Renderer ownership:** React and semantic HTML for labels/tables/disclosures;
  the existing SVG time-series renderer remains unchanged.
- **Instance assumptions:** one comparison carousel and table per ranking page;
  one prize table and two history charts per detail page.
- **State contract:** current URL-backed strategy and price state is unchanged.
  This milestone does not add persistence. Card/detail navigation remains public.
- **Mobile contract:** 360–430px portrait is a primary state. The selected goal,
  primary metric, evidence label, caveat, and source date remain legible without
  hover. Horizontal tables retain sticky context and exact values.
- **Interaction contract:** all essential meanings are always visible or reachable
  with a native keyboard-operable disclosure. No pointer-precision interaction
  is required. Existing carousel buttons retain at least 44px targets.
- **Fallback contract:** charts retain exact tables; stale/error states retain the
  last meaningful context where the API provides it; unsupported estimates show
  an explicit unavailable or official-count fallback instead of disappearing.
- **Performance:** no new dependency, remote asset, chart instance, or polling.
  The carousel may render all currently filtered games so every card is reachable;
  the expected Illinois catalog size is suitable for this DOM cost and remains
  covered by the existing scaled fixture.

## Page reading path

### Comparison page

1. Choose the player question.
2. Read what the selected metric favors.
3. See the current card range and browse every matching game.
4. Read the primary value, its plain-language equivalent, long-run prize return,
   top-prize inventory, evidence note, and launch comparison.
5. Use the full table for exact comparison.
6. Open “How to read the estimates” for the evidence key, worked example, and
   glossary.

### Game detail

1. Identify the game and official published overall odds.
2. Distinguish estimated ticket inventory from official prize counts.
3. Read the evidence key before the prize table.
4. Compare official reported unclaimed, calculated claimed, lag-adjusted
   estimated unclaimed, estimated current chance, and estimated launch chance.
5. Read the explicit fallback reason for sparse or ineligible tiers.
6. Use chart summaries first and exact-data disclosures when needed.

## Accessibility acceptance

- No essential definition, value, source, caveat, or evidence class requires
  hover, color recognition, animation, or a precise pointer.
- Evidence tags have visible text and sufficient contrast in normal, grayscale,
  and common color-deficiency review.
- Native links, buttons, radio controls, tables, and disclosures retain logical
  keyboard focus and names.
- The page remains operable at 200% zoom and at 360px width without hiding the
  primary metric or its caveat.
- Probability values and dates have meaningful accessible names; raw internal
  reason codes and model identifiers are not customer copy.
- History charts retain descriptions, direct series keys, non-color line styles,
  and exact tabular alternatives.
- Reduced motion preserves all information.

## Automated acceptance

- Unit tests cover cents-per-dollar language, probability display, long-run
  return wording, launch comparison wording, evidence/fallback labels, and
  carousel range/page behavior.
- Component tests assert the new methodology/evidence copy, absence of exposed
  model jargon, accessible table labels, and exact-data fallbacks.
- Existing frontend unit tests, TypeScript build, and Playwright tests pass.
- Backend/API tests are required only if an API-facing file changes; the intended
  implementation does not require one.
- `git diff --check` passes.

## Browser evaluation tasks

Run at desktop and mobile portrait widths:

1. Choose each of the five goals and explain the card’s primary number.
2. Browse to the final carousel card and confirm the range label matches visible
   cards after repeated next/previous actions and filter changes.
3. Explain why a $7.42 estimated return does not predict one $10 ticket.
4. Identify which table values are official, calculated, estimated, and
   lag-adjusted.
5. Explain why a sparse >$600 tier retains the official count.
6. Distinguish estimated chance now from estimated chance at launch.
7. Navigate to detail and back with keyboard and pointer.
8. Open exact history data without using hover.
9. Verify unavailable data copy gives a useful player-facing reason and exposes
   no internal reason code.

Record defects separately from interpretation risks. Code correctness is not
evidence that a first-time player understands the result; observed user sessions
remain the final comprehension test.
