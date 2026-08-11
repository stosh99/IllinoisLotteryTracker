# Track 1 milestone 4: outcome ladder

Last updated: 2026-08-11

Status: approved for exploratory implementation

## Objective

Help a player answer a more concrete question than long-run return: what kinds
of outcomes does this game currently appear to offer? The detail page will show
the complete first-pass ladder discussed with the owner, and the comparison
page will add one focused non-jackpot-profit view. The first version is
intentionally broad enough to inspect and revise before its wording or visual
hierarchy is treated as settled.

This milestone implements U-15 and retains U-22 as an acceptance layer. It does
not change the analytics formulas, database schema, claim-delay rule, or public
publication gates.

## Outcome contract

The ladder uses five existing, independently stored analytics measures:

| Outcome | Exact definition | Relationship to other rows |
| --- | --- | --- |
| Money back | Prize equals the ticket price exactly | A distinct break-even outcome; not profit |
| Any ordinary profit | Prize is greater than the ticket price, excluding the top-prize tier | Contains the 5x and 10x ordinary outcomes |
| At least 5x | Prize is at least five times the ticket price, excluding the top-prize tier | Contains the 10x ordinary outcome |
| At least 10x | Prize is at least ten times the ticket price, excluding the top-prize tier | A subset of 5x and ordinary profit |
| Top prize | The game’s highest prize tier | Shown in a separate jackpot lane |

Every row shows the estimated current probability as both a percentage and a
one-in-X frequency. The values are not independent and must not be presented as
parts of one additive total. The top prize is visually separated because the
ordinary-profit, 5x, and 10x measures deliberately exclude it.

## Comparison contract

- Add one primary question: “Where is a non-jackpot profit most likely?”
- Rank using the existing `profit_ex_top` strategy. Do not synthesize a new
  score or change the stored ordering.
- Say “excluding the top prize” in the picker explanation, metric label, rank
  explanation, and detail ladder.
- Keep exact money back and 10x as separate choices. The ladder is not a reason
  to remove an existing question before it can be reviewed in the browser.
- Strategy and price remain URL-backed through the milestone 3 state contract.

## Detail-page reading path

1. **Insight title:** “What could one ticket return?”
2. **Immediate evidence:** five directly labeled outcome rows with one-in-X and
   percent values visible without hover.
3. **Relationship annotation:** ordinary-profit thresholds nest inside one
   another, so those probabilities cannot be added.
4. **Separate lane:** top-prize odds and official X-out-of-Y inventory.
5. **Caveat:** all chances are estimates based on estimated ticket inventory;
   they describe the game, not the next ticket.
6. **Deeper evidence:** the existing prize-tier table remains immediately below
   the decision-support sections.

## Technical design

- **Analytical job:** compare nested probability thresholds for one game and
  rank games by one existing outcome probability.
- **Artifact family:** text-first probability ladder with proportional bars;
  semantic list/table behavior is the primary and fallback representation.
- **Renderer ownership:** React owns semantic structure, labels, and layout. A
  pure TypeScript helper maps the typed API outcomes to ordered presentation
  rows and bounded bar widths. CSS owns proportional geometry; no charting
  dependency is added.
- **API ownership:** the game-detail projection exposes the five existing
  stored aggregate metrics and their status. The browser does not re-sum prize
  tiers or recreate analytics formulas.
- **Instances:** one ladder on a game-detail page; no repeated mini-ladders on
  every ranking card.
- **Scale:** bar lengths are normalized to the largest ordinary-outcome
  probability within the game. Exact values, not bar lengths, are authoritative.
- **Color roles:** neutral track, one ordinary-outcome accent, and a distinct
  jackpot treatment; labels and lane headings redundantly encode meaning.
- **State:** no new local or remote state. The added comparison strategy uses
  the existing URL contract.
- **Mobile:** rows become a single-column reading order; both exact formats stay
  visible, no horizontal pan or hover is required, and the top-prize lane stays
  adjacent to the ladder.
- **Performance:** constant work over five rows; no material page or bundle cost.
- **Fallback:** unavailable or incomplete stored measures show an explicit
  unavailable state rather than a zero-width bar or inferred probability.

## Automated acceptance

- Backend contract tests verify the five outcome keys, stored probability,
  stored one-in value, and status reach the API without client recomputation.
- Pure frontend tests verify ordering, wording, percentage formatting, bar
  normalization, unavailable handling, and the nested-outcome note.
- Component tests verify all exact values are available without hover and the
  jackpot lane retains official inventory.
- Comparison tests verify the new strategy, URL state, rank basis, and keyboard
  navigation.
- Playwright covers desktop and mobile detail reading paths plus the new
  configured comparison URL.
- Existing backend, frontend, build, authentication, history, and share-state
  tests remain green; `git diff --check` passes.

## Evaluation boundary

Engineering can establish mathematical fidelity, accessibility, routing, and
responsive behavior. The owner will inspect this intentionally complete first
version and decide which rungs, labels, and emphasis to keep. Later observed-user
testing must still determine whether people understand “exactly,” “at least,”
“excluding the top prize,” and the fact that nested rows are not additive.
