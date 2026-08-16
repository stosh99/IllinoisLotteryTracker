# Architecture alignment — analysis approach

Date: 2026-08-15
Scope: `IllinoisLotteryTracker` (this repo) and `mediahub`
(`/home/stosh99/projects/MediaDashboard`), both hosted on the same VPS.

## Why this analysis exists

The owner intended IllinoisLotteryTracker to be set up architecturally like
mediahub: **the project directory on the VPS *is* production**, with a separate
development *database* but no separate development *application* on the box.

What was actually built is different. This repository remained the development
application, and a second production application tree was created at
`/home/stosh99/apps/illinois-lottery-tracker/` that the owner did not know about
until 2026-08-15. Both applications run simultaneously on the production VPS.

The goal is to make both projects architecturally similar, using mediahub as the
primary model, while adopting the specific things IllinoisLotteryTracker does
better. Neither project should have a development application instance running on
the production VPS.

## Rules for this analysis

1. **The running system is the truth, not the documentation.** Every claim in the
   comparison must come from the live box — `systemctl cat`, the filesystem,
   `psql`, `nginx -T`, `git rev-parse` — not from a project's own docs. Both
   projects have documentation that is already out of date, and at least one
   documented fact was found to be wrong (see §Evidence sources).
2. **Compare topology before code.** Where processes run, which tree they run
   from, and which database they attach to matter more than internal module
   design. Internal application design is explicitly out of scope.
3. **Separate "different" from "wrong."** Two projects may legitimately differ
   (a React build step vs. no build step). Only differences that cost safety,
   effort, or clarity are candidates for change.
4. **Direction of borrowing is per-dimension, not per-project.** mediahub is the
   default model, but where IllinoisLotteryTracker is demonstrably safer, the
   borrowing runs the other way.
5. **No changes during analysis.** This pass is read-only. Recommendations are
   proposals; nothing is executed without an explicit go-ahead.
6. **Every recommendation names its risk and its rollback.** Production is live
   and public, and one of these projects is being restructured underneath a
   running service.

## Dimensions examined

| # | Dimension | The question it answers |
|---|---|---|
| D1 | Runtime topology | What processes run on the VPS, from which directory, on which port? |
| D2 | Deploy mechanism | How does new code reach production? Working tree, or release tree + symlink? |
| D3 | Configuration and secrets | Where do env values live, and how does a process choose dev vs. prod values? |
| D4 | Database inventory and identity | Which databases and roles exist, and what stops a process attaching to the wrong one? |
| D5 | Development workflow | Where does development happen, and against which data? |
| D6 | Scheduled and background work | In-process scheduler or external systemd timer? |
| D7 | Frontend build and serving | Is there a build step, and who serves the assets? |
| D8 | Public edge | nginx, TLS, redirects, headers. |
| D9 | Backup and rollback | What exists to recover from, and is it verified? |
| D10 | Tests | What do tests run against, and how is the live database protected? |
| D11 | Repository and agent conventions | CLAUDE.md/AGENTS.md, docs layout, tracked infrastructure config. |
| D12 | Footprint hygiene | Disk, stale trees, leftover units and databases. |

## Evidence sources used

- `systemctl cat` / `systemctl --user list-units` / `list-timers` for all units.
- Filesystem inspection of both project roots and
  `/home/stosh99/apps/illinois-lottery-tracker/`.
- `sudo -u postgres psql` for the database and role inventory.
- `/etc/nginx/sites-enabled/` and the tracked `deploy/nginx/` configs.
- `git rev-parse` / `git log` in both the working tree and the release tree, to
  measure drift.
- `~/.config/illinois-lottery-tracker/*.env` and both project-root `.env` files,
  read for **keys and target database names only** — secret values were not
  transcribed into the comparison.

**Documentation found to be wrong during this pass:** mediahub's `CLAUDE.md`
states the `mediahub` production database is owned by role `mediahub`. It is
actually owned by role `mediahub_test`. This is the reason for rule 1.

## Deliverables

1. `01_ANALYSIS_APPROACH.md` — this file.
2. `02_COMPARISON.md` — the evidence-based side-by-side across D1–D12.
3. `03_RECOMMENDATIONS.md` — the proposed target architecture, the per-project
   change list, sequencing, risks, and the open decisions for the owner.

## What this analysis deliberately does not cover

- Internal application/module design, data models, and product behavior.
- The Track 1 usability milestones and the open owner review of milestone 4.
- Whether authentication should be enabled. That remains a separate decision
  gated by `deploy/AUTHENTICATION_OPERATIONS.md`.
