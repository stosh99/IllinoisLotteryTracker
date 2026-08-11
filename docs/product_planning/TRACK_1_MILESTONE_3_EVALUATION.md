# Track 1 milestone 3 evaluation

Last updated: 2026-08-11

Status: implementation and engineering evaluation complete; observed-user
discoverability evaluation pending

## Outcome

U-21 is implemented. Strategy and ticket-price choices now survive refresh,
browser Back/Forward, detail navigation, return navigation, new-tab-capable
hrefs, and copied public links. Detail pages visibly state the comparison
context to which they return.

The URL is the only new persistence surface. No local storage, account field,
database value, API contract, or server-side saved view was introduced.

## State and privacy checks

- React Router location is the comparison’s single state source.
- Strategy and price updates create committed browser-history entries.
- Default strategy and `all` price remain omitted from canonical URLs.
- Canonical parameter order is strategy, then price.
- Card links, table links, and clickable rows carry the same public context.
- Detail return and primary navigation links reconstruct the comparison URL.
- Copied URLs are built from typed public state rather than copying the current
  query string wholesale.
- Unknown parameters, OAuth result values, and other transient state are absent
  from copied URLs.
- Invalid strategies and non-positive prices fall back to the public defaults.
- Clipboard denial produces visible failure guidance and never claims success.

## Automated results

| Check | Result |
| --- | --- |
| Frontend unit and component tests | 66 passed across 13 files |
| TypeScript and production build | Passed |
| Chrome Playwright tests | 20 passed across desktop and 390px mobile projects |
| Whitespace validation | `git diff --check` passed |

The Playwright state journey covers configured direct load, refresh, committed
strategy change, Back, Forward, a real detail href, detail load, return-context
copy, canonical game-link copying, comparison return, canonical comparison-link
copying, and invalid/transient query input.

## Browser and visual evaluation

Chrome was evaluated at 1366 by 900 and 390 by 844. Configured comparison and
detail full-page captures were reviewed.

- The comparison copy action fits beside the full-results heading on desktop
  and becomes a full-width 44px control on mobile.
- The detail return context and game-copy action have a clear desktop split and
  a text-first vertical mobile order.
- Copy success remains adjacent to the control that caused it.
- No control covers analytical evidence or causes page-level horizontal
  overflow.
- Core navigation remains ordinary links with complete hrefs; clipboard access
  is optional enhancement rather than a routing dependency.

No remaining functional or responsive defect was found.

## Interpretation risks retained for observed users

- Some users may not discover “Copy this view” below the card carousel until
  they reach the complete-results heading.
- “Returns to Overall value · $10 tickets” may be clear to experienced users but
  should still be checked with first-time visitors.
- Users may expect carousel position to persist even though it is intentionally
  transient and omitted from shared URLs.

## Next planning choice

The remaining prioritized opportunities should stay separate:

- U-15 adds an outcome ladder and therefore needs careful language evaluation.
- U-18 is a discovery milestone whose scope depends on trustworthy official
  status, link, and image availability.
- U-17 is a historical explanation milestone and has the largest data and
  interpretation surface.

If proceeding without user recruitment, audit U-18’s available fields and
assets before choosing between U-15 and a bounded discovery build.
