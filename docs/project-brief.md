# IllinoisLotteryTracker

Goal: make public Illinois Lottery instant-ticket prize availability easier to
compare while retaining auditable official history.

## Implemented foundation

- nightly official-source and retail-catalog collection;
- immutable raw and normalized snapshot history;
- PostgreSQL constraints, current views, reconciliation, and audits;
- backup and verified-restore tooling;
- versioned tier, EV, strategy, and ranking analytics;
- read-only ranking API and React comparison frontend; and
- authentication work in a separate implementation path.

## High-prize rule

Illinois prizes above $600 can be reported later because they require
claim-center processing. Model 2.0.0 applies one fixed 24-day correction only
to individual tiers with at least 300 original prizes. Smaller tiers and tiers
without a usable historical reference use their official count and remain in
the product.

## Product principles

- Preserve official source evidence and never overwrite history.
- Label EV and probabilities as estimates.
- Never equate unclaimed prizes with unsold tickets.
- Never present an older analytics cutoff as current.
- Keep optional estimation gaps distinct from source-integrity failures.
- Say “compare games using public prize-availability data,” not “find winning
  tickets.”

## Next product work

Connect and validate the live frontend, deploy a minimal production surface,
complete authentication, and add personal ticket-result tracking behind
authenticated accounts.
