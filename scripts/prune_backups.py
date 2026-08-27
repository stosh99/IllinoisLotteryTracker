#!/usr/bin/env python3
"""Prune database backups to a daily/weekly/monthly retention lifecycle.

A backup is a ``*.dump`` file with a sibling ``*.dump.manifest.json``. The
manifest's ``created_at`` is authoritative; a dump without a readable manifest
is never deleted because its age cannot be established. Deleting a dump also
deletes its manifest and any restore-verification marker.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DAILY = 7
DEFAULT_WEEKLY = 4
DEFAULT_MONTHLY = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-dir", type=Path, required=True, help="explicit directory holding the dumps"
    )
    parser.add_argument("--keep-daily", type=int, default=DEFAULT_DAILY)
    parser.add_argument("--keep-weekly", type=int, default=DEFAULT_WEEKLY)
    parser.add_argument("--keep-monthly", type=int, default=DEFAULT_MONTHLY)
    parser.add_argument(
        "--dry-run", action="store_true", help="report the decision without deleting anything"
    )
    return parser.parse_args()


def _created_at(dump: Path) -> datetime | None:
    manifest = dump.with_suffix(f"{dump.suffix}.manifest.json")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        return datetime.fromisoformat(document["created_at"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _week_bucket(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year:04d}-W{week:02d}"


def select_retained(
    backups: list[tuple[Path, datetime]], daily: int, weekly: int, monthly: int
) -> set[Path]:
    """Keep the newest backup in each of the most recent day, week, and month buckets."""

    ordered = sorted(backups, key=lambda item: item[1], reverse=True)
    retained: set[Path] = set()
    if ordered:
        # The newest backup is always retained, whatever the retention counts say.
        retained.add(ordered[0][0])
    for key, limit in (
        (lambda moment: moment.date().isoformat(), daily),
        (_week_bucket, weekly),
        (lambda moment: moment.strftime("%Y-%m"), monthly),
    ):
        seen: dict[str, Path] = {}
        for path, moment in ordered:
            bucket = key(moment)
            if bucket not in seen:
                seen[bucket] = path
            if len(seen) >= limit:
                break
        retained.update(seen.values())
    return retained


def companions(dump: Path) -> list[Path]:
    return [
        dump.with_suffix(f"{dump.suffix}.manifest.json"),
        dump.with_suffix(f"{dump.suffix}.restore-verified.manifest.json"),
    ]


def main() -> int:
    args = parse_args()
    if not args.backup_dir.is_dir():
        print(f"ERROR: not a directory: {args.backup_dir}", file=sys.stderr)
        return 2
    if min(args.keep_daily, args.keep_weekly, args.keep_monthly) < 1:
        print("ERROR: retention counts must be at least 1", file=sys.stderr)
        return 2

    dated: list[tuple[Path, datetime]] = []
    undatable: list[Path] = []
    for dump in sorted(args.backup_dir.glob("*.dump")):
        moment = _created_at(dump)
        if moment is None:
            undatable.append(dump)
        else:
            dated.append((dump, moment))

    if not dated:
        print(f"no dated backups in {args.backup_dir}; nothing to prune")
        for path in undatable:
            print(f"  kept (no readable manifest): {path.name}")
        return 0

    retained = select_retained(dated, args.keep_daily, args.keep_weekly, args.keep_monthly)
    removed = 0
    freed = 0
    for dump, moment in sorted(dated, key=lambda item: item[1], reverse=True):
        if dump in retained:
            print(f"  keep   {moment.date()} {dump.name}")
            continue
        freed += dump.stat().st_size
        removed += 1
        if args.dry_run:
            print(f"  DELETE {moment.date()} {dump.name} (dry run)")
            continue
        print(f"  DELETE {moment.date()} {dump.name}")
        for companion in companions(dump):
            companion.unlink(missing_ok=True)
        dump.unlink()

    for path in undatable:
        print(f"  keep   (no readable manifest) {path.name}")
    verb = "would remove" if args.dry_run else "removed"
    print(
        f"{verb} {removed} backup(s), {freed / 1_048_576:.1f} MiB; "
        f"{len(retained)} retained in {args.backup_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
