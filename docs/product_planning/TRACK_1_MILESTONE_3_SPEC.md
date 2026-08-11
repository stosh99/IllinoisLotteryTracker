# Track 1 milestone 3: durable comparison state

Last updated: 2026-08-11

Status: implemented and browser-verified; observed-user discoverability check pending

## Objective

Make a configured public comparison durable enough to refresh, revisit, open in
another tab, and share without losing the player’s strategy or ticket-price
context. Game-detail navigation must preserve a useful route back to that exact
comparison.

This milestone implements U-21. It changes browser routing and frontend copy
only. It does not change APIs, database state, authentication, analytics,
ranking formulas, or server-side persistence.

## Public state contract

The URL is the canonical and only persistence surface for this milestone.

| State | Comparison URL | Detail URL | Persist elsewhere |
| --- | --- | --- | --- |
| Strategy | `strategy` query parameter when non-default | carried as the same query parameter | No |
| Ticket price | `price` query parameter when not `all` | carried as the same query parameter | No |
| Current game | Not applicable | stable numeric path id | No |
| Comparison anchor | `#rankings` for explicit return/share actions | Not encoded | No |
| Hover, carousel scroll, expanded glossary/charts | Not encoded | Not encoded | No |
| Account state, tokens, private data | Never encoded | Never encoded | Existing secure auth only |

Defaults remain omitted. Parameter order is deterministic: `strategy`, then
`price`. Labels and game names are not URL identifiers.

## Behavior contract

### Comparison

- Strategy and price controls push committed choices into browser history.
- Refresh and direct load reconstruct the same view from the URL without first
  flashing an unrelated configured state.
- Back and Forward restore prior strategy/price combinations.
- Unsupported strategies and non-positive prices fall back safely to defaults.
- A positive price that is valid in shape but absent from current data preserves
  the requested filter and uses the existing no-results/reset state.
- A “Copy this view” action copies a canonical absolute URL containing only the
  stable public state plus `#rankings`.

### Detail and return

- Card links, table links, and clickable table rows include the selected
  strategy and price in the detail URL.
- These are real hrefs, so open-in-new-tab and link copying work without
  JavaScript reconstruction.
- The detail page visibly states the comparison context it will return to.
- “Back to comparison” returns to the same strategy and price at `#rankings`.
- Primary navigation links from detail preserve the public comparison context
  where the destination belongs to the comparison page.
- “Copy this game view” copies the canonical game URL with public comparison
  context but no transient or private query state.
- A direct detail URL with no query returns to the default comparison.

### Copy feedback

- Copy controls are native buttons with at least a 44px target.
- Success and failure feedback uses a polite live region and visible text.
- If the Clipboard API is unavailable or denied, the page tells the user to copy
  the browser address; it must not claim success.
- Repeated copy actions do not create browser-history entries.

## Technical design

- **Analytical job:** preserve the exact ranking claim and filter context across
  browser/navigation boundaries.
- **Artifact family:** URL-backed React route state, ordinary links, two compact
  copy controls, and visible active-context text.
- **Ownership:** React Router owns location changes and history. Pure URL helpers
  own parsing, canonical serialization, comparison/detail href generation, and
  user-facing context labels. React components own copy feedback.
- **Instances:** one comparison-state hook, one comparison copy control, and at
  most one detail copy control per rendered page.
- **Renderer:** semantic HTML and existing React/CSS; no visualization or routing
  dependency is added.
- **Hydration/client boundary:** this Vite application is client-rendered. URL
  parsing occurs synchronously from React Router location state.
- **Persistence:** URL only. No `localStorage`, IndexedDB, cookie, account field,
  or remote saved-view id.
- **Mobile:** controls wrap beneath nearby headings without covering data or
  requiring horizontal scrolling.
- **Performance:** constant string/URL operations with no request, polling, or
  bundle-size concern.
- **Fallback:** links still contain complete relative hrefs if clipboard access
  fails. Direct navigation remains the primary path.

## Security and privacy guardrails

- Canonical copy helpers accept only the stable strategy, price, and numeric
  game id; they do not copy the current query string wholesale.
- OAuth results, session identifiers, CSRF values, email addresses, ticket data,
  and unknown query parameters must not enter copied URLs.
- Public comparison state is non-sensitive and remains usable without login.

## Automated acceptance

- Pure unit tests cover default omission, deterministic ordering, invalid
  parsing, comparison hrefs, detail hrefs, absolute canonical URLs, and context
  labels.
- Component tests cover link hrefs, visible return context, copy success/failure,
  and absence of transient query parameters.
- Playwright covers refresh, Back/Forward, direct configured load, detail and
  keyboard return, link href suitability for a new tab, clipboard success,
  invalid state, and desktop/mobile containment.
- Existing unit, build, authentication, and usability suites pass.
- `git diff --check` passes.

## Evaluation boundary

Engineering verification can establish deterministic routing and copying. A
later user session should still test whether “Copy this view” is discoverable
and whether the visible return-context wording matches what players expect the
Back action to restore.
