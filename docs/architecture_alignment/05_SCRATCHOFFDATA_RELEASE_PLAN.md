# Scratch-Off Data production release plan

**Written 2026-08-27.** This is the reconciled, execution-ready plan for taking
`main` at `8346888` ("Fix mobile header CI regression") to production and moving
the public edge to `scratchoffdata.com`. It merges three existing documents and
resolves their overlaps; it does not replace them:

| Document | Role in this plan |
|---|---|
| `deploy/DOMAIN_MIGRATION.md` | Canonical edge commands (vhosts, certs, redirects, rollback). Phases 1 and 3 reference its sections instead of duplicating them. |
| `docs/architecture_alignment/04_MIGRATION_RUNBOOK.md` (Track C) | Rationale and rollback posture for the feature deploy. Phase 2 executes it. |
| `deploy/AUTHENTICATION_OPERATIONS.md` + `docs/authentication_blueprint/RELEASE_GATE_STATUS.md` | Phase 4 (authentication), which is explicitly **not** part of this release. |

**The governing discipline** (from the runbook): edge cutover, feature+migration
deploy, and authentication enablement are three separately attributable changes.
This plan performs the first two in sequence and defers the third.

Two corrections to earlier draft step lists, made deliberate here:

1. The VPS is on branch `topology-cutover`, so the deploy is a **branch switch
   to `main`**, not a `git pull` of the current branch.
2. **No authentication, account, or ticket-history verification happens in this
   release.** Auth stays disabled (`DOMAIN_MIGRATION.md` forbids touching the
   private production environment or the Google OAuth client during cutover).
   The correct auth check in Phase 2/3 is that it still reports *unavailable*.

## Verified current state (2026-08-27)

| Fact | Value |
|---|---|
| Local/`origin/main` | `8346888` — rebrand, site notice, canonical tags, both nginx vhosts, `DOMAIN_MIGRATION.md`; CI green |
| VPS live production | The git checkout itself: `~stosh99/projects/IllinoisLotteryTracker` at `74614ec` on `topology-cutover` (clean tree); uvicorn system unit `illinois-lottery-prod-api` on loopback `127.0.0.1:8766` |
| VPS `.env` (project root) | Production config: `APP_ENV=production`, `EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod`, mode 0600. Fail-closed DB identity guard is active, so repo-root commands target prod safely |
| Prod DB revision | `0011_defer_auth_event_links` → needs `0012_user_ticket_entries` (purely additive: one table, two indexes) |
| Dev DB revision | `0012` (already applied) |
| DNS | `scratchoffdata.com` and `www.scratchoffdata.com` already resolve to `66.220.29.98` ✓ |
| New-domain nginx/cert | Not yet installed — Phase 1 creates them |
| Old-domain cert | Valid (expires 2026-11-10); old vhost currently serving the app |
| Node on VPS | v20.20.1 (satisfies frontend `engines >=20.19`) ✓ |
| `deploy/certbot/reload-nginx` hook | Present in repo ✓ |
| Collector/fanout | Healthy (system timer, 4 slots 03:00–06:00 CT; Chrome auto-updates via unattended-upgrades). Unaffected by this release |
| Collection watchdog | Installed (`ilt-collection-watchdog.timer`, 06:30 CT). Email delivery pending provider SMTP unblock; independent of this release |
| Known operational gap | Nightly status flags `BACKUP_STALE_OR_UNKNOWN` — scheduled prod backups are not running. Phase 2 takes a manual backup; scheduled backups are a P0 follow-up |

## Phase 0 — Preflight (read-only)

All satisfied as of 2026-08-27; re-verify on execution day:

- [ ] CI green on `origin/main` at the commit being deployed.
- [ ] DNS: `dig +short A scratchoffdata.com` and `www.` → VPS address only.
- [ ] At least one clean overnight fanout since the last VPS change
      (`journalctl -u illinois-lottery-source-fanout.service --since today`).
- [ ] VPS tree clean: `git -C ~/projects/IllinoisLotteryTracker status --short` empty.
- [ ] Record the rollback reference: currently deployed commit `74614ec`.
- [ ] No collection or import is running (avoid restarting mid-fanout; the
      collection window is 03:00–06:10 CT).

## Phase 1 — New-domain edge

Execute `deploy/DOMAIN_MIGRATION.md` sections 1–3 exactly:

1. §1 Bootstrap vhost + ACME webroot + reachability probe (both names must
   return the probe body over HTTP).
2. §2 Issue the `scratchoffdata.com` + `www` certificate via certbot webroot.
3. §3 Install the final vhost; run the section's full verification block.

Expected intermediate state: **both** domains serve the *old* application from
the same loopback origin. That is correct; do not proceed to old-domain
redirects yet. Rollback for this phase: `DOMAIN_MIGRATION.md` "Immediate
rollback" (restore the bootstrap vhost).

## Phase 2 — Application release (Track C)

Run on the VPS as `stosh99`, from `~/projects/IllinoisLotteryTracker`, in this
order and without long gaps (the checkout is the live tree):

```bash
cd ~/projects/IllinoisLotteryTracker

# 1. Manual production backup (writes dump + SHA-256 manifest).
.venv/bin/python scripts/backup_database.py \
  --target-dir ~/illinois-lottery-data/manual-backups/pre-0012

# 2. Confirm the starting revision, then switch to main.
.venv/bin/alembic current            # expect 0011_defer_auth_event_links
git fetch origin
git checkout main
git pull --ff-only origin main       # expect HEAD = 8346888
git log -1 --oneline

# 3. Backend deps (cheap even if unchanged), then migration.
.venv/bin/pip install -e ".[dev]" --quiet
.venv/bin/alembic upgrade head
.venv/bin/alembic current            # expect 0012_user_ticket_entries (head)

# 4. Frontend build.
cd frontend && npm ci && npm run build && cd ..

# 5. Restart the service.
sudo systemctl restart illinois-lottery-prod-api
systemctl status illinois-lottery-prod-api --no-pager | head -5
```

### Phase 2 verification (all against https://scratchoffdata.com)

- [ ] `/` renders; the **site notice appears once**, and is not re-shown after
      acknowledgment (origin-scoped `scratchoffdata.siteNotice`).
- [ ] `<link rel="canonical">` points at `https://scratchoffdata.com/...`.
- [ ] Rankings render; player-type switching works; outcome ladder intact.
- [ ] A game-detail page renders (`/games/<id>` direct load).
- [ ] `/tickets` (public game directory) renders on direct load.
- [ ] `/api/v1/rankings` returns `available: true` with a current date.
- [ ] `/api/v1/auth/session` reports **authenticationAvailable: false** —
      auth must still be off.
- [ ] No anonymous route reaches ticket entries (`/api/v1/ticket-entries`
      does not return data without auth).
- [ ] `ss -ltnp | grep 8766` shows uvicorn loopback-only.
- [ ] The old domain serves the same new release (it proxies the same origin).

Rollback: `git checkout 74614ec`, rebuild frontend, restart. Leaving `0012`
applied is harmless (additive); a schema rollback would restore the Phase 2
backup instead — do not `alembic downgrade` production.

## Phase 3 — Old-domain redirects

Only after every Phase 2 check passes: execute `DOMAIN_MIGRATION.md` §4
(redirect-only old vhost; verify all four old-origin cases 301 to
`https://scratchoffdata.com` preserving path and query) and §5 (renewal
dry-runs for both certificate lineages; keep both webroots and the
`reload-nginx` deploy hook).

Rollback: §"Immediate rollback", second block (restore the saved
`illinoislotterytracker.com.pre-scratchoffdata` vhost).

## Phase 4 — Authentication enablement (separate, later, reversible)

Explicitly **out of scope** for this release. When undertaken:

1. Clear `docs/authentication_blueprint/RELEASE_GATE_STATUS.md` prerequisites,
   now targeting the new domain (production Google OAuth web client with
   authorized origin `https://scratchoffdata.com` and redirect URI
   `https://scratchoffdata.com/api/v1/auth/google/callback`; published privacy
   notice/terms/contact; TLS proxy verification; protected secret delivery;
   encrypted backups; real-Google smoke test).
2. Update the protected production environment
   (`PUBLIC_BASE_URL=https://scratchoffdata.com`, Google client credentials,
   `AUTH_SECRET_KEYS`), then flip `AUTH_ENABLED=true` per
   `deploy/AUTHENTICATION_OPERATIONS.md`.
3. Only here do Google sign-in, account functions, and ticket history become
   verifiable in production.

## Post-release follow-ups (tracked, not blocking)

- **P0:** scheduled production backups + restore verification (nightly status
  currently reports `BACKUP_STALE_OR_UNKNOWN` / `RESTORE_VERIFICATION_STALE_OR_UNKNOWN`).
- Watchdog email delivery (ServerOptima outbound-SMTP unblock ticket, or switch
  the send step to an HTTPS email API).
- Stale doc claims that ticket tracking "is not built yet" (`README.md`,
  `frontend/README.md`, `docs/product_planning/README.md`).
- `CLAUDE.md` / `AGENTS.md` agent guide (runbook treats it as canonical; absent).
- Watch the first post-release overnight fanout and watchdog run.
