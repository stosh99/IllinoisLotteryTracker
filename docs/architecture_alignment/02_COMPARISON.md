# Architecture comparison — IllinoisLotteryTracker vs mediahub

Date: 2026-08-15. All facts verified against the live VPS, not project docs.
Method and dimension definitions: [01_ANALYSIS_APPROACH.md](01_ANALYSIS_APPROACH.md).

## Executive summary

The two projects are built on the same stack (FastAPI, SQLAlchemy 2.0, Alembic,
Postgres 16, `src/` layout, pyproject, ruff, pytest, uvicorn behind nginx on
loopback) and diverge almost entirely in **deployment topology**, not code.

- **mediahub** runs **one** application on the VPS. It runs *from the git working
  tree*. That tree is production. Development happens on other PCs against a
  separate development database over an SSH tunnel.
- **IllinoisLotteryTracker** runs **two** applications on the VPS. This git
  working tree is the *development* app (port 8765); a copied release tree under
  `~/apps/` is the *production* app (port 8766). Development happens on the
  production box.

That is the inversion the owner did not intend, and it is the root of nearly
every other difference below.

## D1 — Runtime topology

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Apps on the VPS | **Two** | **One** |
| systemd scope | **User** units (`--user`, requires `Linger=yes`, which is set) | **System** unit (`/etc/systemd/system/`) |
| Prod service | `illinois-lottery-prod-api.service` → `127.0.0.1:8766` | `mediahub.service` → `127.0.0.1:8137` |
| Prod working dir | `~/apps/illinois-lottery-tracker/current` | `~/projects/MediaDashboard` |
| Dev service | `illinois-lottery-dev-api.service` → `127.0.0.1:8765`, **running now**, working dir = this repo | none |
| Other units | `illinois-lottery-source-fanout.service` + `.timer` (active); `illinois-lottery-shadow-api.service` (disabled); `illinois-lottery-nightly.*` (legacy, retained) | none |
| Proxy hardening | `--proxy-headers` **not** set on either lottery unit | `--proxy-headers --forwarded-allow-ips 127.0.0.1` set |

The lottery dev service is exposed only on loopback and not proxied by nginx, so
it is not publicly reachable — but it is a second live process holding a second
database connection pool on the production machine.

## D2 — Deploy mechanism

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Model | Release tree + atomic `current` symlink | Deploy in place from the working tree |
| Prod code path | `~/apps/illinois-lottery-tracker/releases/prod-ac6e3b83dbc0` | `~/projects/MediaDashboard` |
| Redeploy | Build a new release dir, own venv, own frontend build, repoint symlink, restart | `git pull` → `pip install -e .` if deps changed → `alembic upgrade head` → `sudo systemctl restart mediahub` |
| Rollback | Repoint symlink to the retained `rollback-before-public-20260812` target | `git checkout` a prior commit and restart |
| **Measured drift** | **Prod is one commit behind this tree: `ac6e3b8` vs `e52d9c1`** | None possible — same tree |

The release model is the more "correct" pattern in the abstract, and it does buy
a genuine atomic rollback. Its cost here is concrete: a full duplicate tree with
its own 466 MB venv and its own frontend build, a second `.git`, and a prod
revision that already silently fell behind the repo the owner works in. For a
single-operator project this is the trade that the mediahub model refuses.

## D3 — Configuration and secrets

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Mechanism | stdlib `dataclass` + `python-dotenv` (`config.py`) | `pydantic-settings` `BaseSettings` (`config.py`) |
| Env location | `~/.config/illinois-lottery-tracker/{development,production,collector}.env`, mode `0600`, injected by `EnvironmentFile=` | `.env` in the project root, mode `0600`, read by pydantic |
| Env selection | Per-systemd-unit `EnvironmentFile` | Implicit — one file, one environment |
| Keys | `APP_ENV`, `EXPECTED_DATABASE_NAME`, `DATABASE_URL`, `RAW_DATA_DIR`, `AUTH_ENABLED` | `DATABASE_URL`, `DEV_DATABASE_URL` (inert reference), `APP_BASE_URL`, Google/Spotify/Anthropic keys, `COOKIE_SECURE`, `SECRET_KEY` |
| Validation | Fail-closed identity checks (see D4) | Type coercion only; no environment guard |

**Defect found — this repo's root `.env` is malformed and unsafe.** It is not
used by the systemd units (they use `EnvironmentFile=`), but `config.py`
auto-loads it for *any script run from the project root*. It currently contains:

- `RAW_DATA_DIR=RAW_DATA_DIR=data/raw` and `APP_ENV=APP_ENV=production` —
  doubled key prefixes, so the parsed values are the literal strings
  `RAW_DATA_DIR=data/raw` and `APP_ENV=production`;
- a **development** `DATABASE_URL` combined with an `APP_ENV` that parses as
  production — an incoherent pairing;
- live `GOOGLE_OIDC_CLIENT_SECRET` and `AUTH_SECRET_KEYS` values in plaintext.

The file is gitignored and was last modified 2026-08-15 17:35. Its secrets should
be rotated regardless of what else is decided, because they were read during this
analysis. mediahub has no equivalent malformed file.

## D4 — Database inventory and identity

Live inventory (`pg_database`), lottery- and mediahub-related only:

| Database | Owner role | Status |
|---|---|---|
| `illinois_lottery_tracker_prod` | `lottery_prod` | Live production |
| `illinois_lottery_tracker_dev` | `lottery_dev` | Live development |
| `lottery_dev` | `lottery_dev` | Legacy, pre-split |
| `lottery_claude_test` | `lottery_dev` | Test scratch |
| `lottery_codex_test` | `lottery_dev` | Test scratch |
| `mediahub` | **`mediahub_test`** | Live production (**owner contradicts mediahub's CLAUDE.md, which claims role `mediahub`**) |
| `mediahub_dev` | `mediahub_dev` | Shared dev snapshot |
| `mediahub_test` | `mediahub_test` | pytest throwaway |

Both projects landed on the same three-database idea (prod / dev / test) with
per-database roles. The difference is enforcement:

- **IllinoisLotteryTracker has a real guard.** `database_identity.py` implements
  fail-closed checks: `APP_ENV=production` *requires* `EXPECTED_DATABASE_NAME`;
  the configured URL's database name must match it; and at connect time
  `SELECT current_database()` must match it too. A process configured for dev
  cannot silently write to prod, and vice versa. There is a dedicated test module
  (`tests/test_database_identity.py`).
- **mediahub has no guard at all.** Nothing prevents a `.env` edit or a stray
  `DATABASE_URL` in the environment from pointing the live app, a migration, or a
  script at the wrong database. Its only protection is that `conftest.py` uses a
  separate `TEST_DATABASE_URL`.

This is the clearest case where the borrowing runs **from lottery to mediahub**.

## D5 — Development workflow

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Where dev happens | **On the production VPS**, in this tree, via the dev API service | On other PCs |
| Dev DB access | Local socket on the same box | **SSH tunnel** to VPS Postgres (`LocalForward 5433`), documented in `docs/REMOTE_DEV.md`, supervised on Windows by `tools/tunnel-supervisor.ps1` + a Scheduled Task |
| Postgres exposure | — | Listens localhost-only; tunnel is the only path in (docs note prod still binds `0.0.0.0` as a pending hardening item) |
| Dev data refresh | Dev is fed live by the fanout importer (D6) | Manual `pg_dump` prod → restore into `mediahub_dev`, then `TRUNCATE sessions` |
| Concurrency safety | — | `conftest.py` takes a Postgres **advisory lock** so two dev PCs can't run pytest against the shared test DB simultaneously |

mediahub's remote-dev story is complete and battle-tested, down to Windows ACL
gotchas. Lottery has no equivalent because it never needed one — development is
on the server.

## D6 — Scheduled and background work

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Mechanism | **External** `systemd` timer (`illinois-lottery-source-fanout.timer`) | **In-process** APScheduler inside the uvicorn worker |
| Job | Collect the source once, publish an immutable content-addressed bundle, then import that same bundle into **both** dev and prod | Poll due feeds every minute |
| Isolation | Runs as a separate `oneshot` process under `xvfb-run` with Playwright/Chrome | Shares the app process; constrains mediahub to a single uvicorn worker |
| Idempotency | SHA-256 content addressing, `--skip-if-today-collected`, DB-state completion guard | Dedupe on `(feed_id, guid)` |
| Observability | Journal lines per environment, e.g. `fanout=development:ok,production:ok` | App logs |
| Health today | Ran 2026-08-15 07:04 EDT, both environments `ok`, analytics run 186 | Running |

Lottery's approach is materially more robust: the scheduler cannot be killed by
an app restart, one importer failing does not block the other, and the collection
evidence is immutable and replayable. mediahub's in-process scheduler is
adequate for feed polling but permanently blocks horizontal scaling, which its
own docs acknowledge.

The one part of lottery's design that exists **only** because of the unintended
topology is the *dual-target fanout*. If there is no dev app on the box, importing
the same bundle into two databases every night is no longer required.

## D7 — Frontend build and serving

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Frontend | React + TypeScript + Vite, with Playwright e2e | Vanilla JS/HTML/CSS, **no build step** |
| Source | `frontend/src` → `frontend/dist` | `src/mediahub/static/` |
| Served by | FastAPI mounts `frontend/dist/assets` and serves an SPA fallback | FastAPI static mount |
| Deploy implication | Prod needs a lockfile-built `dist` per release | Nothing to build |

This is a legitimate difference driven by product needs, not a defect. It does,
however, mean lottery's "deploy" can never be quite as trivial as mediahub's
`git pull` — it will always need a build step before restart.

## D8 — Public edge

Both sit behind the same shared nginx with certbot, alongside three other
virtual hosts (`baseball-unlimited.com`, `budraft2026.com`,
`invoicetimetracker.com`).

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Domain | `illinoislotterytracker.com` | `mymediadashboard.com` |
| Config tracked in git | **Yes** — `deploy/nginx/*.conf`, plus a bootstrap variant and a certbot `reload-nginx` deploy hook | **No** — prose description in `docs/DEPLOYMENT.md` only |
| Redirects | Explicit hand-written HTTP→HTTPS and `www`→apex blocks | certbot-generated `--redirect` |
| Hardening | `server_tokens off`, `client_max_body_size 1m`, explicit proxy timeouts, HSTS/CSP/referrer/permissions headers | Standard certbot block |
| TLS | Valid to 2026-11-10; renewal hook validates and reloads | certbot timer |

Lottery's edge configuration is better and, importantly, **version-controlled**.
mediahub's exists only on the box.

## D9 — Backup and rollback

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| DB backups | `data/backups/*.dump` with a **SHA-256 manifest** and a **disposable-restore verification marker** per dump | **None.** `docs/DEPLOYMENT.md` lists backups as a TODO |
| Backup tooling | `tests/test_backup_database.py` exists, so it is a tested code path | — |
| App rollback | Retained `rollback-before-public-20260812` release, preserved shadow service and legacy units | `git checkout` + restart |
| Raw data preservation | Canonical archive at `~/illinois-lottery-data/source-captures` plus the original `data/raw` | n/a |

Lottery is far ahead here, and this is the second clear lottery→mediahub
borrowing. "Restore-verified" backups are a genuinely strong practice; mediahub
currently has no recovery path for its production database at all.

## D10 — Tests

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| Runner | pytest, configured in pyproject | pytest, configured in pyproject |
| Volume | 36 test modules + `analytics/`, `api/`, `auth/`, `postgres/` subdirs; 566 passing with 31 Postgres tests skipped | 36 test modules |
| Live-DB protection | `EXPECTED_DATABASE_NAME` identity guard + separate scratch DBs | `mediahub_test` DB + `TEST_DATABASE_URL` + session advisory lock |
| Frontend tests | 76 unit/component tests, TypeScript build, 20 Playwright tests (desktop + 390 px) | none (no build step, no JS tests) |
| Extra | `pip-audit` in dev deps | — |

Comparable maturity. Lottery has the stronger safety guarantee; mediahub has the
better multi-machine concurrency story.

## D11 — Repository and agent conventions

| | IllinoisLotteryTracker | mediahub |
|---|---|---|
| `CLAUDE.md` | **Absent** | Present, 11.6 KB, genuinely load-bearing (architecture, DB map, gotchas, house UI patterns) |
| `AGENTS.md` | Absent | Present but **broken** — it is a symlink whose *target string is the document text itself*, so it resolves to nothing. The global convention is `ln -s CLAUDE.md AGENTS.md` |
| Docs layout | Numbered blueprint directories (`database_blueprint/`, `authentication_blueprint/`, `environment_separation/`, `product_planning/`) each with `README` + `IMPLEMENTATION_STATUS` | Flat `docs/` with `DEPLOYMENT`, `REMOTE_DEV`, `BACKLOG` + specs |
| Superseded docs | Marked in place (`project_handoff_current_state.md` carries a "Superseded" header) | `BACKLOG.md` entries marked `BUILT ✅ <date>` |
| Infra in git | `deploy/` with systemd units, nginx confs, certbot hook | Not tracked |
| Dep files | `pyproject.toml` **and** `requirements.txt` | `pyproject.toml` **and** `requirements.txt` |

Lottery's documentation is more rigorous and its infrastructure is tracked;
mediahub's is more navigable and it actually has the canonical agent guide that
the global convention requires. Lottery having **no CLAUDE.md** is a real gap —
a fresh agent session on this repo starts with no project-specific grounding,
which is exactly how a second production tree gets built without anyone noticing.

## D12 — Footprint hygiene

| Item | Size / state |
|---|---|
| `~/projects/IllinoisLotteryTracker` | 1.5 GB |
| `~/apps/.../releases/prod-ac6e3b83dbc0` | 466 MB (own venv + own `.git` + built frontend) |
| 4 × `shadow-*` release trees | 3.8 MB each, all superseded |
| `~/projects/MediaDashboard` | 232 MB |
| Legacy DBs | `lottery_dev`, `lottery_claude_test`, `lottery_codex_test` |
| Legacy units | `illinois-lottery-nightly.{service,timer}`, `illinois-lottery-shadow-api.service`, copies under `~/.config/illinois-lottery-tracker/rollback/` |

Lottery carries roughly half a gigabyte of duplicate application tree plus four
stale shadow releases, three surplus databases, and three retained-but-dead
systemd units. mediahub carries none of this because it never forked a second
tree.

## Where each project is better

**IllinoisLotteryTracker does better — adopt into mediahub:**

1. Fail-closed **database identity guard** (`EXPECTED_DATABASE_NAME` + `APP_ENV`).
2. **Verified backups** with SHA-256 manifests and restore markers.
3. **Infrastructure tracked in git** (`deploy/` — systemd, nginx, certbot hook).
4. **External systemd timer** for scheduled work instead of an in-process
   scheduler bolted to the web worker.
5. **Immutable, content-addressed source evidence** with SHA-256 idempotency.
6. Hardened nginx (security headers, explicit timeouts, body-size cap).

**mediahub does better — adopt into IllinoisLotteryTracker:**

1. **One application per box; the working tree is production.** No release tree,
   no symlink, no drift.
2. **No development application on the production VPS.** Dev is a *database*, not
   a second running app.
3. **Documented remote-dev workflow** over an SSH tunnel, including supervision.
4. **System-level systemd unit** with `--proxy-headers`.
5. **A canonical `CLAUDE.md`** that a fresh agent session actually reads.
6. Trivially simple redeploy that one person can execute from memory.

## The single sentence version

Both projects want the same architecture and each has built half of it:
mediahub has the right **topology** with weak **safety rails**, and
IllinoisLotteryTracker has strong **safety rails** wrapped around the wrong
**topology**.
