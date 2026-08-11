#!/usr/bin/env python3
"""Plan or apply bounded authentication retention maintenance."""

from __future__ import annotations

import argparse
import json

from illinois_lottery_tracker.auth.maintenance import AuthenticationMaintenance
from illinois_lottery_tracker.db import get_session


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report eligible row counts only")
    mode.add_argument("--apply", action="store_true", help="apply lifecycle and retention changes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    counts = AuthenticationMaintenance(get_session).run(apply=args.apply)
    print(json.dumps(counts.document(mode="apply" if args.apply else "dry-run"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
