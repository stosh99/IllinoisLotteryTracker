# Architecture alignment — recommendations

Date: 2026-08-15. Proposal only; nothing here has been executed.
Evidence: [02_COMPARISON.md](02_COMPARISON.md). Method: [01_ANALYSIS_APPROACH.md](01_ANALYSIS_APPROACH.md).

## The owner's stated objective (verbatim intent)

> "Codex was supposed to turn **this project into prod with a dev and prod db**."
>
> Make the two projects architecturally similar, "**without a dev app version
> for either on this prod vps**," using "**primarily mediahub, but
> lotterytracker had some elements you liked better**."

That is the whole specification. Everything below serves it.

## Decisions settled by the owner (2026-08-15)

1. **This project directory becomes production.** Not a release tree elsewhere.
2. **Both databases stay** — `illinois_lottery_tracker_prod` and
   `illinois_lottery_tracker_dev`. A dev *database* was always intended; a dev
   *app* was not.
3. **No dev app on this VPS for either project.** mediahub already complies
   (one service, no dev app), so this constrains lottery only.
4. **No development happens on the production server.** The owner develops on
   other machines. The VPS runs production only, even though it currently also
   hosts their desktop session and PyCharm — that workflow moves off-box.
5. mediahub is the primary model; lottery's better elements are borrowed back
   into it rather than discarded.
6. Rollback retention after the cutover: **one week of clean nightly runs**
   before the old release tree is deleted (provisional).
7. **System-level systemd for everything**, matching `mediahub.service`. The
   owner prefers the system way: one command set across both projects, the
   conventional choice for a public daemon, and no dependence on a lingering
   user session for a user who will no longer be logged in.
8. **Downtime is acceptable.** The owner is currently the only user of both
   sites and they "can hiccup." No zero-downtime choreography is required —
   prefer the simple, verifiable sequence over the clever one.

Consequence that follows directly: `~/projects/IllinoisLotteryTracker` on the
VPS becomes a **production deployment checkout**, not a workspace. Nobody edits
it. It receives `git pull` and nothing else — exactly what
`~/projects/MediaDashboard` already is.

Prerequisite verified: the repo has a GitHub remote
(`origin` → `git@github.com:stosh99/IllinoisLotteryTracker.git`) and `main`
tracks `origin/main`, so the pull-based deploy works.

## The target architecture (both projects)

> **One application per project on the VPS, and it is production. It runs from
> the git working tree. Development is a database, not a second running app.
> Secrets never live inside the working tree on the production box.**

Concretely, for each project:

| Aspect | Standard |
|---|---|
| Apps running on the VPS | Exactly one, production |
| Prod code location | The git working tree in `~/projects/<Project>` |
| Prod config | `~/.config/<app>/production.env`, mode `0600`, injected via systemd `EnvironmentFile=` |
| Working-tree `.env` | **Must not exist on the VPS.** It is the *dev-PC* convention only |
| Databases | `<app>` (prod), `<app>_dev` (remote dev), `<app>_test` (pytest throwaway), each with its own role |
| Wrong-DB protection | Fail-closed identity guard: `APP_ENV=production` requires `EXPECTED_DATABASE_NAME`, checked against both the URL and `SELECT current_database()` |
| Development | Off-box, against `<app>_dev` over an SSH tunnel |
| Scheduled work | External systemd timer, not an in-process scheduler |
| Service scope | System-level systemd unit, `User=stosh99`, uvicorn with `--proxy-headers --forwarded-allow-ips 127.0.0.1` |
| Edge | Shared nginx + certbot, config tracked in the repo under `deploy/nginx/` |
| Backups | `pg_dump` with a SHA-256 manifest and a restore-verification marker |
| Agent guide | `CLAUDE.md` canonical, `AGENTS.md` a real symlink to it |
| Redeploy | `git pull` → build frontend if present → `pip install -e .` if deps changed → `alembic upgrade head` → restart |

This keeps mediahub's topology and lottery's safety rails, which is the
combination each project is currently missing half of.

## Deliberate deviations from strict mediahub parity

Three lottery behaviors are **kept**, because they are better and are not what
caused the problem:

1. **Env files in `~/.config/<app>/`, not the working tree.** This is stricter
   than mediahub. It is what makes "the working tree is production" safe — the
   tree holds no secrets, so an editor, an agent, a `git clean`, or a stray
   `pytest` cannot read or clobber production credentials. mediahub should move
   to this too.
2. **The external fanout timer stays.** It is not the problem. The dev *app* was
   the problem. The fanout collects once, publishes an immutable SHA-256 bundle,
   and imports it into two *databases* — which needs no second app. It is more
   robust than mediahub's in-process poller and gives the dev database fresh real
   data daily without ever touching production.
3. **A frontend build step exists.** Lottery's redeploy will always have one more
   step than mediahub's. That is a product requirement, not a divergence to fix.

## Part A — Changes to IllinoisLotteryTracker

Ordered by dependency. **A1–A3 are the actual fix**; the rest is cleanup and
parity.

### A1 — Make this working tree production, as a system unit (P0)

**Merged with the old A6.** Since downtime is acceptable and system-level is the
chosen standard, do this as one cutover rather than repointing the user unit now
and converting it later — one change, one verification.

Create `/etc/systemd/system/illinois-lottery-prod-api.service` with
`User=stosh99`, `WorkingDirectory=/home/stosh99/projects/IllinoisLotteryTracker`,
`EnvironmentFile=/home/stosh99/.config/illinois-lottery-tracker/production.env`,
uvicorn on port 8766 with `--proxy-headers --forwarded-allow-ips 127.0.0.1`
(currently missing). Then `systemctl --user disable --now` the old user unit so
the two can never contend for port 8766. nginx is unchanged. Update the tracked
copy in `deploy/systemd/`.

- Requires: this tree's `.venv` installed with prod deps, `frontend/dist` built
  from the lockfile, and `alembic current` matching prod's revision
  (`0011_defer_auth_event_links`).
- **Closes the measured drift** — prod stops running `ac6e3b8` while the owner
  works on `e52d9c1`.
- Rollback: repoint the unit back to `current` and restart. The release tree is
  not deleted at this step.

### A2 — Remove the development application from the VPS (P0)

`systemctl --user disable --now illinois-lottery-dev-api.service`, then delete
the unit and `deploy/systemd/illinois-lottery-dev-api.service`.

The `illinois_lottery_tracker_dev` **database stays** — it becomes the remote-dev
database, exactly like `mediahub_dev`.

### A3 — Delete the working-tree `.env` on the VPS, and rotate its secrets (P0)

The root `.env` is malformed (`APP_ENV=APP_ENV=production`,
`RAW_DATA_DIR=RAW_DATA_DIR=data/raw`), pairs a **dev** database URL with a
**production** `APP_ENV`, and holds live `GOOGLE_OIDC_CLIENT_SECRET` and
`AUTH_SECRET_KEYS` in plaintext.

- Delete it from the VPS. Prod reads `~/.config/illinois-lottery-tracker/production.env`.
- **Rotate the Google OIDC client secret and `AUTH_SECRET_KEYS`.** They were read
  during this analysis and are therefore in a session transcript. Rotate even
  though authentication is disabled and the file is gitignored.
- Keep `.env.example` as the dev-PC template.

### A4 — Retire the release tree and shadow artifacts (P1)

After A1 has run stably for an agreed period:

- Remove `~/apps/illinois-lottery-tracker/releases/prod-ac6e3b83dbc0` (466 MB)
  and the four `shadow-*` trees.
- Remove `illinois-lottery-shadow-api.service` and the legacy
  `illinois-lottery-nightly.{service,timer}` (plus the `rollback/` copies) once
  the fanout timer is confirmed as the only scheduler.
- Keep `data/backups/*` and `~/illinois-lottery-data/source-captures` — those are
  evidence and recovery assets, not duplication.
- **Do not do this before A1 is proven.** The release tree is the rollback.

### A5 — Repoint the fanout at the single tree (P1)

In `illinois-lottery-source-fanout.service`, set `--production-root` to
`~/projects/IllinoisLotteryTracker` (same as `--development-root`).

Verified as safe: `fanout_source_bundle.py` models each target as an independent
`(project_root, env_file)` pair and runs `import_source_bundle.py` with that
env file's values injected into the child process, so one tree serving both
targets works. Because `config.py` uses `load_dotenv(..., override=False)`, the
injected values win — and after A3 there is no working-tree `.env` to compete
at all.

### A6 — Move the fanout timer to system level too (P2)

The API service is handled in A1. The fanout is moved separately because it runs
Playwright/Chrome under `xvfb-run --auto-servernum` with a persistent browser
profile at `~/illinois-lottery-data/browser-profile/collector`. It should work
unchanged as a system unit with `User=stosh99` — `xvfb-run` starts its own X
server and the unit already unsets `WAYLAND_DISPLAY` and forces
`XDG_SESSION_TYPE=x11` — but **trigger one manual run and confirm a real
collection before trusting the timer**. `XDG_RUNTIME_DIR` is the likely snag if
anything misbehaves.

Once both have moved, `loginctl enable-linger` is no longer load-bearing for
either site.

### A7 — Add `CLAUDE.md` and an `AGENTS.md` symlink (P1)

This repo has neither. A fresh agent session starts with no grounding on the
topology, the identity guard, the fanout, the auth-disabled boundary, or the
blueprint doc layout — which is how a second production tree got built without
anyone noticing. Model it on mediahub's, and create `AGENTS.md` as a **real**
symlink: `ln -s CLAUDE.md AGENTS.md`.

### A8 — Stand up off-box development (P0)

Promoted to P0 by the owner's decision: this is no longer optional parity, it is
the replacement for the capability A2 removes. **A2 must not ship before A8 is
usable**, or there is nowhere to develop.

**This is smaller than it looks.** The dev machine already exists and the hard
parts are already solved on it: mediahub's `docs/REMOTE_DEV.md` documents a
Windows PC (`C:\Users\shart\PycharmProjects\mediadashboard`) with a working SSH
tunnel to this VPS's Postgres, a supervised reconnect loop, and the OpenSSH ACL
workarounds. Lottery reuses that same tunnel — one more `LocalForward` is not
even required, since the tunnel reaches the whole Postgres instance.

Port `docs/REMOTE_DEV.md` from mediahub and adapt it. What a dev machine needs:

| Piece | Detail |
|---|---|
| Clone | `git clone git@github.com:stosh99/IllinoisLotteryTracker.git` |
| Python | venv + `pip install -e ".[dev]"` |
| **Node** | `npm ci` + Vite — lottery has a frontend build mediahub does not. Playwright browsers too, for e2e |
| SSH tunnel | `LocalForward 5433 127.0.0.1:5432` to the VPS, keepalives, `ExitOnForwardFailure yes` |
| Dev `.env` | `DATABASE_URL` → `illinois_lottery_tracker_dev` via `localhost:5433`, plus `APP_ENV=development` and `EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev` |
| Run | `uvicorn illinois_lottery_tracker.api:app --port 8765` locally |
| Windows | mediahub's `tools/tunnel-supervisor.ps1` + Scheduled Task, and its `.ssh` ACL gotchas, port over unchanged |

**The identity guard makes this materially safer than mediahub's version.** A dev
machine that fat-fingers its `DATABASE_URL` toward prod gets a hard
`DatabaseIdentityError` instead of a silent write.

### A8b — Create a real test database (P1)

Off-box development means pytest runs over the tunnel, so lottery needs
mediahub's arrangement: a dedicated `illinois_lottery_tracker_test` database with
its own role, plus the **session advisory lock** from mediahub's `conftest.py` so
two dev machines cannot run the suite concurrently against one shared test DB.

Today the 31 Postgres-environment tests simply skip when no database is present,
and the scratch DBs (`lottery_claude_test`, `lottery_codex_test`) are ad hoc.
Fold them into one real test DB, then drop the surplus:
`lottery_dev`, `lottery_claude_test`, `lottery_codex_test`.

### A9 — Fold `docs/architecture_alignment/` into the blueprint convention (P3)

These three files should get an `IMPLEMENTATION_STATUS.md` like the other
blueprint directories once execution begins, and
`docs/environment_separation/IMPLEMENTATION_STATUS.md` should be marked
superseded — it documents the architecture being replaced.

## Part B — Changes to mediahub

### B1 — Adopt the database identity guard (P0)

Port `database_identity.py` and add `app_env` + `expected_database_name` to
`config.py`. Call `verify_engine_identity` at startup, in Alembic's `env.py`, and
in any script that opens a session. Set `APP_ENV=production` and
`EXPECTED_DATABASE_NAME=mediahub` in the prod env.

mediahub currently has **nothing** preventing a stray `DATABASE_URL` from
pointing the live app or a migration at the wrong database. This is the single
highest-value borrowing in either direction.

### B2 — Adopt verified backups (P0)

mediahub's production database has **no backup at all** — `docs/DEPLOYMENT.md`
lists it as a TODO. Port lottery's `scripts/backup_database.py` pattern
(SHA-256 manifest + disposable-restore verification marker) and put it on a
timer. This is the largest outright risk found anywhere in this analysis.

### B3 — Move prod secrets out of the working tree (P1)

Move mediahub's prod `.env` to `~/.config/mediahub/production.env` (mode `0600`)
and load it via `EnvironmentFile=` in `mediahub.service`. pydantic-settings
reads the process environment, so no code change is needed. Keep `.env` as the
dev-PC convention.

This also cleans up a real hazard: mediahub's tree contains
`googlePassword.odt` and its `.gitignore` carries defensive `*password*` rules
precisely because secrets have leaked into that tree before.

### B4 — Track infrastructure config in git (P1)

Create `deploy/` in mediahub with the systemd unit and the nginx site config, as
lottery does. Today mediahub's nginx configuration exists only on the box and
only in prose.

### B5 — Fix the broken `AGENTS.md` symlink (P1)

`AGENTS.md` is a symlink whose *target string is the document text*, so it
resolves to nothing. Replace with `ln -s CLAUDE.md AGENTS.md` and fold any
unique content from the current text into `CLAUDE.md` first.

### B6 — Correct `CLAUDE.md`'s database ownership claim (P2)

It says the `mediahub` production database is owned by role `mediahub`. It is
owned by `mediahub_test`. Either correct the doc or fix the ownership — the
latter is probably right, since a throwaway test role owning the production
database is not intended. `REASSIGN OWNED` needs care and a backup first (B2).

### B7 — Consider moving the poller out of process (P3)

Optional, and lower value than B1–B4. APScheduler in the uvicorn worker
permanently limits mediahub to one worker. Lottery's external-timer pattern is
the model if that ever becomes a constraint. Not urgent.

## Sequencing

**Phase 0 — build the replacement first:** A8 (+ A8b). Off-box development must
work on at least one machine *before* A2 removes the on-box dev app. Verify by
running the full suite and the dev API from that machine over the tunnel.

**Phase 1 — stop the bleeding (lottery):** A1 → A2 → A3. After this the intended
architecture is live, drift is closed, and the malformed secrets file is gone.
The release tree is retained as rollback.

**Phase 2 — close mediahub's safety gaps:** B2 → B1 → B3. Backups first, because
B1 and B6 both want a backup to exist before they run.

**Phase 3 — parity and cleanup:** A5 → A7 → A4 → B4 → B5 → A6 → A8b → B6.

**Phase 4 — optional:** A9, B7.

Phases 1 and 2 are independent and can run in either order or in parallel.

## Risks

| Risk | Mitigation |
|---|---|
| A1 restarts the public site | Accepted — the owner is the only user and brief hiccups are fine. nginx block, port, and env file are unchanged; verify with the same checks used at promotion (homepage, detail, history, SPA routes, `/api` comparison) |
| Working tree becomes prod → an uncommitted edit ships on the next restart | This is inherent to the mediahub model and accepted; the identity guard, `git status` before restart, and off-box development are the controls |
| Retiring the release tree removes the rollback | A4 is gated behind a proven A1; back up before deleting |
| Rotating auth secrets (A3) breaks login | Authentication is disabled in production (`AUTH_ENABLED=false`, zero rows in all auth tables), so the blast radius is nil today |
| B1/B6 touch mediahub's live DB | B2 (backups) runs first |
| Fanout breaks when both roots are one tree | A5 verified against the script's structure; still confirm with one real timed run before trusting it |

## Open decisions for the owner

Most of the first draft's questions were already answered by the owner's
original brief — see "The owner's stated objective" and "Decisions settled".
What genuinely remains:

1. **Dev database feed — confirm the default.** The brief settles that the dev
   database *exists*; it does not say how it gets data. The nightly fanout
   already imports one immutable bundle into both databases and is tested and
   healthy. Keeping it does not violate "no dev app on the prod vps" — it is a
   data feed writing to a database, with no application involved. The
   alternative (mediahub's on-demand `pg_dump` refresh) makes the prod box's
   nightly job do exactly one thing, at the cost of dev data going stale.
   *Recommended: keep the fanout. Proceeding on that basis unless told otherwise.*

## Note for future agent sessions

After this cutover, agent and IDE sessions must run **on a dev machine against
the cloned repo**, not on the VPS. A session opened in
`~/projects/IllinoisLotteryTracker` on the production box is, by definition,
developing on production. The only operations that belong on the VPS are
deploy (`git pull`, build, migrate, restart) and operational inspection.

This should be stated explicitly at the top of the new `CLAUDE.md` (A7).
