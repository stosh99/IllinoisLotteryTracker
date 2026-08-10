#!/usr/bin/env python3
"""Inspect, approve, reject, or return an analytics model to experimental status."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_VERSION,
    approve_model_version,
    get_model_version,
    reject_model_version,
)
from illinois_lottery_tracker.analytics_models import AnalyticsBacktestRun
from illinois_lottery_tracker.db import get_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name", default=MODEL_NAME)
    parser.add_argument("--model-version", default=MODEL_VERSION)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--approve", action="store_true")
    action.add_argument("--reject", action="store_true")
    action.add_argument("--experimental", action="store_true")
    parser.add_argument("--backtest-run-id", type=int)
    parser.add_argument("--reason", help="Required auditable reason for a state change.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    changing = args.approve or args.reject or args.experimental
    if changing and not (args.reason or "").strip():
        print("ERROR: --reason is required for an approval-state change", file=sys.stderr)
        return 2
    engine = get_engine()
    with Session(engine, expire_on_commit=False, future=True) as session:
        try:
            model = get_model_version(
                session,
                model_name=args.model_name,
                semantic_version=args.model_version,
            )
            if args.approve:
                model = approve_model_version(
                    session,
                    model_name=args.model_name,
                    semantic_version=args.model_version,
                    reason=args.reason,
                    backtest_run_id=args.backtest_run_id,
                )
            elif args.reject:
                backtest_id = args.backtest_run_id
                if backtest_id is None:
                    backtest_id = session.scalar(
                        select(AnalyticsBacktestRun.id)
                        .where(
                            AnalyticsBacktestRun.model_version_id == model.id,
                            AnalyticsBacktestRun.status == "success",
                            AnalyticsBacktestRun.promotion_status == "failed",
                        )
                        .order_by(
                            AnalyticsBacktestRun.finished_at.desc(),
                            AnalyticsBacktestRun.id.desc(),
                        )
                    )
                model = reject_model_version(
                    session,
                    model_name=args.model_name,
                    semantic_version=args.model_version,
                    reason=args.reason,
                    backtest_run_id=backtest_id,
                )
            elif args.experimental:
                model.approval_status = "experimental"
                model.approval_backtest_run_id = None
                model.approval_decided_at = datetime.now(UTC)
                model.approval_reason = args.reason.strip()
                session.flush()
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:  # noqa: BLE001 - command boundary
            session.rollback()
            print(f"ERROR: model approval operation failed: {exc}", file=sys.stderr)
            return 1

    print(
        f"model={model.model_name} version={model.semantic_version} "
        f"approval_status={model.approval_status} "
        f"backtest_run_id={model.approval_backtest_run_id or '-'} "
        f"mode={'dry_run' if args.dry_run else 'committed'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
