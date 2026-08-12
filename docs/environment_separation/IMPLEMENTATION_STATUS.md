# Shadow-production implementation status

Status: **implemented and verified on 2026-08-11; public promotion prohibited**.

## Outcome

Development and production now have independent PostgreSQL databases and credentials,
independent API processes, and independent importer subprocesses. One database-free
collector publishes an immutable source bundle and fans that exact evidence out to
both environments. Shadow production binds only to `127.0.0.1:8766`.
Authentication remains explicitly disabled and all five authentication/user tables
contain zero rows.

The split timer is active. The legacy timer is disabled but its installed files,
private rollback copies, original database, original raw archive, and verified backup
remain intact.

## Verified state

| Check | Result |
| --- | --- |
| Development identity | `illinois_lottery_tracker_dev` as `lottery_dev` |
| Production identity | `illinois_lottery_tracker_prod` as `lottery_prod` |
| Migration revision | `0011_defer_auth_event_links` in both |
| Database comparison after live import | all 20 table counts identical |
| Authentication data | 0 rows in every auth/user table |
| Source audit | zero failures |
| Saved-bundle fan-out | passed in both environments |
| Fresh live bundle | bundle `0bd457a4…`; 3 catalog pages; passed in both |
| Live run IDs | source 101, catalog 102, analytics 184 in both |
| API content | ranking/status/mode content identical; timestamps generated per request |
| API binding | development 8765 and shadow 8766 on loopback only |
| Frontend | production build served by shadow API |
| Authentication endpoint | reports authentication unavailable and unauthenticated |
| Installed fan-out unit | successful manual idempotence run against newest bundle |
| Lint and tests | clean at implementation handoff |

The forced browser-first collection encountered a Cloudflare “Just a moment” page and
failed closed before manifest publication. The normal HTTP-first collection with the
same persistent-Chrome fallback then succeeded and produced the verified live bundle.
This confirms challenge HTML cannot enter either database while retaining the working
collection route.

## Preservation and recovery artifacts

The original archive remains at
`/home/stosh99/projects/IllinoisLotteryTracker/data/raw`. It was copied to
`/home/stosh99/illinois-lottery-data/source-captures`; checksum comparison reported no
differences, with 11,616 files and 936,108,165 bytes on each side at copy time.

Restore-verified backups:

- `data/backups/pre_environment_split_20260811.dump`
- `data/backups/post_environment_split_dev_20260811.dump`
- `data/backups/post_environment_split_prod_20260811.dump`

Each has a SHA-256 manifest and a disposable-restore verification marker. Exact legacy
unit copies are under
`/home/stosh99/.config/illinois-lottery-tracker/rollback/`.

## Release qualification

The shadow release is an immutable staged copy under
`/home/stosh99/apps/illinois-lottery-tracker/releases`, selected by the `current`
symlink. `SHADOW_BUILD_INFO.json` records base commit
`cf41343b4c74fcbfe5ff7145c6bd6fa008570c07` plus a full source-tree digest.

The work remains intentionally uncommitted at the user's request. Therefore the
release is marked `public_promotion_eligible=false`. Before any public deployment,
review and commit the implementation, stage a Git-pinned release, independently
review reverse-proxy/TLS configuration, and make a separate decision about enabling
authentication. None of those public/auth changes are part of this milestone.

## Operational invariant

Never restore development wholesale into production again once production may contain
user data. Future source evidence flows through bundles only. A failure in one
importer must remain visible but must not prevent the other importer from being
attempted.

See [SHADOW_PRODUCTION_SPEC.md](SHADOW_PRODUCTION_SPEC.md) for the architecture and
[deploy/SYSTEMD_SETUP.md](../../deploy/SYSTEMD_SETUP.md) for commands and rollback.
