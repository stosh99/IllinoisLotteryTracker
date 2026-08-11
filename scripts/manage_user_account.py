#!/usr/bin/env python3
"""Inspect or apply guarded operator controls to one local user UUID."""

from __future__ import annotations

import argparse
import json
import uuid

from illinois_lottery_tracker.auth.user_management import (
    UserAccountManager,
    UserOperationError,
)
from illinois_lottery_tracker.db import get_session


def canonical_uuid(value: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a canonical UUID") from exc
    if str(parsed) != value:
        raise argparse.ArgumentTypeError("must be a canonical UUID")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--show-user-id", type=canonical_uuid)
    actions.add_argument("--suspend-user-id", type=canonical_uuid)
    actions.add_argument("--reactivate-user-id", type=canonical_uuid)
    actions.add_argument("--revoke-sessions-user-id", type=canonical_uuid)
    actions.add_argument("--delete-user-id", type=canonical_uuid)
    parser.add_argument("--confirm-delete-user-id", type=canonical_uuid)
    parser.add_argument("--reason-code")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.show_user_id is not None:
        if args.reason_code or args.confirm_delete_user_id or args.apply:
            parser.error("show is read-only and accepts no mutation options")
        return args
    if not args.reason_code:
        parser.error("mutations require --reason-code")
    if args.delete_user_id is not None:
        if args.confirm_delete_user_id != args.delete_user_id:
            parser.error("deletion requires the same UUID in --confirm-delete-user-id")
    elif args.confirm_delete_user_id is not None:
        parser.error("--confirm-delete-user-id is valid only with deletion")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manager = UserAccountManager(get_session)
    try:
        if args.show_user_id is not None:
            result = manager.show(args.show_user_id)
        else:
            options = (
                ("suspend", args.suspend_user_id),
                ("reactivate", args.reactivate_user_id),
                ("revoke_sessions", args.revoke_sessions_user_id),
                ("delete", args.delete_user_id),
            )
            action, user_id = next((name, value) for name, value in options if value is not None)
            result = manager.mutate(
                action, user_id, args.reason_code, apply=args.apply
            )
    except UserOperationError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result.document(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
