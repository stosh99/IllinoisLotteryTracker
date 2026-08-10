#!/usr/bin/env python3
"""Run the read-only source provenance and reconciliation audit."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import Connection, inspect, text

from illinois_lottery_tracker.db import get_engine


def _scalar(connection: Connection, statement: str) -> int:
    return int(connection.execute(text(statement)).scalar_one())


def run_audit(connection: Connection) -> dict[str, Any]:
    required = {
        "scrape_runs",
        "raw_source_snapshots",
        "games",
        "game_snapshots",
        "prize_tier_snapshots",
    }
    present = set(inspect(connection).get_table_names())
    missing = sorted(required - present)
    if missing:
        return {"ok": False, "missing_tables": missing, "inventory": {}, "failures": {}}

    inventory = {
        table_name: _scalar(connection, f'SELECT count(*) FROM "{table_name}"')
        for table_name in sorted(required)
    }
    failures = {
        "tier_count_invariants": _scalar(
            connection,
            """
            SELECT count(*) FROM prize_tier_snapshots
            WHERE original_count IS NULL OR remaining_count IS NULL OR claimed_count IS NULL
               OR original_count < 0 OR remaining_count < 0 OR claimed_count < 0
               OR remaining_count > original_count
               OR claimed_count <> original_count - remaining_count
            """,
        ),
        "rollup_mismatches": _scalar(
            connection,
            """
            WITH totals AS (
                SELECT game_snapshot_id,
                       sum(original_count) AS original_count,
                       sum(remaining_count) AS remaining_count,
                       sum(prize_amount * original_count) AS original_value,
                       sum(prize_amount * remaining_count) AS remaining_value
                FROM prize_tier_snapshots GROUP BY game_snapshot_id
            )
            SELECT count(*)
            FROM game_snapshots gs JOIN totals t ON t.game_snapshot_id = gs.id
            WHERE gs.total_original_winning_tickets IS DISTINCT FROM t.original_count
               OR gs.total_remaining_winning_tickets IS DISTINCT FROM t.remaining_count
               OR gs.total_original_prize_value IS DISTINCT FROM t.original_value
               OR gs.total_remaining_prize_value IS DISTINCT FROM t.remaining_value
            """,
        ),
        "fingerprint_mismatches": _scalar(
            connection,
            """
            WITH serialized AS (
                SELECT p.game_snapshot_id,
                       encode(sha256(convert_to(string_agg(
                           to_char(p.prize_amount, 'FM999999999990.00') || ':' ||
                           p.original_count::text,
                           '|' ORDER BY p.prize_amount
                       ), 'UTF8')), 'hex') AS expected
                FROM prize_tier_snapshots p GROUP BY p.game_snapshot_id
            )
            SELECT count(*) FROM game_snapshots gs
            JOIN serialized s ON s.game_snapshot_id = gs.id
            WHERE gs.structure_fingerprint IS DISTINCT FROM s.expected
            """,
        ),
        "complete_run_provenance": _scalar(
            connection,
            """
            WITH actual AS (
                SELECT sr.id,
                       count(DISTINCT raw.id) AS raw_count,
                       count(DISTINCT gs.id) AS game_count,
                       count(DISTINCT p.id) AS tier_count
                FROM scrape_runs sr
                LEFT JOIN raw_source_snapshots raw ON raw.scrape_run_id = sr.id
                LEFT JOIN game_snapshots gs ON gs.scrape_run_id = sr.id
                LEFT JOIN prize_tier_snapshots p ON p.game_snapshot_id = gs.id
                WHERE sr.workflow = 'unpaid_prizes' AND sr.status = 'success'
                  AND sr.is_complete
                GROUP BY sr.id
            )
            SELECT count(*) FROM actual a JOIN scrape_runs sr ON sr.id = a.id
            WHERE a.raw_count <> 1 OR a.game_count <> sr.parsed_game_count
               OR a.tier_count <> sr.parsed_prize_tier_count
               OR sr.source_observed_at IS NULL OR sr.source_date IS NULL
               OR sr.source_sha256 IS NULL OR sr.pipeline_version IS NULL
            """,
        ),
        "duplicate_complete_hashes": _scalar(
            connection,
            """
            SELECT count(*) FROM (
                SELECT source_sha256
                FROM scrape_runs
                WHERE workflow = 'unpaid_prizes'
                  AND status = 'success' AND is_complete
                GROUP BY source_sha256 HAVING count(*) > 1
            ) duplicates
            """,
        ),
        "structure_changes": _scalar(
            connection,
            """
            SELECT count(*) FROM (
                SELECT gs.game_id, tier.prize_amount
                FROM game_snapshots gs
                JOIN prize_tier_snapshots tier ON tier.game_snapshot_id = gs.id
                JOIN scrape_runs run ON run.id = gs.scrape_run_id
                WHERE run.workflow = 'unpaid_prizes'
                  AND run.status = 'success' AND run.is_complete
                GROUP BY gs.game_id, tier.prize_amount
                HAVING count(DISTINCT tier.original_count) > 1
            ) changed
            """,
        ),
        "remaining_count_reversals": _scalar(
            connection,
            """
            SELECT count(*) FROM (
                SELECT tier.remaining_count,
                       lag(tier.remaining_count) OVER (
                         PARTITION BY snapshot.game_id, tier.prize_amount
                         ORDER BY run.source_observed_at, run.id
                       ) AS prior_remaining_count
                FROM game_snapshots snapshot
                JOIN scrape_runs run ON run.id = snapshot.scrape_run_id
                JOIN prize_tier_snapshots tier ON tier.game_snapshot_id = snapshot.id
                WHERE run.workflow = 'unpaid_prizes'
                  AND run.status = 'success' AND run.is_complete
            ) ordered
            WHERE remaining_count > prior_remaining_count
            """,
        ),
        "captured_time_mismatches": _scalar(
            connection,
            """
            SELECT count(*) FROM game_snapshots gs
            JOIN scrape_runs sr ON sr.id = gs.scrape_run_id
            WHERE sr.is_complete
              AND gs.captured_at IS DISTINCT FROM sr.source_observed_at
            """,
        ),
    }
    return {
        "ok": not missing and all(value == 0 for value in failures.values()),
        "missing_tables": missing,
        "inventory": inventory,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = get_engine()
        with engine.connect() as connection, connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            report = run_audit(connection)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: source audit failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Source audit: {'PASS' if report['ok'] else 'FAIL'}")
        for name, count in report["inventory"].items():
            print(f"  rows.{name}: {count}")
        for name, count in report["failures"].items():
            print(f"  failures.{name}: {count}")
        for table_name in report["missing_tables"]:
            print(f"  missing_table: {table_name}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
