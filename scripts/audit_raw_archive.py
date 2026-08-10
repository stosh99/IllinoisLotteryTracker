#!/usr/bin/env python3
"""Report raw archive file, byte, hash, and projected deduplication counts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.paths import raw_data_dir
from illinois_lottery_tracker.raw_archive import audit_raw_archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="raw archive root (defaults to config)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = audit_raw_archive(args.root or raw_data_dir(get_settings()))
    if args.json:
        print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"Raw archive: {audit.root}")
        print(f"Files: {audit.files}; bytes: {audit.bytes}; unique hashes: {audit.unique_hashes}")
        print(f"Projected deduplication savings: {audit.duplicate_bytes} bytes")
        for category, counts in sorted(audit.categories.items()):
            print(
                f"  {category}: files={counts.files} bytes={counts.bytes} "
                f"hashes={counts.unique_hashes} duplicate_bytes={counts.duplicate_bytes}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
