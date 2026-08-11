# Usability and comprehension opportunity inventory

Last updated: 2026-08-10

Status: owner-prioritized; first milestone approved

This document records the usability brainstorming without turning every idea
into approved scope. Its central question is:

> Can a person who does not know lottery analytics understand what the product
> is saying, why it is saying it, and what remains uncertain?

See the [workstream overview](README.md) for maturity states, shared guardrails,
and the selection process. IDs are stable references for later specifications
and evaluation notes.

The owner approved the priorities below on 2026-08-10. “Now — validate” means
the existing feature is in the milestone test surface; it is not authorization
for unrelated redesign. See the
[milestone specification](TRACK_1_MILESTONE_1_SPEC.md) for the exact build scope.

| ID | Opportunity | Current maturity | Owner priority |
| --- | --- | --- | --- |
| U-01 | Question-first strategy selection | Implemented — evaluate | Now — validate |
| U-02 | Carousel navigation and position feedback | Implemented — evaluate | Now — validate |
| U-03 | Card and table-row navigation | Implemented — evaluate | Now — validate |
| U-04 | Top-prize inventory wording | Implemented — evaluate | Now — validate |
| U-05 | Prize-tier detail table | Implemented — evaluate | Now — validate |
| U-06 | Historical graphs and exact-data fallback | Implemented — evaluate | Now — validate |
| U-07 | Plain-language metric translation | Candidate | Now — build |
| U-08 | Visual language for evidence types | Partially implemented | Now — build |
| U-09 | Estimated-current-odds explanation | Candidate | Now — build |
| U-10 | EV and return in meaningful units | Candidate | Now — build |
| U-11 | Confidence and lumpiness translation | Candidate | Now — build |
| U-12 | Plain-language data states | Partially implemented | Now — build |
| U-13 | Glossary, methodology, and worked example | Partially implemented | Now — build |
| U-14 | “Why this ranks here” | Implemented — evaluate | Milestone 2 complete — observe later |
| U-15 | Outcome ladder and chance to profit | Partially implemented | Next |
| U-16 | Jackpot-dependence explanation | Implemented — evaluate | Milestone 2 complete — observe later |
| U-17 | Result trends and change explanation | Candidate | Next |
| U-18 | Game discovery essentials | Partially implemented | Next |
| U-19 | Side-by-side comparison | Candidate | Later |
| U-20 | Watchlist and notifications | Dependency-blocked | Dependency-blocked |
| U-21 | Durable/shareable comparison state | Partially implemented | Next |
| U-22 | Accessibility and narrow-screen acceptance | Partially implemented | Now — acceptance layer |
| U-23 | Authentication/account comprehension | Dependency-blocked | Dependency-blocked |
| U-24 | Personal ticket entry and results | Dependency-blocked | Dependency-blocked |
| U-G1–U-G5 | Product guardrails and non-goals | Guardrail / non-goal | Always enforced |

## A. Existing comparison experience to evaluate

### U-01 — Question-first strategy selection

- **State:** Implemented — evaluate
- **Problem:** Mathematical labels such as EV and payout ratio do not naturally
  map to the way most players describe what they want.
- **Current behavior:** The comparison begins with five plain-language questions
  representing different playing styles rather than declaring one game best.
- **Evaluate:** Ask users to choose a goal, predict what its ranking favors, and
  explain why the first result fits. Record wrong interpretations and words they
  use naturally.
- **Competitive link:** D-01, D-16

### U-02 — Carousel navigation and position feedback

- **State:** Implemented — evaluate
- **Problem:** Users need to browse more ranked cards without leaving the cards,
  and the visible-range counter must never disagree with the ranks on screen.
- **Current behavior:** Previous/next controls and a single “Showing cards X–Y
  of Z games” indicator were added.
- **Evaluate:** Exercise both controls repeatedly at desktop and mobile widths,
  after strategy and price-filter changes. The counter, visible cards, arrow
  enabled states, keyboard focus, and swipe/scroll behavior must agree after
  every transition.
- **Competitive link:** D-14, D-15

### U-03 — Card and table-row navigation

- **State:** Implemented — evaluate
- **Problem:** Users should be able to investigate a game from either summary
  representation without hunting for a separate link.
- **Current behavior:** Ranking cards and table rows lead to the game-detail page.
- **Evaluate:** Confirm the click target is discoverable, works by keyboard, does
  not create accidental navigation from nested controls, and preserves a useful
  route back to the selected comparison state.
- **Competitive link:** D-14, D-15

### U-04 — Top-prize inventory wording

- **State:** Implemented — evaluate
- **Problem:** “1 left” lacks the original denominator and can make games with
  very different top-prize structures look equivalent.
- **Current behavior:** Summary surfaces show “X out of Y left.”
- **Evaluate:** Verify the denominator is original prize count, the wording fits
  all counts and screen sizes, and users do not mistake official unclaimed counts
  for confirmed unsold tickets.
- **Competitive link:** D-07, D-08

### U-05 — Prize-tier detail table

- **State:** Implemented — evaluate
- **Problem:** A dense tier table can imply more precision than the data provides,
  especially when official counts, adjusted estimates, and odds appear together.
- **Current behavior:** Game detail shows prize tiers, official counts, estimated
  remaining values where eligible, and launch/current odds.
- **Evaluate:** Give users concrete lookup and interpretation tasks. Test header
  wording, units, mobile overflow, sorting expectations, source/date visibility,
  and whether the official-versus-estimated distinction survives a quick scan.
- **Competitive link:** D-06, D-07, D-08

### U-06 — Historical graphs and exact-data fallback

- **State:** Implemented — evaluate
- **Problem:** Users requested both estimated tickets sold and prize-tier claim
  history, but multiple lines and structural breaks can overwhelm or mislead.
- **Current behavior:** Detail pages provide separate sales and tier-history
  graphs, exact-data tables, and line breaks around structural changes.
- **Evaluate:** Ask users what each axis and line means, what is directly observed,
  why a line might break, and what changed over a chosen interval. Validate
  legends, keyboard access, screen-reader alternatives, and small-screen use.
- **Competitive link:** D-04, D-05, D-11

## B. Translation and trust

### U-07 — Plain-language metric translation layer

- **State:** Candidate
- **Problem:** Terms such as expected value, payout ratio, and probability can be
  numerically correct while remaining unusable to a typical player.
- **Candidate behavior:** Give every primary metric a short human interpretation
  beside the exact value, with optional detail rather than a wall of definitions.
  Example form: “Across the full prize pool, this represents about 74 cents in
  prizes per $1 played—not what one ticket is expected to pay.”
- **Foundation:** Existing cards already pair a lead strategy metric with one
  supporting value.
- **Evaluate:** Unprompted paraphrase accuracy, especially avoiding the belief
  that a displayed average predicts the next ticket.
- **Competitive link:** D-01, D-03, D-10

### U-08 — A consistent visual language for evidence types

- **State:** Partially implemented
- **Problem:** “Official,” “estimated,” and “lag-adjusted estimate” have different
  meanings but can blur together when they use the same visual weight.
- **Candidate behavior:** Establish reusable labels, help text, table treatment,
  and chart styling for: official published observation; calculation from
  official inputs; lag-adjusted estimate; and unavailable/not supportable.
  Never rely on color alone.
- **Foundation:** API provenance and current UI labels already expose portions of
  this distinction.
- **Evaluate:** Flash-test and task-test whether users can identify the evidence
  class and name the practical difference without opening methodology.
- **Competitive link:** D-07, D-08

### U-09 — Explain “estimated current odds” at the point of use

- **State:** Candidate
- **Problem:** A one-in-X estimate looks official and exact even though current
  ticket inventory is not directly published.
- **Candidate behavior:** Use explicit names such as “estimated chance now,” show
  the as-of date, disclose the estimation basis close to the value, and provide a
  short worked example. Preserve exact values for users who want to audit them.
- **Foundation:** Current detail data includes launch odds, official remaining
  prizes, estimated inventory, and provenance needed for an explanation.
- **Evaluate:** Users must distinguish launch odds from estimated current odds and
  state that neither predicts the outcome of an individual ticket.
- **Competitive link:** D-07, D-08, D-10

### U-10 — Translate EV and return into meaningful units

- **State:** Candidate
- **Problem:** “EV $7.42” on a $10 ticket is easy to read as a likely payout from
  that ticket rather than a long-run average across the full prize distribution.
- **Candidate behavior:** Prefer a consistent “estimated return per $1” or
  “about $X in prizes per $Y ticket over the long run” formulation, accompanied
  by the exact underlying metric and a no-guarantee explanation. Test whether an
  “estimated amount not returned per ticket” translation is clearer without
  making a long-run average sound like an individual-ticket forecast.
- **Foundation:** The API exposes both ticket price and expected value.
- **Evaluate:** Test ticket-level and per-dollar examples. A successful user can
  explain why a ticket with $7.42 EV can still lose its entire $10 cost.
- **Competitive link:** D-01, D-03, D-10

### U-11 — Translate confidence and lumpiness

- **State:** Candidate
- **Problem:** “Moderate confidence” and “lumpy tier” may sound scientific without
  telling the player what changes in the decision.
- **Candidate behavior:** Replace or supplement generic confidence badges with a
  consequence: “Too few prizes for a stable claim-lag estimate; showing the
  official count instead.” Explain the >=300 eligibility rule where relevant.
- **Foundation:** The pipeline retains official values when an adjustment is not
  supported and can expose the applicable reason.
- **Evaluate:** Confirm users do not interpret confidence as the chance of winning
  or the product's confidence that they personally should buy a ticket.
- **Competitive link:** D-06, D-08

### U-12 — Plain-language data status and unavailable states

- **State:** Partially implemented
- **Problem:** A trustworthy fail-closed system can look broken if the interface
  says “model not approved,” exposes pipeline jargon, or merely fails to load.
- **Candidate behavior:** State what information is unavailable, the customer-
  relevant reason, the last valid data date, and what still can be viewed. Keep
  technical diagnostics behind an operational surface.
- **Foundation:** The API already exposes source, freshness, catalog, and
  generation status; publication already fails closed.
- **Evaluate:** Users should be able to tell the difference between stale source
  data, an incomplete catalog, and a connection failure without learning the
  database architecture.
- **Competitive link:** D-07, D-09

### U-13 — Layered glossary, methodology, and worked example

- **State:** Partially implemented
- **Problem:** Scattered tooltips cannot teach the overall relationship among
  ticket inventory, prizes remaining, EV, odds, and uncertainty.
- **Candidate behavior:** Add a short “How to read this” path with one consistent
  example, then a glossary and auditable methodology for deeper questions.
  Link contextually from the relevant value rather than forcing a long preamble.
- **Foundation:** The home page has a short methodology section and the tier table
  has a reading note. Database and strategy specifications contain the exact
  logic; all of these need a coherent customer-language counterpart rather than
  direct exposure of pipeline terminology.
- **Evaluate:** Compare interpretation before and after the example and measure
  whether users can find an answer without abandoning their task.
- **Competitive link:** D-07, D-10, D-16

## C. Better decision support

### U-14 — “Why this game ranks here” explanation

- **State:** Implemented — evaluate
- **Problem:** A rank without its drivers asks the player to trust an unexplained
  ordering and makes movements look arbitrary.
- **Candidate behavior:** Give each game a concise, strategy-specific explanation
  using visible facts—for example strong non-jackpot return, improving ordinary
  prize availability, or heavy dependence on a scarce top prize.
- **Foundation:** Strategy metrics, launch comparisons, prize-tier data, and
  historical snapshots already exist.
- **Evaluate:** Ask users to explain why #1 outranks #2 and identify the tradeoff;
  verify generated explanations remain mathematically faithful at edge cases.
- **Competitive link:** D-02, D-04, D-10

### U-15 — Outcome ladder and “chance to come out ahead”

- **State:** Partially implemented
- **Problem:** Many players care more about a recognizable outcome than an
  abstract long-run return.
- **Candidate behavior:** Present a small, carefully defined ladder such as money
  back, any profit, 5x, 10x, and top prize. Avoid implying that overlapping
  outcomes are independent or additive.
- **Foundation:** Exact money-back and 10x strategies are public; the backend also
  calculates profit excluding the top prize and contains a 5x measure.
- **Evaluate:** Test whether users can distinguish “at least,” “exactly,” and
  “excluding the top prize,” and whether the ladder improves goal selection.
- **Competitive link:** D-03

### U-16 — Jackpot-dependence explanation

- **State:** Implemented — evaluate
- **Problem:** Two games can have similar full return even though one is carried
  by a tiny chance at a jackpot and the other has more value in ordinary prizes.
- **Candidate behavior:** Show return with the top prize, return without it, and a
  plain statement of how much apparent value depends on the jackpot. Use a small
  comparison visual only if comprehension testing supports it.
- **Foundation:** The product already ranks by full value and value excluding the
  top prize; both inputs exist.
- **Evaluate:** Users should correctly identify which game is more jackpot-
  dependent without treating either style as universally superior.
- **Competitive link:** D-02

### U-17 — Result trends and “what changed?”

- **State:** Candidate
- **Problem:** Input charts show tickets sold and prizes claimed, but users still
  must infer how those changes affected current odds, return, or rank.
- **Candidate behavior:** Add a result-level history or annotated change summary
  explaining when a relevant metric moved and which observed tier changes drove
  it. Keep source corrections distinct from real-world changes.
- **Foundation:** Immutable snapshots, calculated metrics, tier history, and
  structural-change markers exist.
- **Evaluate:** Give users two dates and ask what changed, why the recommendation
  moved, and whether the explanation reflects a claim event or data correction.
- **Competitive link:** D-04, D-05, D-11

## D. Discovery, comparison, and return visits

### U-18 — Game discovery essentials

- **State:** Partially implemented
- **Problem:** Strong analysis is difficult to use if a player cannot find a game
  by name or number or confirm that it is the ticket in front of them.
- **Candidate behavior:** Evaluate ticket image, name/number search, price filter,
  on-sale/ending status, source date, and direct official-game link as one
  coherent discovery flow rather than unrelated decorations.
- **Foundation:** Game identifiers and price filtering are live. Status,
  provenance, and official source fields exist to varying degrees; asset
  availability must be verified.
- **Evaluate:** Find-the-game tasks from a ticket/photo/name; verify stale images
  or conflicting official identifiers cannot silently misidentify a game.
- **Competitive link:** D-09, D-15

### U-19 — Side-by-side game comparison

- **State:** Candidate
- **Problem:** Users currently compare by scanning cards or rows and may lose the
  strategy context when opening multiple details.
- **Candidate behavior:** Allow a small number of games to be compared on a
  deliberately limited set of understandable dimensions, preserving official
  versus estimated labels and the selected goal.
- **Foundation:** Normalized ranking and detail payloads provide candidate fields.
- **Evaluate:** Test whether comparison improves tradeoff explanations or merely
  produces an unreadable metric wall, especially on mobile.
- **Competitive link:** D-14, D-15

### U-20 — Watchlist and change notifications

- **State:** Dependency-blocked
- **Problem:** Players may want to return to a few games without rebuilding the
  same search and may care when a meaningful condition changes.
- **Candidate behavior:** Save games and notify only for clearly defined,
  evidence-backed changes. Provide notification controls and avoid urgency or
  purchase-pressure framing.
- **Dependencies:** Public authentication release, notification/privacy decisions,
  meaningful-change definitions, and responsible-play review.
- **Evaluate:** Measure whether saved-game return is useful without creating
  misleading “buy now” interpretations or notification fatigue.
- **Competitive link:** D-13

### U-21 — Durable and shareable comparison state

- **State:** Partially implemented
- **Problem:** Losing strategy, price, or game context on navigation makes testing,
  comparison, sharing, and return visits harder.
- **Candidate behavior:** Encode stable public choices in the URL where practical,
  preserve them across detail/back navigation, and make shared links open to the
  same understandable state.
- **Foundation:** Strategy and price selections already serialize into the public
  comparison URL. Detail navigation, return context, explicit sharing, and
  unavailable-data behavior still need a minimal contract.
- **Evaluate:** Refresh, back/forward, open-new-tab, and shared-link tasks with
  changed or unavailable data.
- **Competitive link:** D-14

## E. Inclusive interaction and account boundaries

### U-22 — Accessibility and narrow-screen acceptance

- **State:** Partially implemented
- **Problem:** Hover-only explanations, color-only evidence labels, inaccessible
  charts, and wide tables would block core tasks for many users.
- **Candidate behavior:** Make keyboard, focus, screen-reader, contrast, zoom,
  reduced-motion, touch-target, and narrow-screen behavior part of every feature's
  acceptance criteria. Retain exact tabular alternatives for charts.
- **Foundation:** The responsive React application and exact history tables provide
  a starting point; a focused audit is still required.
- **Evaluate:** Automated checks plus manual keyboard/screen-reader and 320px-width
  task completion. Do not treat an automated score as proof of usability.
- **Competitive link:** Supports every item; execution quality rather than a moat.

### U-23 — Authentication and account-state comprehension

- **State:** Dependency-blocked
- **Problem:** Authentication is technically implemented but not publicly enabled;
  release states, failures, expiration, and privacy boundaries must be clear.
- **Candidate behavior:** Define comprehensible signed-out, sign-in, callback,
  expired-session, account, and deletion experiences without blocking public
  rankings.
- **Dependencies:** Authentication release gates, provider configuration, privacy
  policy, production-domain behavior, and operational readiness.
- **Evaluate:** Task tests for sign-in/out, recovery from errors, public browsing,
  and understanding which data is private.
- **Competitive link:** D-12, D-13

### U-24 — Personal ticket entry and results

- **State:** Dependency-blocked
- **Problem:** Personal tracking can be genuinely useful but can also encourage
  false conclusions from tiny samples or loss chasing.
- **Candidate behavior:** After authentication release, separately specify fast
  ticket/result entry, correction, privacy, spend/winnings/net summaries, budget
  context, and explicit small-sample warnings.
- **Dependencies:** U-23, a dedicated data/privacy design, personal-tracking schema,
  deletion/export policy, and responsible-play review.
- **Evaluate:** Entry accuracy and speed, correction/deletion tasks, privacy
  comprehension, and whether summaries are interpreted as records rather than a
  prediction that future play will “even out.”
- **Competitive link:** D-12

## F. Retained guardrails and non-goals

### U-G1 — No universal score or purchase verdict

- **State:** Guardrail / non-goal
- Do not collapse distinct player goals and uncertainty into one opaque grade,
  SmartScore, `BUY`, or `PASS` label.

### U-G2 — No false precision

- **State:** Guardrail / non-goal
- Do not call estimated inventory or odds “real,” hide the as-of date, or imply a
  calculated average predicts the next physical ticket.

### U-G3 — No unexplained pipeline gates in the customer experience

- **State:** Guardrail / non-goal
- Do not restore the removed evidence filter or expose internal phrases such as
  “model not approved,” “14-day error improvement,” or “eligible 30-day
  comparison” as if they were meaningful player decisions.

### U-G4 — No production dummy-data fallback

- **State:** Guardrail / non-goal
- If live comparison data is unavailable, show an honest unavailable state and
  last-valid context; do not silently switch the customer to demonstration games.

### U-G5 — No simulator or near-win gamification in the first usability program

- **State:** Guardrail / non-goal
- A simulated scratch experience does not solve the current comprehension problem
  and risks encouraging play. Reconsider only as a separately justified,
  responsible-play-reviewed project—not as default scope.

## Proposed evaluation protocol for the first specification

The eventual usability specification should select a small subset of IDs and
turn them into representative tasks. The retained test set should include:

1. Choose a goal and price range, then identify the leading game.
2. Explain the leading card in the user's own words.
3. Distinguish an official count from an estimated or adjusted value.
4. Explain a one-in-X value and an expected-return value without treating either
   as a prediction for the next ticket.
5. Navigate from summary to game detail and back without losing context.
6. Use the tier table to answer a concrete prize question.
7. Interpret both history views and find exact values without relying on hover.
8. Explain a data limitation or unavailable state.

For each task, record completion without help, time, interpretation errors,
confidence, requested definitions, and accessibility barriers. The first tests
should favor a handful of observed sessions and detailed misconceptions over a
large survey of opinions.
