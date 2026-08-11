# Track 1 milestone 4 evaluation

Last updated: 2026-08-11

Status: implementation and engineering evaluation complete; owner visual review
and observed-user comprehension evaluation pending

## Outcome

U-15 is implemented as an intentionally complete first-pass outcome ladder.
Each current game detail page now separates:

- exactly money back;
- any ordinary profit, excluding the top prize;
- at least 5x, excluding the top prize;
- at least 10x, excluding the top prize; and
- top-prize odds in a separate jackpot lane.

Every supported value is visible as both one-in-X and a percentage without
hover. The three ordinary-profit thresholds are explicitly labeled as nested,
and the page tells users not to add them. The jackpot lane keeps its official
X-out-of-Y prize inventory beside the estimated chance.

The comparison page also adds “Come out ahead,” backed by the existing
`profit_ex_top` ranking. Its question, explanation, metric name, and rank basis
all state that the top prize is excluded. No ranking or probability formula was
added or changed.

## Data-fidelity checks

- The API projects the five existing stored aggregates, their stored one-in
  values, and metric status. The frontend does not sum tier probabilities.
- A read against the current database returned exactly five outcome entries for
  all 52 published games.
- Across those games, 251 of 260 entries are complete. Nine are legitimately
  `not_applicable`; the UI says “No matching prize tier in this game” instead of
  portraying them as a zero chance or a broken calculation.
- Partial, unavailable, and not-applicable values receive no proportional bar.
- Exactly money back is called break-even, not profit.
- The top prize is not visually nested inside the ordinary outcomes that
  exclude it.

## Automated results

| Check | Result |
| --- | --- |
| Python tests | 566 passed; 31 PostgreSQL-environment tests skipped |
| Python lint | Passed |
| Frontend unit and component tests | 76 passed across 14 files |
| TypeScript and production build | Passed |
| Chrome Playwright tests | 20 passed across desktop and 390px mobile projects |
| Current-database API projection | 52 games; five outcome entries per game |
| Whitespace validation | `git diff --check` passed |

The Chrome path covers all five labels and exact values, the nested-probability
warning, the added comparison strategy, keyboard strategy navigation, URL
state, and page-width containment at both configured viewports.

## Accessibility and responsive behavior

- The exact values are ordinary text; the bars are supplemental and hidden
  from assistive technology.
- Break-even, ordinary profit, and jackpot are named lanes rather than
  color-only distinctions.
- The mobile reading order is title, break-even, nested ordinary outcomes,
  jackpot, caveat, then deeper prize-tier evidence.
- No outcome requires hover, dragging, pointer precision, animation, or a
  charting runtime.
- The new comparison choice remains a keyboard-operable radio and participates
  in the existing URL/share contract.

## Decisions still open for owner review

This milestone was deliberately built for inspection rather than treated as a
final information hierarchy. The owner should decide after using it whether to:

- keep all five outcomes visible;
- shorten or rename “ordinary profit”;
- keep both exact money back and ordinary profit as primary comparison choices;
- promote 5x to its own comparison question, retain only 10x, or expose neither;
- change the order of the jackpot-dependence and outcome-ladder sections; and
- reduce the explanatory copy once the relationships feel clear.

Observed-user evaluation remains necessary. A successful first-time user must
be able to explain “exactly,” “at least,” “excluding the top prize,” and why the
ordinary percentages cannot be added. Until then, this implementation should
be considered a mathematically verified candidate, not settled product copy.
