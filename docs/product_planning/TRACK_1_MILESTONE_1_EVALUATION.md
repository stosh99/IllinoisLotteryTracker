# Track 1 milestone 1 evaluation

Last updated: 2026-08-10

Status: implementation and engineering evaluation complete; observed-user
comprehension evaluation pending

## Outcome

The first usability milestone is implemented. The comparison and game-detail
pages now distinguish official reports, exact calculations, estimates, and the
narrow lag-adjusted estimate. Ranking values use player-facing long-run and
one-in-X language, sparse prize tiers explain why the official count is kept,
and unavailable comparisons no longer expose internal reason codes or model
identifiers.

This evaluation establishes that the intended information is present,
operable, and responsive. It does not establish that a first-time player will
understand every concept without assistance.

## Implemented scope

- U-07 through U-13 are implemented for this milestone.
- U-01 through U-06 were regression-checked and strengthened where needed.
- U-22 was applied as a mandatory mobile and accessibility acceptance layer.
- The comparison formulas, API contract, database, >=300-prize rule, and
  24-day working assumption were not changed.
- The retired evidence/model gates were not restored.

## Automated results

| Check | Result |
| --- | --- |
| Frontend unit and component tests | 47 passed across 12 files |
| TypeScript and production build | Passed |
| Chrome Playwright tests | 16 passed across desktop and 390px mobile projects |
| Whitespace validation | `git diff --check` passed |

The browser regression coverage now includes all five ranking goals, repeated
carousel movement to the first and final cards, counter agreement with the
actual visible card midpoints, a ticket-price filter change, keyboard radio
navigation, detail-page navigation, exact chart-data disclosures, and a
fail-closed stale-source response.

## Browser evaluation

Chrome was evaluated at 1366 by 900 and 390 by 844 using deterministic API
fixtures. Full-page visual captures were reviewed for both the comparison and
game-detail pages.

| Task | Engineering result |
| --- | --- |
| Read each of the five ranking goals | Each goal exposes a non-empty primary metric and plain-language description. Probability goals show one-in-X and percentage context. |
| Browse the entire card set | Passed in both directions. The label matched the visible cards after each movement and after a price-filter change. |
| Interpret `$7.42` on a `$10` game | The cards say the return is per ticket over the long run; the worked example explicitly says one ticket may lose the full price or win a listed prize. |
| Identify evidence type | Text labels—not color alone—identify official reports, calculations, estimates, and lag-adjusted estimates. |
| Explain sparse tiers | The detail row says the official count is used when there were fewer than 300 starting prizes. |
| Compare current and launch chances | Separate table columns and baseline notes are visible without hover. |
| Navigate with keyboard and pointer | Strategy radios and the detail/back path passed keyboard checks; links and buttons retain visible names. |
| Open exact chart data | Both native disclosures expose semantic tables. |
| Read a paused comparison | Player-facing stale-data copy appears and the internal `SOURCE_STALE` code does not. |
| Mobile containment | No page-level horizontal overflow at 390px. Wide data tables scroll within their own containers. |

## Defects and interpretation risks

No remaining functional or responsive defect was found in this evaluation.
The carousel counter defect that motivated the regression coverage is now
guarded by live viewport geometry rather than an assumed card count.

The following are interpretation risks, not confirmed defects:

- A first-time player may still skim past the phrase “over the long run.”
- “Prize sample” may require the nearby explanation before its relevance is
  obvious.
- Some users may confuse estimated current ticket supply with an official sales
  count even though both the evidence tag and chart caveat say otherwise.
- The 24-day value remains a working assumption and must not be presented as a
  proven statewide processing time.

## Required next evaluation

Run short sessions with several people who have not seen the implementation.
Without coaching, ask them to:

1. explain the large number on a value card;
2. say whether `$7.42` predicts the payout of one `$10` ticket;
3. identify one official value and one estimated value;
4. explain why a sparse `$500,000` tier keeps its official count while an
   eligible `$1,000` tier may use the 24-day adjustment;
5. use the carousel and detail page to answer a comparison question.

Record their words and failure points before changing the interface. Those
observations determine whether this milestone needs a comprehension revision or
can advance to U-14 through U-18 and U-21.
