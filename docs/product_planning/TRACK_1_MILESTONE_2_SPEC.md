# Track 1 milestone 2: explain rank and jackpot dependence

Last updated: 2026-08-11

Status: implemented and browser-verified; first-time-user comprehension sessions pending

## Objective

Help a player understand why a game occupies its current rank and how much of
its estimated long-run return comes from the top prize. The interface must make
the selected ranking basis and the jackpot tradeoff explicit without declaring
one playing style universally better.

This milestone implements U-14 and U-16. It uses only values already returned
by the current public API and does not change ranking formulas, database logic,
claim-delay logic, or publication behavior.

## Why these items belong together

“Why this ranks here” needs a visible, mathematically faithful comparison with
the leader in the selected view. Jackpot dependence uses the same full-return
and return-without-top-prize estimates to expose an important tradeoff behind
that ordering. Together they answer what the rank measures and what that single
rank does not capture.

U-15, U-17, U-18, and U-21 remain separate milestones. They respectively add a
new outcome-selection surface, historical result explanations, discovery
behavior, and durable navigation/share state.

## User questions this milestone must answer

1. Which single metric determines this rank?
2. Is this game first, tied for first, or behind the leader?
3. When it is behind, what is the leader comparison in the same units?
4. How much estimated return remains after the top prize is removed?
5. How much of the full estimated return is attributable to the top prize?
6. Does a high or low jackpot share make a game universally better?

## Ranking-explanation contract

- Every ranking card receives an always-visible “Why rank #N” explanation.
- The explanation names the selected ranking basis. It must not cite a factor
  that the selected formula does not use.
- A sole leader says it has the strongest selected metric among the games in
  the current view.
- Multiple leaders say they are tied. Dense-rank ties must never be described
  as a sole first place.
- A non-leading return strategy shows the cents-per-dollar gap from the leader.
- A non-leading probability strategy shows the game’s one-in-X value beside the
  leader’s one-in-X value. If one-in-X is unavailable, use the displayed
  probability values instead of inventing odds.
- A ticket-price filter changes the comparison population and rank label in the
  same way as the existing cards.
- The copy states that the selected metric determines this view; it does not
  imply an overall recommendation.

## Jackpot-dependence contract

For a game with ticket price `P`, estimated full return `F`, and estimated
return excluding the top prize `E`:

- full return per dollar = `F / P`;
- non-top return per dollar = `E / P`;
- top-prize contribution per dollar = `(F - E) / P`;
- top-prize share of full estimated return = `(F - E) / F`.

The decomposition is available only when `P > 0`, `F > 0`, and
`0 <= E <= F` within a small display-rounding tolerance. Invalid or missing
inputs produce an explicit unavailable state rather than a clamped or guessed
answer.

Cards show a short sentence such as “About 5.1% of this estimated return comes
from the top prize.” Game detail shows full return, return without the top
prize, and top-prize contribution in cents per dollar plus the percentage
share. All values remain labeled as estimates.

The percentage is a composition of estimated return, not a chance of winning
the jackpot and not a measure of whether a ticket is “good.” Copy must state
that lower dependence favors non-jackpot value while higher dependence places
more of the estimate in the rare top tier.

## Visualization design

- **Analytical job:** ranking comparison plus composition.
- **Artifact family:** concise explanatory text on repeated cards and one
  direct-labeled horizontal composition bar on game detail.
- **Primary route:** text carries the exact interpretation; the bar provides a
  quick comparison of non-top return and top-prize contribution.
- **Fallback:** the same three textual values remain sufficient without the
  bar. Missing or inconsistent inputs show “Jackpot dependence unavailable.”
- **Renderer:** semantic React/HTML and CSS. No chart library, canvas, SVG,
  animation, tooltip, or remote asset.
- **Instance count:** one text explanation per visible card and one composition
  view per game-detail page.
- **Encoding:** neutral/blue for return from non-top tiers and gold for the top
  contribution. Direct text labels and numeric values carry meaning, so color
  is redundant rather than essential.
- **Mobile path:** text first, three values in a single column when necessary,
  then the full-width bar and caveat. No horizontal interaction.
- **State:** no new control or persistence. The selected strategy and price
  filter continue to use the current URL contract.
- **Performance:** constant arithmetic and DOM/CSS only; no material bundle or
  rendering cost.

## Evidence and language guardrails

- Use the visible `Estimate` label for the decomposition.
- Say “estimated return,” never official return, actual return, or payout for
  one ticket.
- Say “comes from” or “depends on” the top-prize tier, not “chance from the
  jackpot.”
- Keep the long-run, game-wide caveat adjacent on detail.
- Do not use buy/pass language, a composite score, red/green good/bad labels,
  or a preferred jackpot-dependence threshold.
- Do not restore any evidence filter, model-approval gate, or adaptive lag
  behavior.

## Automated acceptance

- Unit tests cover sole leaders, tied leaders, non-leading return gaps,
  non-leading probability comparisons, filtered ranks, missing one-in-X, and
  invalid decomposition inputs.
- Component tests assert that the card explanation names the correct basis and
  that the detail view exposes all three decomposition values plus the estimate
  label and caveat.
- Existing unit tests, production build, and desktop/mobile Playwright suites
  pass.
- Browser checks confirm no card-height clipping, page-level mobile overflow,
  hover-only meaning, or color-only distinction.
- `git diff --check` passes.

## Evaluation boundary

Engineering evaluation can establish mathematical fidelity, accessibility,
responsive behavior, and deterministic copy coverage. It cannot establish that
a first-time player understands “jackpot dependence.” Preserve the following
later observed-user tasks:

1. explain why #1 outranks #2 in the selected view;
2. identify which of two games places more estimated return in the jackpot;
3. explain why that does not make either game universally better;
4. distinguish the jackpot-share percentage from the chance of winning it.
