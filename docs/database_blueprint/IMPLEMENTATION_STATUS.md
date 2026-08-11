# Implementation Status

Updated: 2026-08-10

## Database foundation

The provenance and safety remediation is complete. Historical source runs were
backfilled, current-source/catalog views are fail-closed, structural changes and
count reversals are audited, and backup/restore exercises have succeeded. The
known Illinois Lottery Cloudflare challenge and conflicting Galaxy Blast game
number remain safely contained at collection/import boundaries.

Authentication tables and application authentication code were added separately
in migration 0009.

## Analytics model 2.0.0

The active analytics definition is intentionally small:

- ordinary progress uses all tiers at or below $600;
- only tiers above $600 with at least 300 original prizes are adjusted;
- the adjustment uses a fixed 24-day reporting delay;
- eligible tiers without the historical reference use official counts;
- all other high tiers use official counts;
- absence of the optional adjustment never hides a tier or game.

Migration 0010 removes the superseded derived analytics state and seeds model
2.0.0. Tier rows store eligibility, adjustment status, official remaining,
estimated pending, adjusted remaining, reference time, and days used. Analytics
now completes in one pass and a successful current-cutoff run is immediately
eligible for ranking views, subject to source/catalog freshness and integrity.

## Completed validation

- zero-to-head disposable PostgreSQL migration: passed;
- populated revision-0009 restore upgraded through 0010: passed;
- PostgreSQL integration suite: 29 passed;
- focused analytics/API/pipeline suite: 40 passed;
- frontend suite: 25 passed and production build passed;
- historical model-2.0.0 backfill: 91 succeeded, zero failed;
- current analytics: 57 games, 738 tiers, 29 adjusted eligible tiers,
  zero eligible tiers missing the reference, and 57 strategy rows;
- source audit: zero invariant/provenance failures;
- live ranking API: available, model 2.0.0, 442 rows over 52 games;
- nightly status: zero alerts; and
- pre- and post-migration backups: restore-verified.

The in-app browser surface was unavailable in the CLI session. Frontend unit
tests and the production TypeScript/Vite build passed; interactive browser
smoke testing remains the only manual validation item.
