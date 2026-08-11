# Product planning workstreams

Last updated: 2026-08-10

Planning baseline: commit `fa3957e`

This directory preserves two related product-development tracks for the same
Illinois Lottery Tracker application:

1. **Usability and comprehension** — can an ordinary player understand the
   information, make a comparison, and know the limits of each estimate?
2. **Competitive advantage** — does the product give players a reason to use
   and trust it instead of a generic scratch-off ranking site?

They share data, components, and product principles, but they should be
designed and evaluated as separate workstreams. A feature is not useful as an
advantage if people cannot understand it; a clear interface is not, by itself,
a durable advantage.

The working inventories are:

- [Usability opportunity inventory](USABILITY_OPPORTUNITY_INVENTORY.md)
- [Competitive-advantage inventory](COMPETITIVE_ADVANTAGE_INVENTORY.md)
- [Track 1, milestone 1 specification](TRACK_1_MILESTONE_1_SPEC.md)
- [Track 1, milestone 1 evaluation](TRACK_1_MILESTONE_1_EVALUATION.md)
- [Track 1, milestone 2 specification](TRACK_1_MILESTONE_2_SPEC.md)
- [Track 1, milestone 2 evaluation](TRACK_1_MILESTONE_2_EVALUATION.md)

## What these documents are—and are not

The inventories are a durable record of the completed brainstorming. They are
not an approved backlog and they do not imply that every idea should be built.

Each item has one of these maturity states:

- **Implemented — evaluate:** the capability exists, but still needs deliberate
  user or browser validation.
- **Partially implemented:** useful foundations exist, but the intended user
  experience is incomplete.
- **Candidate:** retained for review; no build decision has been made.
- **Dependency-blocked:** retained, but another product or operational decision
  must come first.
- **Guardrail / non-goal:** a deliberate constraint that protects the product
  from misleading or distracting behavior.

Priority labels such as **Now**, **Next**, **Later**, or **Parked** will be added
only after owner review. Until then, order within an inventory is organizational,
not a priority ranking.

## Recommended implementation cycle

1. Preserve both inventories and confirm that they accurately reflect the
   brainstorming.
2. Review the usability inventory and assign priorities to a small first
   milestone.
3. Write a detailed usability design/build/evaluation specification only for
   that milestone.
4. Build, observe representative users, measure comprehension, and revise.
5. Select one competitive hypothesis whose foundations are understandable and
   test it as a distinct product experiment.
6. Feed learning back into both inventories before selecting another milestone.

This sequence avoids trying to redesign the entire application at once and
keeps competitive claims subordinate to demonstrated user understanding.

## Shared product decisions and guardrails

These are established decisions unless the owner explicitly reopens one:

- There is no universal “best ticket.” The user chooses the outcome or playing
  style that matters to them.
- The product must not issue `BUY`, `PASS`, or guaranteed-win instructions.
- Customer-facing rankings use real application data. Synthetic fixtures remain
  appropriate for automated tests, not the product experience.
- Official observations, estimates, and lag-adjusted estimates must remain
  distinguishable. “Unclaimed” must never be presented as synonymous with
  “unsold.”
- Estimates must not be described as exact, “real,” or known current odds.
- The narrowly scoped claim-lag adjustment applies only to prize tiers over
  $600 with at least 300 originally available prizes. Other tiers remain
  visible using official counts rather than being filtered out.
- The adjustment currently uses one explicit 24-day lag assumption. It is not a
  claim that every prize takes 24 days to appear, and it has not been established
  as an exact universal delay. Future evidence may justify a deliberately
  versioned change, potentially by broad prize class, but not a return to opaque
  per-game fitting or publication gates.
- There is no customer-facing evidence filter. Insufficient or lumpy data changes
  how a value is presented; it does not silently remove the game.
- Internal database, publication, backtest, and model-approval terminology must
  not leak into ordinary customer copy. Unavailability should be explained in
  plain language.
- No opaque composite score should hide what is being measured. Important
  rankings must be explainable from visible inputs and a public methodology.
- Public lottery comparison data stays public. Authentication protects account
  and personal ticket data; it should not become an unnecessary wall around
  public rankings.
- Personal play features must support budgeting and responsible-play context,
  not loss chasing, near-win gamification, or pressure to buy more tickets.
- When the data cannot support a precise estimate, the interface should state
  that limit and show the useful official fact—for example, “4 prizes left.”

## Current implementation baseline

As of the planning baseline:

- Live ranking endpoints and a React comparison experience are connected to the
  remediated database.
- Five question-first playing styles are exposed in the primary interface.
- Ranking cards and rows lead to a game-detail page.
- The detail page contains a prize-tier table and separate ticket-sales and
  tier-claim history views with exact-data fallbacks.
- Cards and tables show a top-prize count as “X out of Y left.”
- Claim-lag logic has been simplified to the established >$600 / >=300-prize
  eligibility rule and current 24-day assumption; the old adaptive lag and
  model-approval approach was removed.
- The backend contains additional useful measures, including probability of any
  profit excluding the top prize, that are not yet primary interface choices.
- Authentication is implemented but disabled pending its external release
  gates. Personal ticket entry and tracking are not implemented.
- Publication remains fail-closed for stale, structurally invalid, or otherwise
  unsafe source data. That integrity behavior is separate from customer-facing
  explanation.

## Where the workstreams overlap

| Shared product area | Usability concern | Competitive opportunity |
| --- | --- | --- |
| Question-first strategies | Can the player choose and explain a goal? | A transparent alternative to one opaque “best” score |
| Jackpot-independent value | Can the player understand “with” versus “without” the jackpot? | Show how much apparent value depends on a very rare top prize |
| Outcome probabilities | Can terms such as profit, 5x, and 10x be understood correctly? | Offer an outcome ladder matched to different player goals |
| Official and estimated data | Can the player tell which numbers were observed and which were inferred? | Earn trust through unusually explicit evidence and uncertainty |
| Historical changes | Can the player explain what changed and when? | Explain why a rank moved and replay what was knowable at the time |
| Illinois-specific data | Can local rules and source exceptions be stated simply? | Build specialized claim-lag, lifecycle, and source expertise |
| Discovery and comparison | Can users find, compare, and return to games? | Meet table stakes so differentiated analysis is actually usable |
| Accounts and saved activity | Are account boundaries and private data clear? | Add watchlists and personal longitudinal tracking after auth release |
| Accessibility and mobile use | Can everyone complete the core tasks without hidden interactions? | Execution quality supports every advantage, though it is not a moat by itself |

## Evaluation rules shared by both tracks

Every selected milestone should have a falsifiable evaluation plan before code
is written. At minimum, record:

- the player question or problem being addressed;
- the intended behavior or decision the change should enable;
- what must remain factually and mathematically correct;
- a representative task a user can attempt without coaching;
- observable success and failure criteria;
- accessibility and narrow-screen checks;
- the result, including confusing interpretations and unintended behavior;
- the decision to keep, revise, remove, or investigate further.

Clicks alone do not establish comprehension, trust, or differentiation. For
competitive experiments, usability is a prerequisite: first test whether users
understand the feature, then whether they prefer or return for it.

## Decision record

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-08-10 | Maintain usability and competitive advantage as separate, linked workstreams in one application. | They share implementation foundations but answer different evaluation questions. |
| 2026-08-10 | Capture candidate inventories before writing the usability build specification. | Prevent brainstorming ideas from being lost or silently promoted to requirements. |
| 2026-08-10 | Leave priority unset pending owner review. | Documentation is not approval to build every candidate. |
| 2026-08-10 | Make usability the first specified implementation milestone. | Differentiated analysis cannot succeed if users cannot interpret it. |
| 2026-08-10 | Approve U-07–U-13 for the first usability build, U-01–U-06 for validation, and U-22 as its acceptance layer. | Establish a trustworthy language system before adding more decision-support features. |

## Next planning decision

The first two usability milestones are implemented and engineering-verified;
their observed-user comprehension checks remain open. If users are still not
available, the next coherent engineering milestone is U-21, durable comparison
and return state, followed separately by U-15, U-18, and U-17.
