# Competitive-advantage opportunity inventory

Last updated: 2026-08-10

Status: candidate inventory awaiting owner prioritization

This document preserves the second brainstorming track: how the Illinois Lottery
Tracker could become meaningfully better than a generic scratch-off ranking site.
It is not an approved feature backlog.

The central question is:

> What can this product help an Illinois player understand or do that is hard to
> get elsewhere—and why would that advantage remain credible over time?

See the [workstream overview](README.md) for shared guardrails and sequencing.
Every item is classified as:

- **Defensible asset:** compounds through proprietary history, operations,
  domain knowledge, or private longitudinal data.
- **Positioning advantage:** meaningfully distinctive to users but reasonably
  easy for a competitor to copy.
- **Table stakes:** necessary for a credible product but not a reason it will win.

Priority is unset for every item pending owner review.

| ID | Opportunity | Current maturity | Advantage class |
| --- | --- | --- | --- |
| D-01 | Question-first rankings | Implemented — evaluate | Positioning |
| D-02 | Jackpot-dependence decomposition | Partially implemented | Positioning / possible signature |
| D-03 | Outcome ladder | Partially implemented | Positioning |
| D-04 | Explain rank/value changes | Candidate | Positioning on data asset |
| D-05 | Historical as-of replay | Candidate | Defensible asset |
| D-06 | Illinois claim-lag adjustment | Partially implemented | Defensible domain/data capability |
| D-07 | Visible provenance and fail-closed trust | Partially implemented | Operational / positioning |
| D-08 | Honest uncertainty and lumpy fallback | Partially implemented | Positioning / brand promise |
| D-09 | Illinois specialization | Partially implemented | Defensible domain specialization |
| D-10 | Public explainable methodology | Partially implemented | Positioning on operations |
| D-11 | Accumulated clean history | Partially implemented | Defensible asset |
| D-12 | Private ticket/result tracking | Dependency-blocked | Potential defensible retention |
| D-13 | Watchlists and change alerts | Dependency-blocked | Table stakes / retention |
| D-14 | Compare, deep-link, and share | Partially implemented | Table stakes |
| D-15 | Images, search, status, official links | Partially implemented | Table stakes |
| D-16 | Evidence-first responsible positioning | Partially implemented | Positioning / brand promise |

## A. A different way to answer “which game?”

### D-01 — Question-first rankings instead of one universal score

- **State:** Implemented — evaluate
- **Class:** Positioning advantage
- **Opportunity:** Let the player choose the outcome they care about—ordinary
  prize value, full value, money back, a moderate multiple, or jackpot odds—then
  rank transparently for that question.
- **Why it matters:** Most single scores bury subjective weights. This approach
  makes the tradeoff the product rather than pretending one game is best for all
  players.
- **Foundation:** Five question-first strategies are live; two additional outcome
  calculations exist in the backend.
- **Copy risk:** High. The durable value comes from clarity, evidence, history,
  and disciplined refusal to collapse the choices again.
- **Evaluate:** Can users explain the selected goal and prefer this approach to an
  opaque score after completing the same comparison task?
- **Usability link:** U-01, U-07, U-G1

### D-02 — Jackpot-dependence decomposition

- **State:** Partially implemented
- **Class:** Positioning advantage with potential signature-feature value
- **Opportunity:** Show return with the top prize, return without it, and the
  portion of apparent value carried by the jackpot. Translate this into a plain
  statement such as “ordinary prizes carry most of this game's value” or “this
  result depends heavily on one rare top prize.”
- **Why it matters:** A headline return can conceal a materially different play
  experience. The product already asks the right question but does not yet expose
  the full decomposition clearly.
- **Foundation:** Full-value and ex-top strategies already use the required
  calculations.
- **Copy risk:** Medium to high; protect it through excellent explanation and
  historical context, not secrecy about arithmetic.
- **Evaluate:** Comprehension, usefulness in choosing between two real games, and
  preference versus full-return-only presentation.
- **Usability link:** U-14, U-16

### D-03 — An understandable outcome ladder

- **State:** Partially implemented
- **Class:** Positioning advantage
- **Opportunity:** Organize comparable outcomes—money back, any profit, 5x, 10x,
  and jackpot—so a player can move from a personal goal to a mathematically exact
  definition.
- **Why it matters:** It covers more recognizable intentions than return alone and
  can make the multi-strategy philosophy memorable.
- **Foundation:** Money-back and 10x strategies are exposed; profit-ex-top and 5x
  calculations are present in the backend.
- **Copy risk:** High. Precision in definitions and interaction quality are the
  advantage.
- **Evaluate:** Whether users choose an intended outcome correctly and understand
  `exactly`, `at least`, and exclusions before comparing preference or retention.
- **Usability link:** U-07, U-10, U-15

### D-04 — Explain why a rank or value changed

- **State:** Candidate
- **Class:** Positioning advantage built on a defensible data asset
- **Opportunity:** Turn historical observations into a concise causal account:
  which tier changed, whether estimated inventory moved, and why the selected
  strategy's result improved or declined.
- **Why it matters:** Competitors commonly show trend lines; fewer explain the
  change in terms a player can audit.
- **Foundation:** Immutable snapshots, tier histories, strategy calculations, and
  structural-change markers are available.
- **Copy risk:** The interface is copyable; the clean historical series and
  correction discipline are harder to reproduce retroactively.
- **Evaluate:** Factual agreement with the underlying snapshots, user ability to
  explain a movement, and trust versus an unexplained arrow or score change.
- **Usability link:** U-06, U-14, U-17

### D-05 — Historical replay: “what was knowable then?”

- **State:** Candidate
- **Class:** Defensible asset presented as a product feature
- **Opportunity:** Let users inspect a past date using only information available
  at that time, rather than applying today's corrected data to yesterday's claim.
- **Why it matters:** It makes historical assertions auditable and prevents
  hindsight from masquerading as predictive quality.
- **Foundation:** Run/snapshot provenance and historical calculation records were
  designed for as-of reconstruction; the exact supported contract must be
  verified before interface design.
- **Copy risk:** Low once sufficient clean history accumulates; a new competitor
  cannot recreate observations it never captured.
- **Evaluate:** Reconstruction correctness, clear correction handling, and whether
  users find replay useful beyond technical curiosity.
- **Usability link:** U-06, U-17

## B. Illinois-specific evidence and trust

### D-06 — Narrow, explainable Illinois claim-lag adjustment

- **State:** Partially implemented
- **Class:** Defensible domain and data capability
- **Opportunity:** Account for the additional mailing and headquarters-processing
  delay affecting sufficiently numerous prize tiers over $600, while leaving
  sparse/lumpy tiers as official counts.
- **Why it matters:** Generic sites often mention claim lag as a caveat. A narrow,
  auditable rule can produce a more useful estimate without pretending the
  unknowable delay is exact.
- **Foundation:** The rule is fixed to >$600 and >=300 original prizes; the old
  adaptive/model-approval machinery has been removed. The >=300 threshold is a
  deliberately simple smoothness rule, not a reason to hide smaller tiers. The
  current 24-day value is an explicit shared assumption, not a proven delay for
  every claim or game.
- **Copy risk:** The concept is copyable, but trustworthy validation, Illinois
  history, and restraint compound over time.
- **Evaluate:** Data operations should monitor whether the shared lag remains a
  reasonable approximation over time and whether broad prize classes ever have
  enough evidence to justify a versioned change. That research must not become a
  per-game approval gate. Customer evaluation should focus on whether the
  adjustment and fallback are understood without implying official or exact
  current inventory.
- **Usability link:** U-05, U-08, U-09, U-11

### D-07 — Provenance and fail-closed behavior as visible trust

- **State:** Partially implemented
- **Class:** Defensible operational capability plus positioning advantage
- **Opportunity:** Make the source, as-of date, calculation class, and material
  data issue legible to customers. When trustworthy rankings cannot be produced,
  explain the limit instead of publishing stale or structurally invalid output.
- **Why it matters:** Many products add a disclaimer beneath a score. Here,
  provenance and refusal to guess are properties of the pipeline and can support
  a stronger trust promise.
- **Foundation:** Source-run lineage, catalog checks, stale-data controls, conflict
  handling, and fail-closed publication are implemented.
- **Copy risk:** Copy is easy; consistently operating the system and retaining an
  audit trail is harder.
- **Evaluate:** Accuracy of displayed provenance, comprehension of unavailable
  states, trust calibration, and operational incident review—not raw uptime alone.
- **Usability link:** U-04, U-08, U-09, U-12, U-13

### D-08 — Honest uncertainty and useful lumpy-tier fallbacks

- **State:** Partially implemented
- **Class:** Positioning advantage and brand promise
- **Opportunity:** Refuse unsupported precision while still showing the useful
  official fact. A sparse tier remains visible as “4 prizes left” rather than
  being omitted or receiving a fragile lag estimate.
- **Why it matters:** Restraint can differentiate a product in a category full of
  precise-looking proprietary scores.
- **Foundation:** Ineligible tiers retain official counts and no evidence filter
  removes their games.
- **Copy risk:** High, but consistent behavior and methodology make the promise
  credible.
- **Evaluate:** Whether users see the result as appropriately limited—not broken,
  secretly inferior, or a prediction about physical tickets.
- **Usability link:** U-04, U-05, U-08, U-09, U-11, U-G2, U-G3

### D-09 — Illinois specialization

- **State:** Partially implemented
- **Class:** Defensible domain specialization
- **Opportunity:** Become the best-maintained explanation of Illinois scratch-off
  games: official identifiers, redemption rules, claim behavior, lifecycle,
  source exceptions, game-ending context, and direct official evidence.
- **Why it matters:** State-specific operational knowledge can make every generic
  metric more accurate and useful. The current Cloudflare challenge and the
  conflicting Galaxy Blast identifiers demonstrate why local source expertise
  matters.
- **Foundation:** Illinois importer, source audits, conflict refusal, restoration
  checks, and local claim-lag reasoning exist.
- **Copy risk:** Lower as documented exceptions, history, and operational know-how
  accumulate.
- **Evaluate:** Coverage/freshness/correction quality, successful resolution of
  source anomalies, and whether local guidance answers real user questions.
- **Usability link:** U-12, U-18

### D-10 — Public, explainable methodology

- **State:** Partially implemented
- **Class:** Positioning advantage supported by operational depth
- **Opportunity:** Publish a customer-readable methodology that connects every
  headline result to exact definitions, official inputs, estimates, limitations,
  and change history.
- **Why it matters:** Transparency is a better fit for the product than a secret
  “smart factor,” and it makes question-first rankings auditable.
- **Foundation:** Detailed internal database and strategy specifications exist.
  They must be translated and curated rather than exposed verbatim.
- **Copy risk:** High for the words, lower for the evidence and consistent
  implementation behind them.
- **Evaluate:** Independent reproduction of sample calculations, user ability to
  find answers, and whether detail increases calibrated trust instead of overload.
- **Usability link:** U-07, U-09, U-10, U-13, U-14

### D-11 — Accumulated clean historical data

- **State:** Partially implemented; the underlying asset compounds with time
- **Class:** Defensible asset
- **Opportunity:** Treat the dated, provenance-linked, structurally aware history
  as a core asset that supports trends, replay, change explanation, calibration,
  and future research.
- **Why it matters:** A competitor can copy a formula tomorrow but cannot recreate
  every trustworthy observation it failed to collect in the past.
- **Foundation:** Historical runs were backfilled; immutable snapshots and source
  provenance are audited; structural changes and reversals are contained.
- **Copy risk:** Low if data quality remains high. History without provenance or
  correction discipline is not the same asset.
- **Evaluate:** Completeness, lineage, restore tests, anomaly rates, supported
  as-of reconstruction, and demonstrated user-facing value from D-04/D-05.
- **Usability link:** U-06, U-17

## C. Retention and personal utility

### D-12 — Private ticket and result tracking

- **State:** Dependency-blocked
- **Class:** Potentially defensible personal longitudinal data and retention
- **Opportunity:** Let an authenticated user record tickets, cost, result, game,
  and date; summarize spend, winnings, and net over time and by game/price while
  warning against conclusions from small samples.
- **Why it matters:** It turns an occasional ranking visit into ongoing personal
  utility. At sufficient scale and with consent, aggregated patterns could inform
  product research, but private records must never be treated as proof of ticket-
  level predictability.
- **Foundation:** Authentication is implemented but not released. Tracking schema,
  privacy lifecycle, entry experience, and responsible-play presentation remain
  unbuilt.
- **Copy risk:** The form is copyable; trusted longitudinal history, privacy, and
  integration with Illinois game data compound.
- **Dependencies:** Authentication release, privacy/deletion/export decisions,
  security review, schema/API design, and responsible-play policy.
- **Evaluate:** Entry retention and accuracy, correction/deletion, privacy
  comprehension, budgeting usefulness, and signs of harmful interpretation.
- **Usability link:** U-23, U-24

### D-13 — Watchlists and meaningful-change alerts

- **State:** Dependency-blocked
- **Class:** Table stakes with retention value
- **Opportunity:** Let users follow selected games and receive controlled alerts
  for clearly defined data or status changes.
- **Why it matters:** It reduces repeated searching and gives historical monitoring
  an everyday use.
- **Foundation:** Game history and auth foundations exist; alert semantics and
  infrastructure do not.
- **Copy risk:** High. Advantage depends on change quality, restraint, and trust.
- **Dependencies:** Public auth, saved-game model, notification permissions,
  delivery operations, and responsible-play review.
- **Evaluate:** Useful return visits, opt-out and fatigue rates, comprehension of
  the trigger, and absence of false urgency.
- **Usability link:** U-20, U-23

## D. Necessary but not differentiating

### D-14 — Compare, deep-link, and share state

- **State:** Partially implemented
- **Class:** Table stakes with modest positioning value
- **Opportunity:** Preserve a selected goal and filters, compare a small set of
  games, and share a stable public view.
- **Why it matters:** It lets users discuss the differentiated analysis and makes
  research repeatable; it is not itself a moat.
- **Foundation:** Public routes, normalized ranking/detail data, and URL-backed
  strategy and price selections exist. Multi-game comparison and detail-page
  return/share behavior do not.
- **Evaluate:** Task completion, correct state restoration, mobile readability,
  and whether comparison improves decisions rather than adding metric overload.
- **Usability link:** U-02, U-03, U-19, U-21

### D-15 — Images, search, status, and official links

- **State:** Partially implemented
- **Class:** Table stakes
- **Opportunity:** Help a player identify the physical game, find it quickly,
  know whether it remains active, and inspect the official source.
- **Why it matters:** Missing basics can prevent users from reaching the analysis;
  adding them does not create sector dominance by itself.
- **Foundation:** Names, game numbers, prices, and provenance exist; ticket-image
  rights/source and lifecycle completeness must be audited.
- **Evaluate:** Find-the-game accuracy and speed, identifier-conflict handling,
  link freshness, accessibility, and mobile performance.
- **Usability link:** U-02, U-03, U-18, U-19

## E. Brand and product discipline

### D-16 — Evidence-first, responsible positioning

- **State:** Partially implemented
- **Class:** Positioning advantage and constraint on every feature
- **Opportunity:** Own a clear promise: choose the outcome you care about, see how
  much the answer depends on the jackpot, and inspect the evidence and limits.
- **Why it matters:** The strongest distinction may be not a proprietary score but
  a product that is unusually candid about goals, negative expected value,
  uncertainty, source problems, and what it cannot know.
- **Foundation:** Question-first strategies, ex-top analysis, fail-closed data,
  lumpy-tier fallbacks, and responsible-play principles align with the promise.
- **Copy risk:** Language is immediately copyable; consistent product decisions
  and accumulated trust are not.
- **Evaluate:** Message comprehension and recall, calibrated trust, preference,
  repeat use, and whether the experience discourages false certainty or chasing.
- **Usability link:** U-01, U-07, U-13, U-G1, U-G2, U-G5

One working positioning sentence—not approved marketing copy—is:

> Choose the outcome you care about. See which games fit it, how much the answer
> depends on the jackpot, and exactly what evidence supports it.

## What is and is not likely to be a moat

| Category | Most credible candidates | Important limitation |
| --- | --- | --- |
| Defensible | Clean Illinois history and provenance; Illinois-specific source/claim expertise; private longitudinal ticket records with consent | These require sustained operational quality, time, privacy, and demonstrated user value. |
| Distinctive positioning | Question-first rankings; jackpot-dependence decomposition; honest uncertainty; public explanation | Competitors can copy the interface or wording, so execution and evidence must keep improving. |
| Table stakes | Search, images, official links, filters, comparison, shareable state, watchlists | Missing them can hurt adoption, but shipping them does not establish leadership. |
| Not a moat | A chart by itself; a hidden formula; an exact-looking score; generic AI-generated commentary | These are easy to copy and can reduce trust when unsupported. |

## Retained observations from the initial sector scan

These observations explain where the inventory came from; they are not permanent
claims about competitors and should be rechecked before external marketing or a
later roadmap decision.

- Common analytical treatments included EV/ROI per dollar, average loss or
  return per ticket, published and adjusted odds, estimated tickets remaining,
  prize ratios, and movement relative to launch.
- Common presentation patterns included composite scores or grades, ticket
  images, search/status filters, direct game pages, and trend indicators.
- Better transparency patterns included distinguishing published from inferred
  values, showing `N/A` when evidence was insufficient, retaining exact official
  counts, and acknowledging claim-reporting lag.
- Retention patterns included watchlists, alerts, and scratch simulators. The
  first two remain candidates here; simulation was retained as a non-goal for
  the first usability program because it does not address comprehension and can
  create responsible-play concerns.
- The most promising gap was not another score. It was the combination of an
  explicit player goal, jackpot-dependence analysis, a narrow Illinois-specific
  adjustment, causal historical explanation, and visible provenance.

## How to evaluate a competitive candidate

Do not bundle the inventory into one “sector dominance” release. Select one
hypothesis at a time after its usability dependencies are ready:

1. **Comprehension:** Can users accurately explain it without coaching?
2. **Incremental utility:** Does it answer a decision question the current
   experience does not?
3. **Preference:** When compared on the same task, do users prefer it to a simpler
   baseline or representative competitor treatment—and why?
4. **Trust calibration:** Do users trust supported claims while recognizing the
   stated limits?
5. **Behavior over time:** Do they intentionally return, save, compare, or use the
   feature again, rather than merely click it once?
6. **Defensibility:** What compounds if the feature succeeds—history, operational
   learning, domain expertise, or consented private utility?
7. **Risk:** Could the feature encourage false precision, purchase pressure,
   privacy harm, or conclusions from small samples?

The result of an experiment may be to keep, simplify, rename, postpone, or remove
the candidate. A differentiated idea that users misunderstand has failed its
first requirement.
