# Implementation Work Packets

## Completed database foundation

Source provenance, completeness gates, catalog reconciliation, current views,
backup/restore verification, invariant audits, and authentication schema are
implemented through migration 0009.

## Completed simplified high-prize analytics

Migration `0010_simplified_high_prize_adjustment` and model `2.0.0` implement:

- ordinary reference tiers through $600;
- high-prize eligibility above $600 with at least 300 original prizes;
- one fixed 24-day reporting-delay adjustment;
- official-count fallback without suppressing games;
- one-pass tier, game, strategy, and ranking computation;
- direct successful-run availability with source/catalog freshness checks;
- explicit stored adjustment provenance; and
- removal of the superseded derived tables, fields, commands, and runtime code.

## Required deployment sequence

1. Take a database backup.
2. Run Alembic through revision 0010.
3. Backfill analytics model 2.0.0 over desired source cutoffs.
4. Run source/invariant audits.
5. Verify ranking status and API output.
6. Run frontend tests and browser validation.
7. Take and restore-verify a post-migration backup.

## Future work

Future changes to the fixed 24-day or 300-prize constants require an explicit
product decision, a new semantic model version, migration/test updates, and a
recompute of derived analytics. They must not be fitted silently during nightly
operation.
