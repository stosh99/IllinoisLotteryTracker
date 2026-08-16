# Illinois Lottery Tracker frontend

The first public frontend slice for comparing Illinois instant-ticket games by
one transparent strategy metric at a time.

The application reads the cutoff-strict publication surface through the
project's read-only API. It never connects to PostgreSQL directly and never
falls back to sample rankings when the API is missing or publication is
blocked. See [INTEGRATION.md](INTEGRATION.md) for the response contract.

## Run locally

Start the API from the project root:

```bash
.venv/bin/uvicorn illinois_lottery_tracker.api:app --reload
```

Then start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. In a same-origin production
deployment, no frontend environment setting is required. Set
`VITE_RANKINGS_URL` only when the API lives on a different origin. If port 8000
is occupied during development, set `VITE_API_PROXY_TARGET` to the API's local
origin.

## Checks

```bash
npm test
npm run build
npm run test:e2e
```

## Current scope

- Responsive site shell, comparison page, game-detail pages, and protected account route
- Click-through current prize-tier tables backed by the published analytics cutoff
- Dated estimated-ticket-sales and selectable prize-tier claim-progress charts
- Six player questions backed by the published analytics metrics
- Ticket-price filtering and ticket search
- URL-backed comparison state
- Explicit loading, error, empty, stale, and unavailable states
- Desktop table and mobile ranked-card layouts
- Visible source/model status and estimate caveats

Google provider credentials and tokens never enter the frontend. Authentication
state and the session-bound CSRF value are held only in React memory; browser
storage contains no session material. Authentication can remain disabled while
rankings operate normally. Personal ticket tracking is not built yet.
Synthetic ranking data exists only in the test fixture directory and is never
imported by runtime code.
