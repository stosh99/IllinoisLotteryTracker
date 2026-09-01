# Architecture alignment — merged migration runbook

Date: 2026-08-15. **Planning only. No production changes are authorized by this
document.**

## What this supersedes

This is the single canonical plan. It merges two independent analyses that
reached the same target architecture:

- `docs/architecture_consistency.md` (Codex) — contributes the phase/checkpoint
  structure, the three-risk separation, the rollback procedure, and the collector
  credential-stripping idea. **Superseded by this file.**
- `docs/architecture_alignment/01–03` (Claude) — contributes the evidence base,
  the mediahub-side changes, and the items Codex's lottery-only scope missed.
  `03_RECOMMENDATIONS.md` remains useful as rationale; execution lives here.

Where the two disagreed, the resolution is recorded in "Settled decisions".

## Settled decisions (owner, 2026-08-15)

1. **This project checkout becomes production.** Not a release tree elsewhere.
2. **Both databases stay** — `illinois_lottery_tracker_prod` and
   `illinois_lottery_tracker_dev`.
3. **No dev app on the VPS, for either project.** mediahub already complies.
4. **No development happens on the production server.** All development, including
   the topology changes in this plan, is authored on an external machine, pushed,
   and only then pulled by the VPS.
5. **One canonical `.env` in the project root** holds production configuration.
   `~/.config/illinois-lottery-tracker/{production,development,collector}.env` are
   **retired**. *(Owner instruction; resolves the one disagreement between the two
   plans in Codex's favor.)*
6. **System-level systemd**, running as `stosh99`, for the API and the fanout.
7. **Downtime is acceptable** — the owner is the only user of both sites. Prefer
   simple, verifiable sequences over zero-downtime choreography.
8. **The fanout keeps importing into both databases** from one source bundle.
9. Rollback artifacts are retained **seven days** after cutover.

## What this plan does *not* block

Feature development continues throughout. stoshai already has its own checkout,
venv, and access to `illinois_lottery_tracker_dev` — it applied `0012` there — so
it is already operating the way the target architecture intends. Track A changes
nothing about it: both databases stay, and the nightly fanout keeps feeding dev.

- **Merge friction is near zero.** `68680c4` touches no `deploy/`, `scripts/`,
  `pyproject.toml`, or `alembic.ini`; the topology branch touches almost nothing
  else. The two lines of work barely overlap on disk.
- **The 7-day soak is passive.** It gates deleting the old release tree only. It
  does not gate development, and after the Track C revision it does not gate
  deploying features either.
- **The only real constraint:** do not plan a production deploy during Track A
  itself, while the VPS sits on `topology-cutover` (roughly a day). Develop
  freely; just do not ship mid-cutover.

Doing Track A sooner actively helps feature work: until it is done, the only way
to reach production is the release-tree mechanism that is being retired.

## Target architecture (both projects)

| Aspect | Standard |
|---|---|
| Apps on the VPS | Exactly one per project, production |
| Prod code | The git checkout in `~/projects/<Project>` |
| Prod config | Project-root `.env`, mode `0600`, gitignored |
| Databases | `<app>_prod` / `<app>_dev` / `<app>_test`, each with its own role |
| Wrong-DB protection | Fail-closed identity guard (`APP_ENV` + `EXPECTED_DATABASE_NAME`, checked against the URL *and* `SELECT current_database()`) |
| Development | External machines only, over an SSH tunnel to the dev DB |
| Scheduled work | External systemd timer |
| Service | System unit, `User=stosh99`, uvicorn `--proxy-headers --forwarded-allow-ips 127.0.0.1` |
| Edge | Shared nginx + certbot; config tracked in `deploy/nginx/` |
| Backups | `pg_dump` + SHA-256 manifest + restore-verification marker |
| Agent guide | `CLAUDE.md` canonical, `AGENTS.md` a real symlink to it |
| Deploy | `git pull` → build frontend → `pip install -e .` if deps changed → `alembic upgrade head` **when intended** → restart |

## The three risks, kept separate

Codex's central discipline, adopted wholesale:

1. **Topology correction** (Track A) — no schema change, no feature deployment.
2. **Feature + migration `0012` deployment** (Track C) — after one clean
   post-cutover fanout run (see Track C for the revised timing).
3. **Authentication enablement** — later still, separately, reversibly.

Bundling any two of these makes a failure impossible to attribute.

## Current state (verified 2026-08-15)

| Fact | Value |
|---|---|
| Live production code | release tree at `ac6e3b8` |
| VPS checkout | `65b3eef` (clean; pulled to `68680c4` then committed these docs). The checkout is currently **inert** — the live site runs from the release tree, so this pull changed nothing in production. The dev API would pick up the newer code only on restart; it is slated for removal in A4 |
| `origin/main` | `65b3eef` (= `68680c4` feature work + this documentation) |
| Feature commit size | 55 files, +4519/−1045; adds `0012_user_ticket_entries`, `ticket_entries_api.py`; modifies `alembic/env.py` |
| Feature commit infra footprint | **none** — no `deploy/`, `pyproject.toml`, `alembic.ini`, or `scripts/` changes |
| Prod DB revision | `0011_defer_auth_event_links` |
| **Dev DB revision** | **`0012_user_ticket_entries`** — already migrated from stoshai |
| Services | `illinois-lottery-prod-api` (user), `illinois-lottery-dev-api` (user, running), `illinois-lottery-source-fanout` (user, timer active) |

### The branching wrinkle

Codex's plan says to build the topology change from clean revision `e52d9c1`.
That was written when the feature work was uncommitted. It is now `68680c4` on
`main`, so **the topology work cannot simply sit on `main`** — deploying `main`
would drag the feature code and `0012` along with it, violating risk separation.

Resolution:

- Create branch **`topology-cutover` from `e52d9c1`**. All Track A work lands there.
- The VPS checks out `topology-cutover` for the cutover.
- Merge `topology-cutover` into `main` whenever convenient (main then has both).
- At Track C, the VPS switches to `main` and the feature work deploys deliberately.

This runbook was authored on `main` (`65b3eef`). At the owner's request, the five
architecture-planning documents were later copied onto `topology-cutover` as a
documentation-only change so the execution reference remains visible. No feature
code or migration `0012` accompanied that copy.

---

# Track A — Lottery topology cutover

## Phase A0 — Prepare on the development machine

All of this happens on stoshai, not the VPS.

1. Branch `topology-cutover` from `e52d9c1`.
2. **Config refactor:** production values move to the project-root `.env`.
   Canonical contents (categories, not values):

   ```dotenv
   APP_ENV=production
   EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod
   DATABASE_URL=<production URL>
   DEV_DATABASE_URL=<development URL>      # inert to the app; import tooling only
   RAW_DATA_DIR=/home/stosh99/illinois-lottery-data/source-captures

   PUBLIC_BASE_URL=https://scratchoffdata.com
   GOOGLE_OIDC_CLIENT_ID=<verified from Google>
   GOOGLE_OIDC_CLIENT_SECRET=<re-copied from Google — the current value is mistyped>
   AUTH_SECRET_KEYS=<newly generated; the old value was exposed in conversation>
   AUTH_ENABLED=false
   ```

3. **Pipeline refactor** (one code root, no `~/.config` env files):
   - production import uses `DATABASE_URL`;
   - development import maps `DEV_DATABASE_URL` → `DATABASE_URL` internally;
   - the **collector subprocess has both URLs stripped from its environment**, so
     it is structurally incapable of reaching a database *(Codex's idea — keep it)*;
   - identity guards mandatory on both import paths;
   - the two imports stay independent, so one failure cannot hide or prevent the other;
   - credentials never appear in argv or logs.
4. **systemd units** (tracked in `deploy/systemd/`): rewrite the prod API as a
   system unit — `User=stosh99`,
   `WorkingDirectory=/home/stosh99/projects/IllinoisLotteryTracker`, port 8766,
   `--proxy-headers --forwarded-allow-ips 127.0.0.1`, no `EnvironmentFile`.
   Rewrite the fanout as a system unit; its non-secret settings (`APP_ENV`,
   `RAW_DATA_DIR`, `AUTH_ENABLED`) become `Environment=` lines, retiring
   `collector.env`.
5. **Add `CLAUDE.md`** + `ln -s CLAUDE.md AGENTS.md`. It must state, at the top,
   that the VPS checkout is production and that agent/IDE sessions belong on a
   development machine.
6. **Docs:** replace `docs/environment_separation/` guidance with deployment,
   remote-dev onboarding, migration rehearsal, collection/import ops, and rollback.
7. Run the full suite, ruff, frontend build, and e2e. Push the branch.

**Checkpoint A0 — proceed only when:** the branch is clean and pushed; `0012` and
ticket-tracking code are absent from it; tests prove that production config
resolves only the production DB, development config only the development DB,
`APP_ENV=production` against the dev DB **fails closed**, and the collector
receives no database credentials.

## Phase A1 — Remote development proven

Before removing the on-box dev app, prove the replacement works.

**First, establish how stoshai currently reaches the VPS Postgres.** It
demonstrably connects — it applied `0012` to the dev database — but the path is
unverified. mediahub's documented, supervised tunnel setup exists on the
*Windows* dev PC (`docs/REMOTE_DEV.md`), not necessarily on stoshai. If stoshai
connects any way other than an SSH tunnel to a localhost-bound Postgres (e.g. a
direct LAN connection to an exposed port), bring it onto the tunnel model as part
of this phase — the target architecture's security posture assumes the tunnel is
the only path in. One tunnel reaches the whole Postgres instance, so mediahub
and lottery share it.

Per development machine: clone, venv + `pip install -e ".[dev]"`, **`npm ci` and
Playwright browsers** (lottery has a frontend build mediahub does not), local
`.env` with `APP_ENV=development`,
`EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev`, and a `DATABASE_URL`
through `127.0.0.1:5433`. No production credentials ever land on a dev machine;
each generates its own `AUTH_SECRET_KEYS`.

**Checkpoint A1 — proceed only when** a dev checkout starts locally, reads and
writes only the dev DB, **refuses to connect to production**, runs its full test
suite, and rehearses a migration against dev — all with no dev app on the VPS.

## Phase A2 — Back up and capture rollback state

On the VPS. Dumps of both databases with restore verification into disposable
databases; copies of the current env files, installed unit files, git revisions,
the `current` symlink target, service/timer states, nginx config; and baseline
public API and browser results. Record both DB identities, both Alembic
revisions, critical row counts, and the latest successful source import —
without exposing credentials.

**Checkpoint A2 — proceed only when** both dumps restore successfully, the
existing release-based service can demonstrably be restored, the public site
passes baseline smoke tests, and the rollback procedure is written down.

## Phase A3 — Stage the production candidate

1. Confirm the VPS checkout is clean; `git fetch`; `git checkout topology-cutover`.
2. Install locked backend deps; build the frontend.
3. Create the canonical `.env` (mode `0600`) with the corrected Google secret and
   a **newly generated** `AUTH_SECRET_KEYS`. Keep `AUTH_ENABLED=false`.
4. Delete the old malformed project `.env` content in the process — it must not
   survive.
5. Confirm the DB revision **without upgrading it** (prod stays at `0011`).
6. Start a short-lived candidate on an unused loopback port and verify it connects
   to `illinois_lottery_tracker_prod`, serves rankings and game details, reports
   authentication unavailable, writes nothing unexpected, and serves the intended
   frontend build. Stop it immediately — it is not a dev service.

**Checkpoint A3 — proceed only when** the checkout is clean at the approved
commit, `.env` resolves only the production DB, the identity guard passes, the
candidate smoke test succeeds, auth is still unavailable, and the existing public
service is still up.

## Phase A4 — Cutover

1. Pause the fanout timer; confirm no collection or import is running.
2. Stop the release-based production service.
3. **Stop and permanently disable the VPS development API.**
4. Install and start the system-level production service on `127.0.0.1:8766`
   (nginx unchanged).
5. Verify database identity *before* traffic checks.
6. Loopback smoke tests, then public HTTPS smoke tests.
7. Install the revised system-level collector/fanout unit; re-enable its timer.

**Do not:** apply `0012`; enable auth; deploy feature work; delete the old release
tree; delete the old external env files.

**Checkpoint A4 — cutover succeeds only when** exactly one lottery web app runs on
the VPS; no dev API is active or enabled; production runs from
`~/projects/IllinoisLotteryTracker` against `illinois_lottery_tracker_prod`; nginx
serves site and API; auth remains unavailable; and the four neighbouring sites are
unaffected. **Any failure → roll back immediately.**

## Phase A5 — Pipeline verification

Run one manual collection and fanout. Confirm the collector holds no database
URL; both imports are reported independently; the same bundle reached both
databases; source-run identities and row counts line up; the public data
timestamp advances; and a failure in one target would stay visible without
blocking the other.

**Checkpoint A5 — proceed only when** one manual fanout and at least one
scheduled fanout have succeeded and no credentials appear in logs.

## Phase A6 — Soak (7 days) and cleanup

Retain for seven days: the old release tree, old unit files, old external env
files, database backups, previous fanout configuration. Monitor uptime, timer
results, import results, identity checks, the public data timestamp, nginx
errors, and neighbouring sites.

After the soak **and explicit owner approval**: delete the release tree
(`prod-ac6e3b83dbc0`, 466 MB) and the four `shadow-*` trees; remove the dev API
unit, the shadow service, and the legacy `illinois-lottery-nightly.*` units;
archive or securely remove the retired `~/.config/illinois-lottery-tracker/*.env`
files; drop the surplus databases `lottery_dev`, `lottery_claude_test`,
`lottery_codex_test`; mark release-tree deployment docs obsolete.

**Also in cleanup:** create `illinois_lottery_tracker_test` with its own role and
port mediahub's `conftest.py` **session advisory lock**, so two development
machines cannot run the suite against one shared test DB simultaneously. Today
the 31 Postgres tests simply skip.

---

# Track B — mediahub alignment

Independent of Track A; can run in parallel or first. Codex's plan does not cover
mediahub at all, and two of these are the highest-risk findings in either project.

| # | Change | Priority |
|---|---|---|
| B1 | **Back up the production database.** mediahub has *none* — its own `DEPLOYMENT.md` lists it as a TODO. Port lottery's manifest + restore-verification pattern and put it on a timer. | **P0** |
| B2 | **Adopt the identity guard.** Port `database_identity.py`; add `app_env`/`expected_database_name` to `config.py`; call it at startup, in Alembic `env.py`, and in scripts. Set `EXPECTED_DATABASE_NAME=mediahub`. Nothing currently stops a stray `DATABASE_URL` hitting the live DB. | **P0** |
| B3 | **Track infrastructure in git.** Add `deploy/` with the systemd unit and nginx site config; today they exist only on the box and only as prose. | P1 |
| B4 | **Fix `AGENTS.md`.** It is a symlink whose target *string* is the document text, so it resolves to nothing. Fold any unique content into `CLAUDE.md`, then `ln -s CLAUDE.md AGENTS.md`. | P1 |
| B5 | **Reconcile DB ownership.** `CLAUDE.md` says the `mediahub` database is owned by role `mediahub`; it is owned by `mediahub_test`. Fix the ownership (needs `REASSIGN OWNED` and a backup first — do after B1) or correct the doc. | P2 |
| B6 | Consider moving the APScheduler poller out of process, as lottery does. Optional; it is what pins mediahub to one uvicorn worker. | P3 |

**Dropped from the earlier draft:** the proposal to move mediahub's secrets to
`~/.config/mediahub/`. Settled decision 5 makes the project-root `.env` the
standard, which mediahub already follows.

---

# Track C — Deploy the feature work

**Revised 2026-08-15.** Codex gated this behind the full 7-day soak. That is too
conservative for a site with one user, and it would leave the VPS on a
non-`main` branch for a week. Run Track C **after one clean fanout run** —
hours after cutover, not days. Keep the release tree for the full seven days
regardless; that retention protects the *topology* rollback, not this deploy.

The two stay separate changes with separate verifications. The point is
attribution, not delay.

### What is actually being deployed

`68680c4` is substantially larger than its name suggests. It is **not** an
auth-gated feature bolted onto an unchanged site:

| Area | Change |
|---|---|
| `rankings_api.py` | +266 — the main public ranking endpoint |
| `game_details_api.py` | +102 |
| `GameDetailPage.tsx` | 204 lines changed; new `AllTicketsPage.tsx` |
| `styles.css` | +1819 / −904 — wholesale visual overhaul |
| `strategies.ts`, `outcomeLadder.ts` | milestone-4 outcome ladder logic |

Every anonymous visitor sees this. By contrast the ticket-tracking feature is
**inert in production**: `user_ticket_entries` foreign-keys to `app_users`, auth
is disabled, and that table has zero rows — no entry can be created. That
asymmetry is the reason not to bundle it into the cutover: it adds no
functionality to production while making a failure impossible to attribute.

`0012` itself is **purely additive** — one table, two indexes, no alteration of
existing objects. Rolling the code back while leaving the table in place is
harmless, so this deploy does not compromise the service-swap rollback.

### Steps

1. VPS switches from `topology-cutover` to `main`.
2. Rehearse `0012` against the development database *(already applied there —
   verify rather than re-apply)*.
3. **Back up production.**
4. Build the frontend; deploy the feature commit; apply `0012`; restart.
5. Verify: public rankings and game detail render correctly, the outcome ladder
   is intact, authentication still reports unavailable, and no ticket-entry route
   is reachable anonymously.

Authentication enablement stays a **separate, later, reversible change** —
Google login testing, privacy/terms/support-contact requirements, and the release
gates in `deploy/AUTHENTICATION_OPERATIONS.md` all belong to that third risk, not
this one.

---

## Rollback

Because Track A applies no schema change, rollback is purely a service swap:
stop the new service; restore the saved release-based unit and its external
`production.env`; confirm `current` still targets the preserved release; start it
on 8766; verify loopback and public HTTPS; restore the previous fanout unit only
if the replacement was activated. The dev API is **not** needed to restore
production.

## Risks

| Risk | Mitigation |
|---|---|
| Cutover restarts the public site | Accepted — sole user, hiccups fine. nginx, port, and DB unchanged |
| Working tree becomes prod; an uncommitted edit ships on restart | Inherent to the model and accepted. Controls: no development on the VPS, the identity guard, `git status` before restart |
| Secrets now live in the deployment tree | Accepted per decision 5. `.env` is gitignored and `0600`; never `git clean -x` the tree; the identity guard fails closed if the file is wrong |
| Deleting the release tree removes rollback | Gated behind a 7-day soak and explicit approval |
| Rotating auth secrets breaks login | Auth is disabled in production, zero rows in all auth tables — blast radius nil today |
| Fanout breaks when one tree serves both targets | Verified compatible with the script's `(root, env_file)` design; still confirm with one manual run (A5) |
| Track B touches mediahub's live DB | B1 (backups) runs first |

## Open items

1. **Confirm Track B is in scope now**, or deferred until lottery is done.
2. Whether `docs/architecture_consistency.md` gets a "superseded by
   `04_MIGRATION_RUNBOOK.md`" header, matching the project's existing convention
   for retired docs.
3. **How stoshai connects to the VPS Postgres** — verify in Phase A1 (see that
   phase); tunnel it if it is not already tunnelled.

Resolved: Track A's code is authored on stoshai per decision 4; these documents
were committed from the VPS as the deliberate final on-box commit (`65b3eef`).
