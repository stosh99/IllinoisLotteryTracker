# IllinoisLotteryTracker — Current Project Handoff

> **Superseded historical handoff.** This file describes the pre-blueprint
> implementation and its mutable legacy EV formulas. Do not use it as current
> operating or analytical guidance. The authoritative current documents are
> `docs/database_blueprint/README.md`,
> `docs/database_blueprint/IMPLEMENTATION_STATUS.md`, and
> `docs/project-synopses.md`.

## Project Goal

IllinoisLotteryTracker tracks Illinois Lottery instant ticket prize availability over time.

The project is data-first:
- preserve raw source files
- collect nightly unpaid-prizes snapshots
- parse official Illinois Lottery data
- store historical game/prize snapshots
- compute estimated ticket/EV metrics
- build UI later after the data pipeline is trustworthy

The app should eventually help users compare games by strategy, not claim to predict winners.

---

## Core Principles

- Preserve raw source files.
- Do not overwrite historical snapshots.
- Parser should be testable with fixtures.
- Unit tests should not use live network.
- Keep parser, importer, metrics, and reports separate.
- Use `game_number` as the integration key.
- Treat EV and ticket counts as estimates.
- Do not fabricate missing metadata.
- UI comes later.
- Use cautious wording:
  - “estimated”
  - “implied”
  - “appears”
  - “based on public unclaimed-prize data”
- Do not say unclaimed prizes equal unsold tickets.

---

## Current Data Sources

### Unpaid-prizes source

Official page:

https://www.illinoislottery.com/about-the-games/unpaid-instant-games-prizes

This source provides:
- active unpaid-prizes games
- game name
- ticket price
- game number
- weeks in market
- prize tiers
- original prize counts
- unclaimed/remaining prize counts

This is the nightly source.

### Instant-ticket detail metadata source

Starting hub:

https://www.illinoislottery.com/games-hub/instant-tickets

Detail pages provide:
- overall odds
- launch date
- category
- play style
- source URL
- top prize metadata

This is not currently part of the nightly automated pipeline.

---

## Implemented Workflows

### 1. Unpaid-prizes raw collection

Raw HTML is collected and preserved under `data/raw`.

Plain requests may return 403, so Playwright is used when needed.

Validation rejects:
- Cloudflare pages
- “Just a moment...” pages
- challenge-form pages
- wrong pages
- zero parsed games
- fewer than minimum expected games

---

### 2. Unpaid-prizes parser

Parser extracts:
- game_name / display_name
- ticket_price / data_price
- game_number
- weeks_in_market
- prize tiers:
  - prize_amount
  - total_prizes
  - unclaimed_prizes

Warnings are returned, not fatal.

---

### 3. Unpaid-prizes importer

Importer writes:
- `games`
- `game_snapshots`
- `prize_tier_snapshots`

Behavior:
- upserts games by `game_number`
- creates one `game_snapshot` per game per scrape run
- creates prize tier snapshots under each game snapshot
- computes raw snapshot totals:
  - total_original_prize_value
  - total_remaining_prize_value
  - total_original_winning_tickets
  - total_remaining_winning_tickets
  - top_prizes_original
  - top_prizes_remaining
  - weeks_in_market
- EV fields remain separate metrics logic
- idempotency is scoped to `(game_id, scrape_run_id)`

---

### 4. Instant-ticket detail discovery/parser/importer

Implemented:
- hub discovery
- detail page parsing
- metadata import into `games`

Detail metadata importer:
- upserts by `game_number`
- updates `games` only
- does not touch `game_snapshots`
- does not touch `prize_tier_snapshots`
- does not compute EV
- does not overwrite non-null fields with nulls
- reports missing game numbers, duplicates, price/name mismatches, warnings, unsupported fields

Known hub issue:
- Hub had 58 card entries but 57 unique game numbers.
- Duplicate was `jurassic-park` on page 2 and page 3.
- This was a hub/source duplicate, not a parser duplicate-game-number issue.

---

## Current Clean Database State

Development DB was reset and cleanly reloaded.

Clean reload counts:
- `scrape_runs`: 1
- `raw_source_snapshots`: 1
- `games`: 60
- `game_snapshots`: 60
- `prize_tier_snapshots`: 771
- games with `overall_odds_one_in`: 59
- games with `est_total_tickets`: 59
- snapshots with `estimated_ev`: 59
- snapshots with `estimated_ev_excluding_top_prize`: 59

Known metadata gap:
- `$250,000 CROSSWORD`
- `game_number`: 7587
- active on unpaid-prizes page
- no current detail page found
- slug `250000-crossword` resolves to newer game 7640
- odds-dependent metadata and metrics remain null intentionally

Targeted detail metadata successfully added for:
- `TRIPLE DYNAMITE 777`, game 7613
- `BIG BONUS BLOWOUT`, game 7565

---

## Metrics Implemented

Current metrics module:

`src/illinois_lottery_tracker/metrics.py`

Implemented functions:
- `estimate_total_tickets(total_original_winning_tickets, overall_odds_one_in)`
- `estimate_remaining_tickets(total_remaining_winning_tickets, overall_odds_one_in)`
- `estimate_ev(total_remaining_prize_value, estimated_remaining_tickets)`
- `estimate_ev_excluding_top_prize(prize_tiers, estimated_remaining_tickets)`
- `compute_snapshot_metrics(session)`

Current persisted metrics:
- `game.est_total_tickets`
- `game_snapshot.estimated_tickets_remaining`
- `game_snapshot.estimated_ev`
- `game_snapshot.estimated_ev_excluding_top_prize`

Important formulas:
- estimated total tickets =
  `total_original_winning_tickets * overall_odds_one_in`
- estimated remaining tickets =
  `total_remaining_winning_tickets * overall_odds_one_in`
- estimated EV =
  `total_remaining_prize_value / estimated_remaining_tickets`
- estimated EV excluding top prize =
  remaining prize value excluding top prize / estimated remaining tickets

Game 7587 remains null for odds-dependent metrics.

---

## Nightly Pipeline

Implemented nightly unpaid-prizes pipeline runner:

`scripts/run_nightly_unpaid_prizes_pipeline.py`

Pipeline does:
1. optionally skip if today's successful DB snapshot already exists
2. collect fresh unpaid-prizes raw HTML
3. preserve raw file
4. validate source content
5. parse unpaid-prizes data
6. import new snapshot set
7. compute metrics
8. print summary
9. exit nonzero on real validation/import failures

Duplicate guard:
- SHA256 content based
- prevents duplicate import of same raw HTML content
- clean skip exits 0
- `--force` can override intentionally

Scheduler completion guard:
- `--skip-if-today-imported`
- checks database state, not logs or raw files alone
- requires successful scrape run for today's source date
- requires enough game snapshots and at least one prize-tier snapshot
- lets repeated timer attempts exit without fetching once the day is complete

Confirmed behavior:

```text
SKIP: content (sha256=3141f3e10cc35e7c...) was already imported as scrape_run_id=1; use --force to override
```

Scheduling

User-level systemd timer is installed and enabled.

Files:

deploy/SYSTEMD_SETUP.md
deploy/systemd/illinois-lottery-nightly.service
deploy/systemd/illinois-lottery-nightly.timer

Installed user timer:

illinois-lottery-nightly.timer
triggers illinois-lottery-nightly.service
active/waiting
attempts around 03:00, 04:00, 05:00, and 06:00 EDT with jitter
later attempts skip if today's successful imported snapshot already exists
Persistent=true

Useful commands:

systemctl --user status illinois-lottery-nightly.timer
systemctl --user list-timers | grep illinois-lottery
journalctl --user -u illinois-lottery-nightly.service -n 100 --no-pager
Snapshot Change Report

Implemented read-only structural snapshot change report.

Focus:

new games
missing/removed games
prize structure/original prize pool changes

Does not yet report normal daily remaining-prize movement.

Important timestamp fix:

scrape_run.started_at means when pipeline/import ran.
raw_source_snapshot.captured_at means when the source HTML was captured.
snapshot change reports order by source captured time, not import time.
filename timestamp is preferred; file mtime fallback is used.
legacy runs without raw source snapshots fall back to scrape_run.started_at.

This fixed the issue where re-importing an older file later could make old source data look newer.

Overall Website Strategy

The website should not have one universal “best game.”

It should help users find:

Best overall estimated value
Best practical value excluding top prizes
Best practical value excluding prizes over $600
Best for getting money back
Best for moderate upside
Best jackpot chase
Games to be careful with

Player styles:

Money-Back Player
Steady Value Player
Moderate Upside Player
Jackpot Hunter
Avoid-Bad-Games Player

Core positioning:

Do not say “find winning tickets.”
Say “compare Illinois instant tickets using public prize-availability data.”
The product promise is to make public lottery data easier to understand.

A detailed strategy file was drafted as:

overall_wesite_startegy.md

Note: filename currently has typo wesite; consider either keeping as-is if already created or renaming to overall_website_strategy.md.

Claim-Activity / Popularity Proxy Future Milestone

Future CC prompts should include claim-activity/popularity-proxy metrics as a future milestone.

Important wording:

Use “claim activity”
Use “most active games”
Use “newly recorded claimed prizes”
Use “implied ticket activity”
Do not definitively say “most popular” or “tickets sold”

Candidate metrics:

newly claimed winning tickets
newly claimed prize value
claim rate
implied ticket activity using overall odds
activity by prize bucket
rolling windows:
1-day
7-day
14-day
30-day

This should likely come after normalized metrics/launch comparison and before or alongside prize bucket/player-style reports.

Next Recommended CC Task

Add Phase 1 normalized snapshot metrics and launch-comparison metrics.

Do not build UI yet.
Do not add player-style composite scores yet.
Do not add prize-bucket metrics yet.
Do not fetch live network data.
Do not fabricate metadata for game 7587.

Metrics to add:

estimated_payout_ratio
estimated_house_edge
estimated_payout_ratio_excluding_top_prize
launch_ev
launch_payout_ratio
ev_vs_launch_ratio
remaining_prize_value_pct
remaining_winning_tickets_pct
top_prize_remaining_pct
top_prize_depleted

Store these on game_snapshots unless there is a clearly justified alternative.

Conceptual formulas:

estimated_payout_ratio =
estimated_ev / ticket_price
estimated_house_edge =
1 - estimated_payout_ratio
estimated_payout_ratio_excluding_top_prize =
estimated_ev_excluding_top_prize / ticket_price
launch_ev =
total_original_prize_value / est_total_tickets
launch_payout_ratio =
launch_ev / ticket_price
ev_vs_launch_ratio =
estimated_ev / launch_ev
remaining_prize_value_pct =
total_remaining_prize_value / total_original_prize_value
remaining_winning_tickets_pct =
total_remaining_winning_tickets / total_original_winning_tickets
top_prize_remaining_pct =
top_prizes_remaining / top_prizes_original
top_prize_depleted =
top_prizes_original > 0 and top_prizes_remaining == 0

Missing or zero denominators should produce null/None, not exceptions.

Success criteria should be specific to the task and included in every CC prompt.

User Preferences for Future Prompts

The user primarily uses Claude Code, abbreviated CC.

Codex may be used in the background for parallel tasks.

When providing coding-agent prompts:

write them for CC unless told otherwise
keep them easy to copy/paste
include a specific Success criteria section every time
success criteria must be task-specific, not generic boilerplate
coe
