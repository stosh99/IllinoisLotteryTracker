# Systemd unit inventory

## Current production topology

Install these as system-level units under `/etc/systemd/system/`:

- `illinois-lottery-prod-api.service`
- `illinois-lottery-source-fanout.service`
- `illinois-lottery-source-fanout.timer`

The production API and source fanout run as `stosh99` from
`/home/stosh99/projects/IllinoisLotteryTracker`. There is no development API on
the VPS. See `../SYSTEMD_SETUP.md` for installation and verification.

## Historical or inactive units

The nightly single-database units and shadow-production unit are retained in Git
only as historical and rollback references. Do not install or enable them in the
current topology:

- `illinois-lottery-nightly.service`
- `illinois-lottery-nightly.timer`
- `illinois-lottery-shadow-api.service`

Authentication-maintenance units remain inactive until authentication receives a
separate production-readiness approval. Topology cutover does not authorize their
installation or activation.
