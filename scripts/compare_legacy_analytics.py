#!/usr/bin/env python3
"""Write the one-time legacy/new metric transition comparison."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from illinois_lottery_tracker.db import get_engine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        print(f"ERROR: comparison output already exists: {output}", file=sys.stderr)
        return 2
    with Session(get_engine()) as session:
        rows = list(
            session.execute(
                text(
                    """
                    SELECT source.id source_run_id, source.source_observed_at,
                           model.semantic_version, game.game_number, game.name,
                           snapshot.estimated_tickets_remaining legacy_remaining_tickets,
                           gm.estimated_remaining_tickets new_remaining_tickets,
                           snapshot.estimated_ev legacy_ev_full,
                           strategy.estimated_ev_full new_ev_full,
                           snapshot.estimated_ev_excluding_top_prize legacy_ev_ex_top,
                           strategy.estimated_ev_ex_top new_ev_ex_top,
                           snapshot.estimated_payout_ratio legacy_payout_full,
                           strategy.estimated_payout_ratio_full new_payout_full,
                           gm.data_status, strategy.metric_statuses
                    FROM current_complete_scrape_run_v source
                    JOIN analytics_runs run ON run.as_of_scrape_run_id=source.id
                      AND run.status='success' AND run.publishable
                    JOIN analytics_model_versions model ON model.id=run.model_version_id
                      AND model.model_name='core_ticket_model'
                      AND model.semantic_version=:version
                    JOIN analytics_game_metrics gm ON gm.analytics_run_id=run.id
                    JOIN games game ON game.id=gm.game_id
                    JOIN game_snapshots snapshot ON snapshot.id=gm.game_snapshot_id
                    JOIN analytics_strategy_metrics strategy
                      ON strategy.analytics_run_id=run.id AND strategy.game_id=gm.game_id
                    ORDER BY game.game_number
                    """
                ),
                {"version": args.model_version},
            ).mappings()
        )
    if not rows:
        print("ERROR: no matching current source/model comparison rows", file=sys.stderr)
        return 1
    generated = datetime.now(UTC).replace(microsecond=0)
    lines = [
        "# Legacy/New Analytics Comparison",
        "",
        f"- Generated at: `{generated.isoformat()}`",
        f"- Model: `core_ticket_model {rows[0]['semantic_version']}`",
        f"- Source run: `{rows[0]['source_run_id']}`",
        f"- Source observed at: `{rows[0]['source_observed_at'].isoformat()}`",
        f"- Current games compared: `{len(rows)}`",
        "",
        "This is the required one-time transition audit. The legacy estimate uses all",
        "reported remaining winning tickets times published overall odds as its",
        "denominator. The replacement uses the non-circular <=$500 progress model,",
        "leave-one-tier-out regular references, and cutoff-versioned high-tier status.",
        "The columns are therefore expected to differ and must not be overwritten.",
        "",
        "## Coverage and Difference Summary",
        "",
        "| Metric | Paired games | Median new - legacy | Mean absolute difference |",
        "|---|---:|---:|---:|",
    ]
    pairs = (
        ("Estimated remaining tickets", "legacy_remaining_tickets", "new_remaining_tickets"),
        ("EV full", "legacy_ev_full", "new_ev_full"),
        ("EV excluding top", "legacy_ev_ex_top", "new_ev_ex_top"),
        ("Payout ratio full", "legacy_payout_full", "new_payout_full"),
    )
    for label, legacy_key, new_key in pairs:
        differences = [
            Decimal(row[new_key]) - Decimal(row[legacy_key])
            for row in rows
            if row[legacy_key] is not None and row[new_key] is not None
        ]
        lines.append(
            f"| {label} | {len(differences)} | {_format(_median(differences))} | "
            f"{_format(_mean([abs(value) for value in differences]))} |"
        )
    lines.extend(
        [
            "",
            "## Largest Full-EV Differences",
            "",
            "| Game | Legacy EV | New EV | New - legacy | Data status |",
            "|---|---:|---:|---:|---|",
        ]
    )
    ranked = sorted(
        (
            row
            for row in rows
            if row["legacy_ev_full"] is not None and row["new_ev_full"] is not None
        ),
        key=lambda row: abs(Decimal(row["new_ev_full"]) - Decimal(row["legacy_ev_full"])),
        reverse=True,
    )
    for row in ranked[:15]:
        difference = Decimal(row["new_ev_full"]) - Decimal(row["legacy_ev_full"])
        lines.append(
            f"| {row['game_number']} {row['name']} | {_format(row['legacy_ev_full'])} | "
            f"{_format(row['new_ev_full'])} | {_format(difference)} | "
            f"{row['data_status']} |"
        )
    lines.extend(
        [
            "",
            "## Cutover Decision",
            "",
            "- Legacy columns remain physically present and unchanged for audit.",
            "- Nightly/import code no longer writes legacy estimated columns.",
            "- Current reports and rankings use versioned analytics views only.",
            "- The legacy report command is disabled with an explicit deprecation message.",
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"comparison={output}")
    print(f"games={len(rows)} model={args.model_version} source_run={rows[0]['source_run_id']}")
    return 0


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def _format(value) -> str:
    return "N/A" if value is None else f"{Decimal(value):,.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
