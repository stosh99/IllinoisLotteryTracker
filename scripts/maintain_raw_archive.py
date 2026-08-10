#!/usr/bin/env python3
"""Write a non-destructive raw archive deduplication manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from illinois_lottery_tracker.raw_archive import write_maintenance_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="explicit absolute archive root")
    parser.add_argument("--manifest", type=Path, required=True, help="new JSON manifest path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="seed missing immutable blobs; capture files are never changed or deleted",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = write_maintenance_manifest(
        root=args.root, manifest_path=args.manifest, apply=args.apply
    )
    print(
        f"{document['mode']}: {len(document['duplicate_groups'])} duplicate groups; "
        f"manifest={args.manifest.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
