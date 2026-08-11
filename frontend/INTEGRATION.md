# Frontend ranking integration contract

This document defines the seam between the initial frontend and the read-only
FastAPI application endpoint in `illinois_lottery_tracker.api`.

## Endpoint

```text
GET /api/v1/rankings
```

The frontend currently fetches the complete response once and applies the
small, current-scale filters locally. At roughly 57 games and nine strategy
keys this keeps interaction instant and the API contract simple. Server-side
filtering can be added later without changing the record shape.

Set the endpoint with:

```text
VITE_RANKINGS_URL=https://example.test/api/v1/rankings
```

When the variable is absent, the app requests the same-origin
`/api/v1/rankings` path. The Vite development server proxies that path to the
local API. A failed request produces an explicit retryable error; it never
loads substitute ranking data.

## Fail-closed rule

The API derives `status` from the canonical ranking-status surface and derives
rows only from the cutoff-strict current ranking view. Both reads occur in one
repeatable-read, read-only transaction.

- If `status.available` is `false`, `rankings` must be an empty array.
- Never return rows from an older analytics cutoff as though they were current.
- Never return experimental or rejected-model rows through this endpoint.
- Never treat `games.is_active` as ranking eligibility.
- Source and catalog timestamps must be returned independently.

The frontend validates the unavailable-plus-empty invariant at its network
boundary and rejects a contradictory response.

## Response shape

JSON uses camelCase at the frontend boundary:

```json
{
  "generatedAt": "2026-08-08T12:00:00Z",
  "mode": "live",
  "status": {
    "available": false,
    "reasonCode": "ANALYTICS_UNAVAILABLE",
    "sourceObservedAt": "2026-08-08T07:04:43Z",
    "catalogObservedAt": "2026-08-08T08:12:18Z",
    "modelVersion": null,
    "sourceRunId": 91,
    "catalogRunId": 92,
    "analyticsRunId": null
  },
  "rankings": []
}
```

When available, each long-form ranking row is:

```json
{
  "analyticsRunId": 123,
  "gameId": 42,
  "gameNumber": "7654",
  "gameName": "Example game",
  "ticketPrice": 10,
  "strategyKey": "value_ex_top",
  "metricValue": 0.704,
  "oneInValue": null,
  "launchMetricValue": 0.682,
  "relativeToLaunch": 1.032258,
  "targetTierCount": 11,
  "targetCountCoverage": 1.0,
  "targetValueCoverage": 1.0,
  "metricStatus": "complete",
  "lowestConfidence": "moderate",
  "containsLumpyTier": false,
  "sourceObservedAt": "2026-08-08T07:04:43Z",
  "catalogObservedAt": "2026-08-08T08:12:18Z",
  "modelVersion": "2.0.0",
  "rankOverall": 1,
  "rankWithinTicketPrice": 1,
  "estimatedEvFull": 7.42,
  "estimatedEvExTop": 7.04,
  "topPrizeAmount": 500000,
  "topPrizesRemaining": 2,
  "weeksInMarket": 22
}
```

The authoritative TypeScript definitions are in `src/types/rankings.ts`.
Runtime validation rejects missing, malformed, non-finite, out-of-range, or
cutoff-inconsistent fields before the response reaches React. The frontend
contract tests must pass before a live endpoint is enabled.

## Database mapping

Most fields map directly from the ranking, status, strategy, game, and current
snapshot views introduced by the database blueprint and review remediation.
The API assembles the response in a read-only transaction so status and
rows cannot observe different cutoffs.

`estimatedEvFull`, `estimatedEvExTop`, top-prize facts, game name, and weeks in
market are supporting display fields. Full and ex-top EV must come from the
corresponding versioned strategy metrics at the same current analytics/source
cutoff; neither may be populated from retained legacy estimated columns.

The frontend selects the supporting EV that matches the active strategy.
Strategies that exclude the top tier display and label `estimatedEvExTop`;
full-value, money-back, and jackpot views display and label `estimatedEvFull`.
